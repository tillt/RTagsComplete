import sublime
import sublime_plugin
import subprocess

import logging


log = logging.getLogger("RTags")

class Mode:
    RESET = 0
    SLEEP = 1
    RUN = 2


class Controller:
    PERIOD = 5000.0

    def __init__(self, auto_reindex, threshold, callback):
        self.counter = 0
        self.auto_reindex = auto_reindex
        self.counter_threshold = threshold / Controller.PERIOD
        self.view = None
        self.callback = callback

    def trigger(self, view):
        if not self.auto_reindex:
            return

        # We should always have a valid view object.
        if not view:
            return

        self.view = view

        sublime.set_timeout_async(lambda self=self: self.run(Mode.RESET), 0)

    def sleep(self):
        sublime.set_timeout_async(lambda self=self: self.run(Mode.SLEEP), 0)

    def run(self, mode=Mode.RUN):
        if mode == Mode.SLEEP:
            return

        if mode == Mode.RESET:
            self.counter = 0

        if self.counter >= self.counter_threshold:
            log.debug("Threshold reached.")
            self.callback(view=self.view)
            return

        self.counter += 1

        sublime.set_timeout_async(lambda: self.run(Mode.RUN), Controller.PERIOD)
