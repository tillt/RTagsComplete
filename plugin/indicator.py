# -*- coding: utf-8 -*-

"""Progress Indicator.

"""

import sublime
import logging

from random import sample
from threading import RLock

from . import settings

log = logging.getLogger("RTags")


class ProgressIndicator():
    #MSG_CHARS = u'◒◐◓◑'
    MSG_CHARS = u'◤◥◢◣'
    #MSG_CHARS = u'╀┾╁┽'
    PERIOD = 150

    MSG_LEN = 1

    lock = RLock()

    def __init__(self):
        self.view = None
        self.step = 0
        self.len = 1
        self.active_counter = 0
        self.stop_counter = 0
        self.status_key = settings.SettingsManager.get('progress_key')

    def clear(self, view=None):
        if not self.view:
            return

        if not view:
            view = self.view

        view.erase_status(self.status_key)

    def start(self, view):
        with ProgressIndicator.lock:
            needs_start = not self.active_counter
            self.active_counter += 1
            log.debug("Indicator now running for {} processes".format(self.active_counter))

        if needs_start:
            log.debug("Starting indicator")
            self.len = ProgressIndicator.MSG_LEN
            self.view = view
            sublime.set_timeout_async(lambda self=self: self.run(), 0)

    def stop(self, total=False):
        log.debug("Stopping one indication")
        with ProgressIndicator.lock:
            if self.active_counter == 0:
                log.debug("Indicator not active")
                return

            if total:
                self.stop_counter = self.active_counter
            else:
                self.stop_counter += 1

            log.debug("Indicator still running for {} processes".format(self.active_counter))

    def run(self):
        with ProgressIndicator.lock:
            if self.stop_counter > 0:
                self.stop_counter -= 1
                self.active_counter -= 1

            if self.active_counter == 0:
                self.clear()
                log.debug("Indicator stopped")
                return

        mod = len(ProgressIndicator.MSG_CHARS)

        chars = []
        for x in range(0, self.len):
            chars += ProgressIndicator.MSG_CHARS[(x + self.step) % mod]

        self.step = (self.step + 1) % mod

        self.view.set_status(self.status_key, '{}'.format(''.join(chars)))
        sublime.set_timeout_async(lambda self=self: self.run(), ProgressIndicator.PERIOD)
