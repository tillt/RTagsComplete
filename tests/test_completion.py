"""Tests for Completion Controller."""
from concurrent import futures
from os import path
from unittest import mock

from RTagsComplete.plugin import completion
from RTagsComplete.plugin import jobs
from RTagsComplete.tests.gui_wrapper import GuiTestWrapper


class TestCompletionController(GuiTestWrapper):
    """Test Progress Indicator."""

    def setUp(self):
        """Test that setup view correctly sets up the view."""
        self.set_up()
        file_name = path.join(path.dirname(__file__),
                              'test_files',
                              'test.cpp')
        self.set_up_view(file_name, 16, 5)

        self.assertIsNotNone(self.view)

    def tearDown(self):
        self.tear_down()

    @mock.patch.object(jobs.CompletionJob, 'run')
    def test_completion_at(self, mock_run):
        prefix = ""
        locations = [182]

        trigger_position = locations[0] - len(prefix)
        job_id = "RTCompletionJob{}".format(trigger_position)
        out = [
            ('void bar() CXXMethod\tA', 'bar$0'),
            ('void foo(double a) CXXMethod\tA', 'foo$0'),
            ('A:: ClassDecl\tA', 'A$0'),
            ('A & operator=(const A &) CXXMethod\tA', 'operator=$0'),
            ('A & operator=(A &&) CXXMethod\tA', 'operator=$0'),
            ('void ~A() CXXDestructor\tA', '~A$0')
        ]
        mock_run.return_value = (job_id, out, None, self.view)

        completion.query(self.view, prefix, locations)

        future = jobs.JobController.future(job_id)

        futures.wait([future], return_when=futures.ALL_COMPLETED)
        self.assertTrue(future.done())

        self.assertEqual(mock_run.call_count, 1)

        (tested_job_id, tested_out, _, _) = future.result()

        self.assertEqual(tested_job_id, job_id)
        self.assertEqual(tested_out, out)

        # We should now see a completions list on the screen.
        # TODO(tillt): Find a way to locate and maybe even validate
        # the completion popup content.
