# -*- coding: utf-8 -*-

"""Progress Indicator.

"""

import sublime
import logging

from random import sample

from . import settings

log = logging.getLogger("RTags")


class ProgressIndicator():
    MSG_LEN = 1

    #MSG_CHARS = u'◒◐◓◑'
    MSG_CHARS = u'◤◥◢◣'
    #MSG_CHARS = u'╀┾╁┽'
    PERIOD = 200

    def __init__(self):
        self.view = None
        self.step = 0
        self.len = 1
        self.active_counter = 0
        self.status_key = settings.SettingsManager.get('status_key', 'rtags_status_indicator')

    def start(self, view):
        self.active_counter += 1
        log.debug("Indicator now running for {} processes".format(self.active_counter))

        if self.active_counter > 1:
            log.debug("Indicator already active")
            return

        log.debug("Starting indicator")
        self.len = ProgressIndicator.MSG_LEN
        self.view = view
        sublime.set_timeout(lambda self=self: self.run(), 0)

    def stop(self, abort=False):
        if self.active_counter == 0:
            log.debug("Indicator not active")
            return

        self.active_counter -= 1
        log.debug("Stopping one indication")
        log.debug("Indicator now running for {} processes".format(self.active_counter))

    def run(self):
        if self.active_counter == 0:
            if self.view:
                self.view.erase_status(self.status_key)
            return

        mod = len(ProgressIndicator.MSG_CHARS)

        chars = []
        for x in range(0, self.len):
            chars += ProgressIndicator.MSG_CHARS[(x + self.step) % mod]

        self.step = (self.step + 1) % mod

        self.view.set_status(self.status_key, 'RTags {}'.format(''.join(chars)))

        sublime.set_timeout(lambda self=self: self.run(), ProgressIndicator.PERIOD)
