# -*- coding: utf-8 -*-

"""Jobs.

Jobs are scheduled process runs.

"""

import sublime
import subprocess

import logging

import json

from concurrent import futures
from functools import partial
from time import time
from threading import RLock

from . import settings
from . import tools

log = logging.getLogger("RTags")


class JobError:
    UNKNOWN = 0
    PROJECT_LOADING = 1
    NOT_INDEXED = 2
    RDM_DOWN = 3
    EXCEPTION = 4
    ABORTED = 5

    def __init__(self, code=UNKNOWN, message=""):
        self.code = code
        self.message = message

    def html_message(self):
        return self.message.replace('\n', '<br />')

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
                "Failed to connect to RTags server.")

        if code != 0:
            if code < 0:
                return JobError(JobError.ABORTED, "Command aborted.")

            message = "RTags command failed with status {}".format(code)

            if out:
                # In rare cases or due to invalid invocations we might
                # get a string instead of bytes.
                if isinstance(out, bytes):
                    details = out.decode('utf-8')
                else:
                    details = out

                message += " and message:\n{}".format(details)

            return JobError(JobError.UNKNOWN, message + ".")

        return None


class RTagsJob():

    def __init__(self, job_id, command_info, **kwargs):
        self.job_id = job_id
        self.command_info = command_info
        self.timeout = None
        if 'timeout' in kwargs:
            self.timeout = kwargs['timeout']
        else:
            self.timeout = settings.get('rc_timeout')
        self.data = b''
        if 'data' in kwargs:
            self.data = kwargs['data']
        self.p = futures.Future()
        if 'view' in kwargs:
            self.view = kwargs['view']
        if 'communicate' in kwargs:
            self.callback = kwargs['communicate']
        else:
            self.callback = self.communicate
        self.nodebug = 'nodebug' in kwargs
        self.kwargs = kwargs
        self.command_active = futures.Future()

    def prepare_command(self):
        return [settings.get('rc_path')] + self.command_info

    def active(self):
        return self.p.done()

    def stop(self):
        start_time = time()

        # Blocks until process has started.
        process = self.p.result()

        log.debug("Awaited process startup for {:2.6f} seconds".format(
            time() - start_time))

        log.debug("Killing job command subprocess {}".format(process))

        # We abort the process by sending a SIGKILL and by closing all
        # connected pipes.
        try:
            process.kill()
        except OSError:
            # silently fail if the subprocess has exited already
            pass

    def communicate(self, process, timeout=None):
        if not self.nodebug:
            log.debug("Static communicate with timeout {} for {}".format(
                timeout,
                self.callback))

        if not timeout:
            timeout = self.timeout

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

                self.p.set_result(process)

                if not self.nodebug:
                    log.debug("Process running with timeout {},"
                              " input-length {}".format(
                                timeout, len(self.data)))
                    log.debug("Communicating with process via {}"
                              .format(self.callback))

                (out, error) = self.callback(process, timeout)

        except Exception as e:
            error = JobError(
                JobError.EXCEPTION,
                "Aborting with exception: {}".format(e))

        if not self.nodebug:
            log.debug("Output-length: {}".format(len(out)))
            log.debug("Process job ran for {:2.5f} seconds".format(
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
        command_info.append('--code-complete-include-macros')

        # command_info.append('--max')
        # command_info.append(MAX_FROM_DEFAULTS)

        super().__init__(
            completion_job_id,
            command_info,
            **{'data': text, 'view': view})

    def render(self, line):
        # Line is like this
        #  "process void process(CompletionThread::Request *request) CXXMethod"
        #  "reparseTime int reparseTime VarDecl"
        #  "dump String dump() CXXMethod"
        #  "request CompletionThread::Request * request ParmDecl"
        #
        # We want it to show as
        #  "process($0${1:CompletionThread::Request *request})\tCXXMethod"
        #  "reparseTime$0\tVarDecl"
        #  "dump()$0\tCXXMethod"
        #  "request$0\tParmDecl"
        #
        # Output is list of tuples:
        # - first tuple element is what we see in popup menu
        # - second is what is inserted into the file
        #
        # '$0' is where to place cursor.
        # '${[n]:type [name]}' is an argument.
        elements = line.decode('utf-8').split()
        display = "{}\t{}".format(' '.join(elements[1:-1]), elements[-1])

        middle = ' '.join(elements[1:-1])

        # Locate brackets for argument inspection.
        left = middle.find('(')
        right = middle.rfind(')')

        # The default completion is just the symbol name.
        completion = "{}$0".format(elements[0])

        # Completions with brackets.
        if left != -1 and right != -1 and right > left:
            # Empty parameter list.
            if right - left == 1:
                completion = "{}()$0".format(elements[0])
            else:
                parameters = middle[left+1:right].split(', ')
                index = 1
                arguments = []
                for parameter in parameters:
                    arguments.append(
                        "${" + "{}:{}".format(index, parameter) + "}")
                    index += 1

                completion = "{}($0{})".format(elements[0],
                                               ", ".join(arguments))

        return display, completion

    def run(self):
        (job_id, out, error) = self.run_process(60)

        suggestions = []

        if not error:
            for line in out.splitlines():
                display, render = self.render(line)
                suggestions.append((display, render))

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
        super().__init__(
            job_id,
            ['--json', '-m'],
            **{'communicate': self.communicate})

    def run(self):
        log.debug("Running MonitorJob process NOW...")
        return self.run_process()

    def communicate(self, process, timeout=None):
        log.debug("In data callback {}".format(process.stdout))

        buffer = ''  # JSON to be parsed

        brackets_open = 0

        for line in iter(process.stdout.readline, b''):
            line = line.decode('utf-8')

            brackets_open += line.count('{')
            brackets_open -= line.count('}')

            # Keep on accumulating JSON object data until its end.
            buffer += line

            error = JobError.from_results(line)
            if error:
                return (b'', error)

            if brackets_open <= 0:
                dictionary = json.loads(buffer)

                log.debug("JSON dump dictionary: {}".format(dictionary))

                if 'checkStyle' in dictionary:
                    checkstyle = dictionary['checkStyle']

                    mapping = {
                        'warning': 'warning',
                        'error': 'error',
                        'fixit': 'error'
                    }

                    issues = {
                        'warning': [],
                        'error': [],
                        'note': []
                    }

                    for file in checkstyle.keys():
                        for error in checkstyle[file]:
                            if not error['type'] in mapping.keys():
                                continue

                            issue = {}
                            issue['type'] = mapping[error['type']]
                            issue['line'] = int(error['line'])
                            issue['column'] = int(error['column'])
                            if 'length' in error.keys():
                                issue['length'] = int(error['length'])
                            issue['message'] = error['message']
                            issue['subissues'] = []

                            if 'children' in error.keys():
                                for child in error['children']:
                                    if not child['type'] == 'note':
                                        log.warning(
                                            "Ignoring subissue type {}".format(
                                                child['type']))
                                        continue

                                    context_file = file
                                    if 'file' in child:
                                        context_file = child['file']
                                    context_line = int(child['line'])
                                    context_column = int(child['column'])
                                    context_length = 0
                                    if 'length' in child.keys():
                                        context_length = int(child['length'])

                                    message = child['message']
                                    context = ""

                                    if context_line > 0:
                                        if context_file == file:
                                            context = tools.Utilities.file_content(
                                                context_file,
                                                context_line)
                                            message += "\n\a{}\b".format(context.strip())
                                        else:
                                            context = tools.Utilities.file_content(
                                                context_file,
                                                context_line)
                                            message += " \v{}\f\n\a{}\b".format(
                                                context_file,
                                                context.strip())

                                    subissue = {}
                                    subissue['type'] = 'note'
                                    subissue['file'] = context_file
                                    subissue['line'] = context_line
                                    subissue['column'] = context_column
                                    subissue['message'] = message
                                    subissue['length'] = context_length

                                    issue['subissues'].append(subissue)

                            issues[mapping[error['type']]].append(issue)

                        log.debug("Triggering fixits update")

                        sublime.active_window().active_view().run_command(
                            'rtags_fixit',
                            {
                                'filename': file,
                                'issues': issues
                            })

                buffer = ''

            if process.poll():
                log.debug("Process has terminated")

                return (b'', None)

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
        future = None
        with JobController.lock:
            if job.job_id in JobController.thread_map.keys():
                log.debug("Job {} still active".format(job.job_id))
                return None

            log.debug("Starting async job {}".format(job.job_id))

            if indicator:
                indicator.start()

            future = JobController.pool.submit(job.run)

            # Push the future and job onto our thread-map.
            #
            # Note that this has to happen before we install any
            # callbacks. This way we make sure any callback invocation
            # is able to access its own the thread-map entry, assuming
            # the job is already done when we reach this point.
            JobController.thread_map[job.job_id] = (future, job)

        if callback:
            future.add_done_callback(callback)

        future.add_done_callback(
            partial(JobController.done, job=job, indicator=indicator))

        return future

    @staticmethod
    def run_sync(job, timeout=None):
        # Debug logging every single run_sync request is too verbose
        # if polling is used for gathering rc's indexing status.
        return job.run_process(timeout)

    @staticmethod
    def stop(job_id):
        future = None
        job = None

        with JobController.lock:
            if job_id in JobController.thread_map.keys():
                (future, job) = JobController.thread_map[job_id]

        if not future:
            log.debug("Job {} never started".format(job_id))
            return

        start_time = time()

        log.debug("Stopping Job {} with {}".format(job_id, future))

        # Terminate any underlying subprocess.
        job.stop()

        # Wait upon the job to terminate.
        futures.wait([future], timeout=15, return_when=futures.ALL_COMPLETED)

        log.debug("Waited {:2.2f} for job {} ".format(
            time() - start_time,
            job_id))

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
            if job.job_id in JobController.thread_map:
                del JobController.thread_map[job.job_id]
                log.debug("Removed bookkeeping for job {}".format(job.job_id))
            else:
                log.error("Bookeeping does not know about job {}".format(job.job_id))

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
