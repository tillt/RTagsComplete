# -*- coding: utf-8 -*-

"""RTagsComplete plugin for Sublime Text 3.

Provides completion suggestions and much more for C/C++ languages
based on RTags.

Original code by Sergei Turukin.
Hacked with plenty of new features by Till Toenshoff.
Some code lifted from EasyClangComplete by Igor Bogoslavskyi.

TODO(tillt): This desperately needs a refactor into submodules with
clean APIs instead of this horrible spaghetti code.
TODO(tillt): The current tests are broken and need to get redone.
TODO(tillt): Life is more important than any of the above, so fuck it.
"""

import re
import sublime
import sublime_plugin
import subprocess

import logging

import xml.etree.ElementTree as etree

from functools import partial

from . import settings

log = logging.getLogger("RTags")

class RTagsJob():

    def __init__(self, job_id, command_info, data=None):
        self.job_id = job_id
        self.command_info = command_info
        self.data = data
        self.p = None

    def prepare_command(self):
        command = [settings.SettingsManager.get('rc_path')]
        command += self.command_info

        if self.data:
            stdin = subprocess.PIPE
        else:
            stdin = self.data

        return (command, stdin)


class SyncRTagsJob(RTagsJob):

    def run_process(self, nodebug=False):
        out = None

        (command, pipe) = self.prepare_command()

        #log.debug("Starting {}".format(command))

        with subprocess.Popen(
            command,
            stderr=subprocess.STDOUT,
            stdout=subprocess.PIPE,
            stdin=pipe) as p:

            (out, _) = p.communicate(input=self.data, timeout=settings.SettingsManager.get('rc_timeout'))

        return out


class AsyncRTagsJob(RTagsJob):

    def __init__(self, job_id, command_info, data=None, data_callback=None):
        RTagsJob.__init__(self, job_id, command_info, data)
        self.p = None
        self.data_callback = data_callback

    def run_process(self, nodebug=False):
        (command, pipe) = self.prepare_command()

        log.debug("Starting async {}".format(command))

        with subprocess.Popen(
            command,
            stderr=subprocess.STDOUT,
            stdout=subprocess.PIPE,
            stdin=pipe) as process:

            log.debug("async running")

            if self.data_callback:
                log.debug("callback running {}".format(self.data_callback))
                self.data_callback(process=process)

        log.debug("async done")
        return None

     # Unused so far - may be pointless.
    def stop(self):
        if self.p:
            self.p.kill()
        self.p = None


class CompletionJob(SyncRTagsJob):

    def __init__(self, view, completion_job_id, filename, text, size, row, col):
        command_info = []

        # Auto-complete switch.
        command_info.append('-l')
        # The query.
        command_info.append('{}:{}:{}'.format(filename, row + 1, col + 1))
        # We want to complete on an unsaved file.
        command_info.append('--unsaved-file')
        # We launch rc utility with both filename:line:col and filename:length
        # because we're using modified file which is passed via stdin (see --unsaved-file
        # switch)
        command_info.append('{}:{}'.format(filename, size))
        # Make this query block until getting answered.
        command_info.append('--synchronous-completions')

        self.view = view

        SyncRTagsJob.__init__(self, completion_job_id, command_info, text)

    def run(self):
        log.debug("Completion starting")
        out  = self.run_process()
        log.debug("Completion returned")

        suggestions = []
        for line in out.splitlines():
            # log.debug(line)
            # line is like this
            # "process void process(CompletionThread::Request *request) CXXMethod"
            # "reparseTime int reparseTime VarDecl"
            # "dump String dump() CXXMethod"
            # "request CompletionThread::Request * request ParmDecl"
            # we want it to show as process()\tCXXMethod
            #
            # output is list of tuples: first tuple element is what we see in popup menu
            # second is what inserted into file. '$0' is where to place cursor.
            # TODO play with $1, ${2:int}, ${3:string} and so on.
            elements = line.decode('utf-8').split()
            suggestions.append(('{}\t{}'.format(' '.join(elements[1:-1]), elements[-1]),
                                '{}$0'.format(elements[0])))

        log.debug("Completion done")
        return (self.view, self.job_id, suggestions)


class MonitorJob(AsyncRTagsJob):

    def __init__(self, job_id):
        #AsyncRTagsJob.__init__(self, job_id, ['-m'], None, partial(self.data_callback, self=self))
        AsyncRTagsJob.__init__(self, job_id, ['-m'], None, lambda process:MonitorJob.data_callback(process))

    def run(self):
        return self.run_process()

    def data_callback(process):
        log.debug("In data callback {}".format(process.stdout))
        rgxp = re.compile(r'<(\w+)')
        buffer = ''  # xml to be parsed
        start_tag = ''

        for line in iter(process.stdout.readline, b''):
            line = line.decode('utf-8')
            process.poll()

            if not start_tag:
                start_tag = re.findall(rgxp, line)
                start_tag = start_tag[0] if len(start_tag) else ''

            buffer += line

            if "Can't seem to connect to server" in line:
                log.error(line)
                #if sublime.ok_cancel_dialog(
                #    "Can't seem to connect to server. Make sure RTags `rdm` is running, then retry.",
                #    "Retry"):
                #    #self.run()

            # Keep on accumulating XML data until we have a closing tag,
            # matching our start_tag.

            if '</{}>'.format(start_tag) in line:
                tree = etree.fromstring(buffer)
                # OK, we received some chunk
                # check if it is progress update
                if (tree.tag == 'progress' and
                        tree.attrib['index'] == tree.attrib['total'] and
                        navigation_helper.flag == NavigationHelper.NAVIGATION_REQUESTED):
                    # notify about event
                    sublime.active_window().active_view().run_command(
                        'rtags_location',
                        {'switches': navigation_helper.switches})

                if  tree.tag == 'checkstyle':
                    key = 0

                    mapping = {
                        'warning': 'warning',
                        'error': 'error',
                        'fixit': 'error'
                    }

                    issues = {
                        'warning': [],
                        'error': []
                    }

                    for file in tree.findall('file'):
                        for error in file.findall('error'):
                            if error.attrib["severity"] in mapping.keys():
                                issue = {}
                                issue['line'] = int(error.attrib["line"])
                                issue['column'] = int(error.attrib["column"])
                                if 'length' in error.attrib:
                                    issue['length'] = int(error.attrib["length"])
                                else:
                                    issue['length'] = -1
                                issue['message'] = error.attrib["message"]

                                issues[mapping[error.attrib["severity"]]].append(issue)

                        log.debug("Got fixits to send.")

                        sublime.active_window().active_view().run_command(
                            'rtags_fixit',
                            {
                                'filename': file.attrib["name"],
                                'issues': issues
                            })

                buffer = ''
                start_tag = ''

        log.debug("Data callback terminating")
