import sublime
import logging

from threading import RLock

log = logging.getLogger("RTags")


class SettingsManager():
    settings = None

    def update():
        SettingsManager.settings = sublime.load_settings('RtagsComplete.sublime-settings')

    def get(key, default=None):
        if not SettingsManager.settings:
            SettingsManager.update()
        return SettingsManager.settings.get(key, default)

    def add_on_change(key):
        SettingsManager.settings.add_on_change(key, SettingsManager.update)
