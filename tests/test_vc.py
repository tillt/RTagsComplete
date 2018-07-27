"""Tests for VC Manager."""
import sublime
import sys

from os import path
from unittest import TestCase

from RTagsComplete.plugin import vc
from RTagsComplete.plugin.tools import PKG_NAME
from RTagsComplete.tests.gui_wrapper import GuiTestWrapper

class TestVC(GuiTestWrapper):
    """Test VC Manager."""

    def setUp(self):
        self.set_up()
        file_name = path.join(path.dirname(__file__),
                              'test_files',
                              'test.cpp')
        self.set_up_view(file_name)

        self.assertIsNotNone(self.view)

    def tearDown(self):
        self.tear_down()

    def test_invalid(self):
        """Test asking for an invalid view's viewcontroller."""
        vc_manager = vc.VCManager()
        controller = vc_manager.view_controller(None)

        self.assertIsNone(controller)

    def test_init(self):
        """Test asking for a view's viewcontroller and its expected members."""
        vc_manager = vc.VCManager()
        controller = vc_manager.view_controller(self.view)

        self.assertIsNotNone(controller)
        self.assertIsNotNone(controller.status)
        self.assertIsNotNone(controller.fixits)
        self.assertIsNotNone(controller.idle)
