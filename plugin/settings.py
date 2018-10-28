# -*- coding: utf-8 -*-

"""Settings.

Settings manager.

"""

import sublime
import logging

from . import tools

from os import path

log = logging.getLogger("RTags")


class SettingsManager():
    PACKAGE_PATH = "Packages"
    THEMES_PATH = "themes"
    THEME_NAME = "Default"

    settings = None
    templates = {}

    def template_as_html(category, typename, message):
        if typename not in SettingsManager.templates.keys():
            return None
        if category not in SettingsManager.templates[typename].keys():
            return None
        template = SettingsManager.templates[typename][category]
        padded = template.replace('{', '{{').replace('}', '}}')
        substituted = padded.replace('[', '{').replace(']', '}')
        return substituted.format(message)

    def update():
        log.debug("Settings update")
        SettingsManager.settings = sublime.load_settings(
            'RTagsComplete.sublime-settings')

        # Init templates.
        SettingsManager.templates = {}
        types = {
            "phantom": ["error", "warning"],
            "popup": ["error", "info"]
        }

        for key in types.keys():
            SettingsManager.templates[key] = {}
            for name in types[key]:
                filepath = path.join(
                    SettingsManager.PACKAGE_PATH,
                    tools.PKG_NAME,
                    SettingsManager.THEMES_PATH,
                    SettingsManager.THEME_NAME,
                    "{}_{}.html".format(name, key))

                log.debug("load_binary_resource of {}".format(filepath))
                SettingsManager.templates[key][name] = sublime.load_binary_resource(filepath).decode('utf-8')

    def get(key, default=None):
        if not SettingsManager.settings:
            SettingsManager.update()
        value = SettingsManager.settings.get(key, default)
        # log.debug("Setting {}={}".format(key, value))
        return value

    def add_on_change(key):
        log.debug("Settings watching {}".format(key))
        SettingsManager.settings.add_on_change(key, SettingsManager.update)
