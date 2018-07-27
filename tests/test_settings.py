"""Tests for settings."""
import imp

from os import path
from unittest import TestCase

from RTagsComplete.plugin import settings

class TestSettings(TestCase):
    """Test settings."""

    def test_init(self):
        """Test that settings are correctly initialized."""
        self.assertIsNone(settings.SettingsManager.get('unknown_config_key'))

        self.assertIsNotNone(settings.SettingsManager.get('verbose_log'))
        self.assertIsNotNone(settings.SettingsManager.get('fixits'))

        self.assertEqual(settings.SettingsManager.get('unknown_config_key_with_default', 'default'), 'default')

    def test_templates(self):
        """Test that templates load as expected."""
        self.assertIsNone(settings.SettingsManager.template_as_html("unknown", "file", "test"))

        self.assertIsNotNone(settings.SettingsManager.template_as_html("error", "phantom", "test"))
        self.assertIsNotNone(settings.SettingsManager.template_as_html("warning", "phantom", "test"))
        self.assertIsNotNone(settings.SettingsManager.template_as_html("error", "popup", "test"))
        self.assertIsNotNone(settings.SettingsManager.template_as_html("info", "popup", "test"))
