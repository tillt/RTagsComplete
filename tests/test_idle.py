"""Tests for Idle Controller."""
from os import path

from RTagsComplete.plugin import vc_manager
from RTagsComplete.tests.gui_wrapper import GuiTestWrapper


class TestIdleController(GuiTestWrapper):
    """Test Idle Controller."""

    def setUp(self):
        """Test that setup view correctly sets up the view."""
        super().setUp()
        file_name = path.join(path.dirname(__file__),
                              'test_files',
                              'test_fixits.cpp')
        self.set_up_view(file_name)

        self.assertIsNotNone(self.view)

    def test_init(self):
        controller = vc_manager.view_controller(self.view)

        self.assertIsNotNone(controller)
        self.assertIsNotNone(controller.idle)

    def idle_callback(self):
        self.idle_callback_hit = True

    def test_idle(self):
        self.idle_callback_hit = True
