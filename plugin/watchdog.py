# -*- coding: utf-8 -*-

"""Index Watchdog.
Polls `rdm` to detect an indexing in progress.
"""

import sublime

import logging

from . import jobs

log = logging.getLogger("RTags")


class IndexWatchdog():

    def __init__(self):
        self.active = False
        self.period = 500
        self.threshold = 10
        self.indexing = False
        self.callback = None

    def stop(self):
        if not self.active:
            return

        # Schadule into timer-thread.
        sublime.set_timeout_async(lambda self=self: self.run(True), 0)

    def start(self, callback):
        if self.active:
            log.debug("Watchdog already active")
            return

        log.debug("Watchdog starting")
        self.active = True
        self.threshold = 10
        self.callback = callback
        self.indexing = False

        # Schadule into timer-thread.
        sublime.set_timeout_async(lambda self=self: self.run(False), 0)

    def run(self, stopping):
        if not self.active:
            log.debug("Watchdog not even active - interesting case")
            return

        if stopping:
            log.debug("Stopping indexing watchdog now")
            self.active = False
            if self.callback:
                self.callback(False)
            return

        (_, out, error) = jobs.JobController.run_sync(jobs.RTagsJob(
            "ReindexWatchdogJob",
            ["--is-indexing", "--silent-query"],
            **{'nodebug': True}))

        if error:
            log.error("Watchdog failed to poll: {}".format(error.message))
            log.debug("Retrying...")
            self.threshold -= 1
        else:
            if out.decode().strip() == "1":
                # We are now indexing!
                self.indexing = True
            else:
                # In case we did detect activity before, we now assume
                # a done state.
                if self.indexing is True:
                    self.active = False
                    if self.callback:
                        self.callback(True)
                    return

                log.debug("Retrying...")
                self.threshold -= 1

        if self.threshold == 0:
            log.debug("We never even recognized an indexing in progress")
            self.active = False
            if self.callback:
                self.callback(True, error)
            return

        # Repeat as long as we are still indexing OR we are still trying
        # to recognize the first indication of an ongoing indexing before
        # the theshold expires.
        sublime.set_timeout_async(
            lambda self=self: self.run(False),
            self.period)
