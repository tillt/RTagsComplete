"""Tests for Idle Controller."""
import time

from os import path

from RTagsComplete.plugin import vc
from RTagsComplete.tests.gui_wrapper import GuiTestWrapper

class TestIdleController(GuiTestWrapper):
    """Test Idle Controller."""

    def setUp(self):
        """Test that setup view correctly sets up the view."""
        self.set_up()
        file_name = path.join(path.dirname(__file__),
                              'test_files',
                              'test.cpp')
        self.set_up_view(file_name)

        self.assertIsNotNone(self.view)

    def tearDown(self):
        self.tear_down()

    def test_init(self):
        vc_manager = vc.VCManager()
        controller = vc_manager.view_controller(self.view)

        self.assertIsNotNone(controller)
        self.assertIsNotNone(controller.idle)
