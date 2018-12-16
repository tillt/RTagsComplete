"""Tests for Progress Controller."""
import time

from os import path

from RTagsComplete.plugin import vc_manager
from RTagsComplete.tests.gui_wrapper import GuiTestWrapper


class TestProgressIndicator(GuiTestWrapper):
    """Test Progress Indicator."""

    def setUp(self):
        """Test that setup view correctly sets up the view."""
        self.set_up()
        file_name = path.join(path.dirname(__file__),
                              'test_files',
                              'test_fixits.cpp')
        self.set_up_view(file_name)

        self.assertIsNotNone(self.view)

    def tearDown(self):
        self.tear_down()

    def test_init(self):
        """Test that the progress indicator is loaded but inactive, as
           expected."""
        controller = vc_manager.view_controller(self.view)

        self.assertIsNotNone(controller)
        self.assertIsNotNone(controller.status.progress)
        self.assertEqual(self.view.get_status(
            controller.status.progress.status_key), '')

    def test_startstop(self):
        """Test that starting the progress indicator makes it show
           something in the statusbar."""
        controller = vc_manager.view_controller(self.view)

        self.assertIsNotNone(controller)
        self.assertIsNotNone(controller.status.progress)

        controller.status.progress.start()

        time.sleep(0.5)

        self.assertEqual(controller.status.progress.active_counter, 1)
        self.assertNotEqual(self.view.get_status(
            controller.status.progress.status_key), '')

        controller.status.progress.stop()

        time.sleep(0.5)

        self.assertEqual(controller.status.progress.active_counter, 0)
        self.assertEqual(self.view.get_status(
            controller.status.progress.status_key), '')

    def test_interleaved(self):
        """Test that the progress indicator allows stacking of start
           and stop operations."""
        controller = vc_manager.view_controller(self.view)

        self.assertIsNotNone(controller)
        self.assertIsNotNone(controller.status.progress)

        controller.status.progress.start()
        controller.status.progress.start()

        time.sleep(0.5)

        self.assertEqual(controller.status.progress.active_counter, 2)

        controller.status.progress.stop()
        controller.status.progress.stop()

        time.sleep(0.5)

        self.assertEqual(controller.status.progress.active_counter, 0)
        self.assertEqual(self.view.get_status(
            controller.status.progress.status_key), '')

    def test_rapid(self):
        """Test that the starting and stopping in quick succession
           shows no surprises."""
        controller = vc_manager.view_controller(self.view)

        self.assertIsNotNone(controller)
        self.assertIsNotNone(controller.status.progress)

        controller.status.progress.start()
        controller.status.progress.stop()
        controller.status.progress.start()
        controller.status.progress.stop()

        time.sleep(0.5)

        self.assertEqual(controller.status.progress.active_counter, 0)
        self.assertEqual(self.view.get_status(
            controller.status.progress.status_key), '')
