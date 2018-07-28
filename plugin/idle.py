# -*- coding: utf-8 -*-

"""Idle Controller.

Manages idle timeout tasks. Uses coarse grained period for this low
priority work.

"""


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
    def __init__(self, view, auto_reindex, period, threshold, callback):
        self.counter = 0
        self.period = period
        self.auto_reindex = auto_reindex
        self.counter_threshold = (threshold * 1000.0) / self.period
        self.view = view
        self.callback = callback

    def deactivated(self):
        log.debug("Deactivated")
        self.sleep()

    def activated(self):
        log.debug("Activated")

    def trigger(self):
        if not self.auto_reindex:
            return

        sublime.set_timeout_async(lambda self=self: self.run(Mode.RESET), 0)

    def sleep(self):
        if not self.auto_reindex:
            return

        sublime.set_timeout_async(lambda self=self: self.run(Mode.SLEEP), 0)

    def run(self, mode=Mode.RUN):
        if mode == Mode.SLEEP:
            log.debug("Sleep idle control for view-id {}".format(self.view.id()))
            self.active = False
            return

        if mode == Mode.RESET:
            self.counter = 0
            log.debug("Reset idle control for view-id {}".format(self.view.id()))
            if self.active:
                return
            self.active = True

        if not self.active:
            log.debug("Not active for view-id {}".format(self.view.id()))
            return

        if self.counter >= self.counter_threshold:
            log.debug("Idle control threshold reached for view-id {}".format(self.view.id()))
            self.active = False
            self.callback()
            return

        if mode == Mode.RUN:
            self.counter += 1

        sublime.set_timeout_async(lambda self=self: self.run(Mode.RUN), Controller.PERIOD)

    def unload(self):
        self.sleep()
