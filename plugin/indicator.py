# -*- coding: utf-8 -*-

"""Activity Indicator.

"""

import sublime
import logging

from random import sample

from . import settings

log = logging.getLogger("RTags")


class ProgressIndicator():
    # Borrowed from EasyClangComplete.
    MSG_CHARS_COLOR_SUBLIME = u'⣾⣽⣻⢿⡿⣟⣯⣷'

    PERIOD = 100

    def __init__(self):
        self.size = 8
        self.view = None
        self.active = False
        self.status_key = settings.SettingsManager.get('status_key', 'rtags_status_indicator')

    def start(self, view):
        if self.active:
            log.debug("Indicator already active")
            return

        log.debug("Starting indicator {} {}".format(active_callback, done_callback))
        self.view = view
        self.active = True
        sublime.set_timeout(lambda self=self: self.run(1), 0)

    def stop(self):
        if not self.active:
            log.debug("Indicator was not active")
            return

        log.debug("Stopping indicator")
        sublime.set_timeout(lambda self=self: self.run(1, True), 0)

    def run(self, i, stopping=False):
        if not self.active:
            return

        if stopping:
            log.debug("Stopped indicator")
            self.active = False
            if self.view:
                self.view.erase_status(self.status_key)
            return

        mod = len(ProgressIndicator.MSG_CHARS_COLOR_SUBLIME)
        rands = [ProgressIndicator.MSG_CHARS_COLOR_SUBLIME[x] for x in sample(range(mod), mod)]

        self.view.set_status(self.status_key, 'RTags {}'.format(''.join(rands)))

        sublime.set_timeout(lambda self=self: self.run(i), ProgressIndicator.PERIOD)
