"""Tests for Completion Controller."""
from concurrent import futures
from os import path
from unittest import mock

from RTagsComplete.plugin import completion
from RTagsComplete.plugin import jobs
from RTagsComplete.tests.gui_wrapper import GuiTestWrapper


class TestCompletionController(GuiTestWrapper):
    def setUp(self):
        """Test that setup view correctly sets up the view."""
        self.set_up()
        file_name = path.join(path.dirname(__file__),
                              'test_files',
                              'test_completion.cpp')
        self.set_up_view(file_name, 16, 5)

        self.assertIsNotNone(self.view)

    def tearDown(self):
        self.tear_down()

    @mock.patch("subprocess.Popen")
    def test_completion_at(self, mock_popen):
        prefix = ""
        locations = [182]

        trigger_position = locations[0] - len(prefix)
        job_id = "RTCompletionJob{}".format(trigger_position)

        # Mock subprocess.
        mock_process = mock.Mock()

        # `communicate` returns a set of bytestreams.
        mock_process.communicate = mock.Mock(return_value=(
            b' bar void bar() CXXMethod  A \n'
            b' foo void foo(double a) CXXMethod  A \n'
            b' A A:: ClassDecl  A \n'
            b' operator= A & operator=(const A &) CXXMethod  A \n'
            b' operator= A & operator=(A &&) CXXMethod  A \n'
            b' ~A void ~A() CXXDestructor  A \n',
            b''))

        # `__enter__` returns the mock subprocess.
        mock_process.__enter__ = mock.Mock(return_value=mock_process)

        # `__exit__` does nothing.
        mock_process.__exit__ = mock.Mock(return_value=None)

        # `returncode` returns 0.
        type(mock_process).returncode = mock.PropertyMock(return_value=0)

        # `Popen` returns the mock subprocess.
        mock_popen.return_value = mock_process

        # Request a completion.
        completion.query(self.view, prefix, locations)

        # Await that completion job.
        future = jobs.JobController.future(job_id)
        futures.wait([future], return_when=futures.ALL_COMPLETED)

        self.assertTrue(future.done())

        self.assertTrue(mock_popen.call_count, 1)

        (tested_job_id, tested_out, _, _) = future.result()

        expect_out = [
            ('void bar() CXXMethod\tA', 'bar$0'),
            ('void foo(double a) CXXMethod\tA', 'foo$0'),
            ('A:: ClassDecl\tA', 'A$0'),
            ('A & operator=(const A &) CXXMethod\tA', 'operator=$0'),
            ('A & operator=(A &&) CXXMethod\tA', 'operator=$0'),
            ('void ~A() CXXDestructor\tA', '~A$0')
        ]

        self.assertEqual(tested_job_id, job_id)
        self.assertEqual(tested_out, expect_out)

        # We should now see a completions list on the screen.
        # TODO(tillt): Find a way to locate and maybe even validate
        # the completion popup content.
