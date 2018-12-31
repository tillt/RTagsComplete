"""Tests for VC Manager."""

import collections

from os import path

from RTagsComplete.plugin import vc_manager
from RTagsComplete.plugin import settings

from RTagsComplete.tests.gui_wrapper import GuiTestWrapper


class TestVC(GuiTestWrapper):
    """Test VC Manager."""

    def setUp(self):
        super().setUp()
        file_name = path.join(path.dirname(__file__),
                              'test_files',
                              'test_fixits.cpp')
        self.set_up_view(file_name)

        self.assertIsNotNone(self.view)

    def test_invalid(self):
        """Test asking for an invalid view's viewcontroller."""
        controller = vc_manager.view_controller(None)

        self.assertIsNone(controller)

    def test_init(self):
        """Test asking for a view's viewcontroller and its expected members."""
        controller = vc_manager.view_controller(self.view)

        self.assertIsNotNone(controller)
        self.assertIsNotNone(controller.status)
        self.assertIsNotNone(controller.fixits)
        self.assertIsNotNone(controller.idle)

    def test_small_history(self):
        """Test checking if a small history remains in order and complete ."""
        self.assertEqual(len(vc_manager.history), 0)

        vc_manager.push_history("matilda", 1969, 12)

        self.assertEqual(len(vc_manager.history), 1)

        vc_manager.push_history("till", 2012, 10)

        self.assertEqual(len(vc_manager.history), 2)

        [file, line, col] = vc_manager.pop_history()
        self.assertEqual(file, "till")
        self.assertEqual(line, 2012)
        self.assertEqual(col, 10)

        self.assertEqual(len(vc_manager.history), 1)

        [file, line, col] = vc_manager.pop_history()
        self.assertEqual(file, "matilda")
        self.assertEqual(line, 1969)
        self.assertEqual(col, 12)

        self.assertEqual(len(vc_manager.history), 0)

    def test_large_history(self):
        """Test checking if a large history remains in order and shortened."""
        size = int(settings.get('jump_limit', 10))

        for i in range(0, size):
            vc_manager.push_history("item{}".format(i + 1), 1, 1)

        self.assertEqual(len(vc_manager.history), size)

        # This will push out item1
        vc_manager.push_history("overflow", 1, 1)

        self.assertEqual(len(vc_manager.history), size)

        [file, line, col] = vc_manager.pop_history()
        self.assertEqual(file, "overflow")

        for i in range(size, 1, -1):
            [file, line, col] = vc_manager.pop_history()
            self.assertEqual(file, "item{}".format(i))

        self.assertEqual(len(vc_manager.history), 0)
