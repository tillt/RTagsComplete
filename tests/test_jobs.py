"""Tests for Job Controller."""
import logging
import time
import uuid

from concurrent import futures
from functools import partial
from unittest import TestCase, mock

from RTagsComplete.plugin import jobs

log = logging.getLogger("RTags")
log.setLevel(logging.DEBUG)
log.propagate = False

formatter_default = logging.Formatter(
    '%(name)s:%(levelname)s: %(message)s')
formatter_verbose = logging.Formatter(
    '%(name)s:%(levelname)s: %(asctime)-15s %(filename)s::%(funcName)s'
    ' [%(threadName)s]: %(message)s')


class TestJob(jobs.RTagsJob):

    def __init__(self, test_job_id, command_info):
        jobs.RTagsJob.__init__(
            self, test_job_id, command_info, **{'data': b'', 'view': None})

    def prepare_command(self):
        return self.command_info


class TestJobController(TestCase):
    """Test Job Controller."""

    expect = 0

    def command_done(
        self,
        future,
        expect_error,
        expect_out,
        expect_job_id,
            **kwargs):
        log.debug("Command done callback hit {}".format(future))

        self.expect = self.expect - 1

        if not future.done():
            log.warning("Command future failed")
            return

        if future.cancelled():
            log.warning(("Command future aborted"))
            return

        (job_id, out, error) = future.result()

        self.assertEqual(job_id, expect_job_id)
        if expect_out:
            self.assertEqual(out, expect_out)
        if expect_error:
            self.assertEqual(error, expect_error)

    def test_sync(self):
        """Test running a synchronous job."""
        job_id = "TestSyncCommand" + jobs.JobController.next_id()

        (received_job_id, received_out, received_error) = jobs.JobController.run_sync(
            TestJob(job_id, ['/bin/sh', '-c', 'echo foo']))

        self.assertEqual(received_error, None)
        self.assertEqual(received_job_id, job_id)
        self.assertEqual(received_out.decode('utf-8'), "foo\n")

    def test_async(self):
        """Test running an asynchronous job."""
        job_id = "TestAsyncCommand" + jobs.JobController.next_id()

        self.assertEqual(self.expect, 0)

        self.expect = self.expect + 1

        future = jobs.JobController.run_async(
            TestJob(job_id, ['/bin/sh', '-c', 'sleep 1']),
            partial(
                self.command_done,
                expect_error=None,
                expect_out='',
                expect_job_id=job_id))

        futures.wait([future], return_when=futures.ALL_COMPLETED)
        self.assertTrue(future.done())

        self.assertEqual(self.expect, 0)

    def test_async_abort(self):
        """Test running an asynchronous job."""
        job_id = "TestAsyncCommand" + jobs.JobController.next_id()

        self.assertEqual(self.expect, 0)

        self.expect = self.expect + 1

        future = jobs.JobController.run_async(
            TestJob(job_id, ['/bin/sh', '-c', 'sleep 10000']),
            partial(
                self.command_done,
                expect_error=None,
                expect_out='',
                expect_job_id=job_id))

        self.assertFalse(future.done())

        jobs.JobController.ab


    @mock.patch.object(jobs.RTagsJob, 'run')
    def test_mock_async(self, mock_run):
        """Test that an asyncronous callup of a mocked Job delivers its
           state as expected through JobManager processing."""
        job_id = "TestAsyncMock-" + str(uuid.uuid4())
        out = b'test'

        mock_run.return_value = (job_id, out, None)

        future = jobs.JobController.run_async(jobs.RTagsJob(job_id, ['']))

        futures.wait([future], return_when=futures.ALL_COMPLETED)
        self.assertTrue(future.done())

        self.assertEqual(mock_run.call_count, 1)

        (tested_job_id, tested_out, _) = future.result()

        self.assertEqual(tested_job_id, job_id)
        self.assertEqual(tested_out, out)

    @mock.patch("subprocess.Popen", autospec=True)
    def test_mock_async_process(self, mock_popen):
        """Test that an asyncronous callup of a mocked subprocess delivers
           its state as expected through JobManager processing."""
        param = [
            (0, b'Mocked stdout', None),
            (1, b"Mocked failure", jobs.JobError.UNKNOWN),
            (0, b"Not indexed", jobs.JobError.NOT_INDEXED),
            (0, b"Project loading", jobs.JobError.PROJECT_LOADING),
            (0, b"Can't seem to connect to server", jobs.JobError.RDM_DOWN)]

        for (result, stdout, code) in param:
            job_id = "TestMockProcess-" + str(uuid.uuid4())

            log.debug("Job {} gets parameters {}, {}, {}".format(
                      job_id, result, stdout, code))

            # Mock subprocess.
            mock_process = mock.Mock()
            # `communicate` returns a set of bytestreams.
            mock_process.communicate = mock.Mock(return_value=(stdout, b''))

            # `__enter__` returns the mock subprocess.
            mock_process.__enter__ = mock.Mock(return_value=mock_process)

            # `__exit__` does nothing.
            mock_process.__exit__ = mock.Mock(return_value=None)

            # property `returncode` is parameterized.
            type(mock_process).returncode = mock.PropertyMock(
                return_value=result)

            # `Popen` returns the mock subprocess.
            mock_popen.return_value = mock_process

            future = jobs.JobController.run_async(jobs.RTagsJob(job_id, ['']))

            futures.wait([future], return_when=futures.ALL_COMPLETED)
            self.assertTrue(future.done())

            self.assertTrue(mock_popen.call_count, 1)

            (tested_job_id, tested_out, tested_err) = future.result()

            self.assertEqual(tested_job_id, job_id)

            if tested_err:
                self.assertEqual(tested_err.code, code)
            else:
                self.assertEqual(tested_err, None)
                self.assertEqual(tested_out, stdout)
