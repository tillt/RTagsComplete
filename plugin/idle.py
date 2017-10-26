import sublime
import sublime_plugin
import subprocess

import logging


log = logging.getLogger("RTags")

class Controller:
    PERIOD = 5000.0

    def __init__(self, auto_reindex, threshold, callback):
        self.counter = 0
        self.auto_reindex = auto_reindex
        self.counter_threshold = threshold / Controller.PERIOD
        self.active = False
        self.view = None
        self.callback = callback

    def trigger(self, view):
        if not self.auto_reindex:
            return

        # We should always have a valid view object.
        if not view:
            return

        self.counter = 0
        self.view = view

        if not self.active:
            self.active = True
            self.run()

    def sleep(self):
        self.active = False

    def run(self):
        if not self.active:
            return

        self.counter += 1

        if self.counter >= self.counter_threshold:
            log.debug("Threshold reached.")
            self.active = False
            self.callback(view=self.view)
            return

        sublime.set_timeout(lambda: self.run(), Controller.PERIOD)
