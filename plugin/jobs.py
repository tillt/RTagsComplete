# -*- coding: utf-8 -*-

"""Jobs.

Jobs are scheduled process runs.

"""

import re
import sublime
import subprocess

import logging

import xml.etree.ElementTree as etree

from concurrent import futures
from functools import partial
from time import time
from threading import RLock

from . import settings
from . import vc_manager

log = logging.getLogger("RTags")


class JobError:
    UNKNOWN = 0
    PROJECT_LOADING = 1
    NOT_INDEXED = 2
    RDM_DOWN = 3
    EXCEPTION = 4

    def __init__(self, code=UNKNOWN, message=""):
        self.code = code
        self.message = message

    def from_results(out, code=0):
        # Check if the file in question is not indexed by rtags.
        if out == "Not indexed\n":
            return JobError(
                JobError.NOT_INDEXED,
                "Not indexed.")
        elif out == "Project loading\n":
            return JobError(
                JobError.PROJECT_LOADING,
                "Project loading.")
        elif out.startswith("Can't seem to connect to server"):
            return JobError(
                JobError.RDM_DOWN,
                "Can't seem to connect to RTags server.")

        if code != 0:
            if out:
                message = "RTags failed with status {} and message:\n{}." \
                          .format(code, out.decode('utf-8'))
            else:
                message = "RTags failed with status {}.".format(code)
            return JobError(JobError.UNKNOWN, message)

        return None


class RTagsJob():

    def __init__(self, job_id, command_info, **kwargs):
        self.job_id = job_id
        self.command_info = command_info
        self.data = b''
        if 'data' in kwargs:
            self.data = kwargs['data']
        self.p = None
        if 'view' in kwargs:
            self.view = kwargs['view']
        if 'communicate' in kwargs:
            self.callback = kwargs['communicate']
        else:
            self.callback = self.communicate
        self.nodebug = 'nodebug' in kwargs
        self.kwargs = kwargs

    def prepare_command(self):
        return [settings.SettingsManager.get('rc_path')] + self.command_info

    def stop(self):
        try:
            log.debug("Killing job {}".format(self.p))
            if self.p:
                self.p.kill()
        except subprocess.ProcessLookupError:
            pass
        self.p = None

    def communicate(self, process, timeout=None):
        if not self.nodebug:
            log.debug("Static communicate with timeout {} for {}".format(
                timeout,
                self.callback))

        if not timeout:
            timeout = settings.SettingsManager.get('rc_timeout')
        (out, _) = process.communicate(input=self.data, timeout=timeout)

        if not self.nodebug:
            log.debug("Static communicate terminating")

        return out, JobError.from_results(
            out.decode('utf-8'),
            process.returncode)

    def run_process(self, timeout=None):
        out = b''
        error = None

        command = self.prepare_command()

        if not self.nodebug:
            log.debug("Starting process job {}".format(command))

        start_time = time()

        try:
            with subprocess.Popen(
                command,
                stderr=subprocess.STDOUT,
                stdout=subprocess.PIPE,
                    stdin=subprocess.PIPE) as process:

                self.p = process

                if not self.nodebug:
                    log.debug("Process running with timeout {},"
                              " input-length {}".format(
                                timeout, len(self.data)))
                    log.debug("Communicating with process via {}"
                              .format(self.callback))

                (out, error) = self.callback(process, timeout)

        except Exception as e:
            error = JobError(JobError.EXCEPTION, "Aborting with exception: {}"
                                                 .format(e))

        if not self.nodebug:
            log.debug("Output-length: {}".format(len(out)))
            log.debug("Process job ran for {:2.2f} seconds".format(
                time() - start_time))

        if error:
            log.error("Failed to run process job {} with error: {}"
                      .format(command, error.message))

        return (self.job_id, out, error)

    def run(self):
        return self.run_process()


class CompletionJob(RTagsJob):

    def __init__(self,
                 completion_job_id,
                 filename,
                 text,
                 size,
                 row,
                 col,
                 view):
        command_info = []

        # Auto-complete switch.
        command_info.append('-l')
        # The query.
        command_info.append('{}:{}:{}'.format(filename, row + 1, col + 1))
        # We want to complete on an unsaved file.
        command_info.append('--unsaved-file')
        # We launch rc utility with both filename:line:col and filename:length
        # because we're using modified file which is passed via stdin
        # (see --unsaved-file switch)
        command_info.append('{}:{}'.format(filename, size))
        # Make this query block until getting answered.
        command_info.append('--synchronous-completions')

        super().__init__(
            completion_job_id,
            command_info,
            **{'data': text, 'view': view})

    def run(self):
        (job_id, out, error) = self.run_process(60)

        suggestions = []

        if not error:
            for line in out.splitlines():
                # log.debug(line)
                # line is like this
                # "process void process(CompletionThread::Request *request)
                # CXXMethod" "reparseTime int reparseTime VarDecl"
                # "dump String dump() CXXMethod"
                # "request CompletionThread::Request * request ParmDecl"
                # we want it to show as process()\tCXXMethod
                #
                # output is list of tuples: first tuple element is what
                # we see in popup menu second is what inserted into file.
                # '$0' is where to place cursor.
                # TODO play with $1, ${2:int}, ${3:string} and so on.
                elements = line.decode('utf-8').split()
                suggestions.append(('{}\t{}'.format(' '.join(elements[1:-1]), elements[-1]),
                                    '{}$0'.format(elements[0])))
            log.debug("Completion done")

        return (job_id, suggestions, error, self.view)


class ReindexJob(RTagsJob):

    def __init__(self, job_id, filename, text=b'', view=None):
        command_info = ["-V", filename]
        if len(text):
            command_info += ["--unsaved-file", "{}:{}"
                             .format(filename, len(text))]

        super().__init__(job_id, command_info, **{'data': text, 'view': view})

    def run(self):
        return self.run_process(300)


class MonitorJob(RTagsJob):

    def __init__(self, job_id):
        super().__init__(job_id, ['-m'], **{'communicate': self.communicate})

    def run(self):
        log.debug("Running MonitorJob process NOW...")
        return self.run_process()

    def communicate(self, process, timeout=None):
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

            error = JobError.from_results(line)
            if error:
                return (b'', error)

            # Keep on accumulating XML data until we have a closing tag,
            # matching our start_tag.

            if '</{}>'.format(start_tag) in line:
                tree = etree.fromstring(buffer)
                # OK, we received some chunk
                # check if it is progress update
                if (tree.tag == 'progress' and
                    tree.attrib['index'] == tree.attrib['total'] and
                        vc_manager.flag == vc_manager.NAVIGATION_REQUESTED):
                    # notify about event
                    sublime.active_window().active_view().run_command(
                        'rtags_location',
                        {'switches': vc_manager.switches})

                if tree.tag == 'checkstyle':
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
                                    issue['length'] = int(
                                        error.attrib["length"])
                                else:
                                    issue['length'] = -1
                                issue['message'] = error.attrib["message"]

                                issues[mapping[error.attrib["severity"]]].append(issue)

                        log.debug("Got fixits to send")

                        sublime.active_window().active_view().run_command(
                            'rtags_fixit',
                            {
                                'filename': file.attrib["name"],
                                'issues': issues
                            })

                buffer = ''
                start_tag = ''

        log.debug("Data callback terminating")
        return (b'', None)


class JobController():
    pool = futures.ThreadPoolExecutor(max_workers=4)
    lock = RLock()
    thread_map = {}
    unique_index = 0

    @staticmethod
    def next_id():
        JobController.unique_index += 1
        return "{}".format(JobController.unique_index)

    @staticmethod
    def run_async(job, callback=None, indicator=None):
        with JobController.lock:
            if job.job_id in JobController.thread_map.keys():
                log.debug("Job {} still active".format(job.job_id))
                return

            log.debug("Starting async job {}".format(job.job_id))

            if indicator:
                indicator.start()

            future = JobController.pool.submit(job.run)
            if callback:
                future.add_done_callback(callback)
            future.add_done_callback(
                partial(JobController.done, job=job, indicator=indicator))

            JobController.thread_map[job.job_id] = (future, job)

    @staticmethod
    def run_sync(job, timeout=None):
        # Debug logging every single run_sync request is too verbose
        # if polling is used for gathering rc's indexing status
        return job.run_process(timeout)

    @staticmethod
    def stop(job_id):
        future = None
        job = None

        with JobController.lock:
            if job_id in JobController.thread_map.keys():
                (future, job) = JobController.thread_map[job_id]

        if not job:
            log.debug("Job not started")
            return

        log.debug("Stopping job {}={}".format(job_id, job.job_id))
        log.debug("Job {} should now disappear with {}".format(job_id, future))

        # FIXME(tillt): This entire part appears to either not have the
        # intended results or the debug output time skewing the displayed
        # results; complete job termination is NOT waited upon.

        # Signal that we are not interested in results.
        future.cancel()

        # Terminate any underlying subprocesses.
        job.stop()

        log.debug("Waiting for job {}".format(job_id))

        # Wait upon the job to terminate.
        future.result(15)

        log.debug("Waited for job {}".format(job_id))

        if future.done():
            log.debug("Done with that job {}".format(job_id))

        if future.cancelled():
            log.debug("Cancelled job {}".format(job_id))

    @staticmethod
    def done(future, job, indicator):
        log.debug("Job {} done".format(job.job_id))

        if not future.done():
            log.debug("Job wasn't really done")

        if future.cancelled():
            log.debug("Job was cancelled")

        if indicator:
            indicator.stop()

        with JobController.lock:
            del JobController.thread_map[job.job_id]
            log.debug("Removed bookkeeping for job {}".format(job.job_id))

    @staticmethod
    def job(job_id):
        job = None
        with JobController.lock:
            (_, job) = JobController.thread_map[job_id]
        return job

    @staticmethod
    def future(job_id):
        future = None
        with JobController.lock:
            (future, _) = JobController.thread_map[job_id]
        return future

    @staticmethod
    def stop_all():
        with JobController.lock:
            log.debug("Stopping running threads {}".format(list(
                JobController.thread_map)))
            for job_id in list(JobController.thread_map):
                JobController.stop(job_id)
