"""Tests for Fixits Controller."""
import time

from os import path
from os import environ
from unittest import skipIf

from RTagsComplete.plugin import vc_manager
from RTagsComplete.tests.gui_wrapper import GuiTestWrapper


class TestFixitsController(GuiTestWrapper):
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
        """Test that a viewcontroller has set fixits controller member."""
        controller = vc_manager.view_controller(self.view)

        self.assertIsNotNone(controller)
        self.assertIsNotNone(controller.fixits)

    @skipIf("TRAVIS" in environ and environ["TRAVIS"] == "true", "Skipping this test on Travis CI.")
    def test_reindex(self):
        """Test that triggering fixits in quick succession has no
           quirky effects."""
        controller = vc_manager.view_controller(self.view)

        self.assertIsNotNone(controller)
        self.assertIsNotNone(controller.fixits)

        controller.fixits.reindex(True)
        controller.fixits.reindex(True)
        controller.fixits.reindex(True)

        time.sleep(0.5)

        self.assertEqual(controller.status.progress.active_counter, 1)

        time.sleep(10.0)

        self.assertEqual(controller.status.progress.active_counter, 0)

        self.assertEqual(self.view.get_status(
            controller.status.progress.status_key), '')
