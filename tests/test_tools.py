"""Tests for Job Controller."""
import os
import tempfile

from unittest import TestCase

from RTagsComplete.plugin import tools


class TestTools(TestCase):
    """Test Utilities."""

    def test_replace_in_file(self):
        """Test file string replace function."""

        name = ""

        with tempfile.NamedTemporaryFile(delete=False) as out_file:
            name = out_file.name

            contents = b'echo foo && sleep 1\n'

            out_file.write(contents)
            out_file.close()

        tools.Utilities.replace_in_file(
            "foo", "bar", name, {0: [6]})

        with open(name) as in_file:
            contents = in_file.read()

            self.assertEqual(contents, "echo bar && sleep 1\n")

        os.unlink(name)
