# -*- coding: utf-8 -*-

"""Settings.

Settings manager.

"""

import sublime
import logging

from threading import RLock

log = logging.getLogger("RTags")


class SettingsManager():
    settings = None

    def update():
        log.debug("Settings update")
        SettingsManager.settings = sublime.load_settings('RTagsComplete.sublime-settings')

    def get(key, default=None):
        if not SettingsManager.settings:
            SettingsManager.update()
        value = SettingsManager.settings.get(key, default)
        log.debug("Setting {}={}".format(key, value))
        return value

    def add_on_change(key):
        log.debug("Settings watching {}".format(key))
        SettingsManager.settings.add_on_change(key, SettingsManager.update)
