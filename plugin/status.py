# -*- coding: utf-8 -*-

"""Status Controller.

"""

import sublime
import logging

from random import sample

from . import settings

log = logging.getLogger("RTags")


class StatusController():

    def __init__(self, progress):
        self.view = None
        self.progress = progress
        self.status_key = settings.SettingsManager.get('status_key')
        self.results_key = settings.SettingsManager.get('results_key')

    def clear_status(self, view=None):
        if not view:
            if not self.view:
                return
            view = self.view
            self.view = None
        log.debug("Clearing status from view {}".format(view))
        view.erase_status(self.status_key)

    def signal_status(self, view, error=None):
        log.debug("Signalling status with error={}".format(error))

        self.clear_status(view)

        if error:
            view.set_status(self.status_key, "RTags ❌")
            self.view = view

    def clear_results(self, view=None):
        if not view:
            if not self.view:
                return
            view = self.view
            self.view = None
        log.debug("Clearing results from view {}".format(view))
        view.erase_status(self.results_key)

    def update_results(self, view, issues):
        results = []

        error_count = len(issues['error'])
        warning_count = len(issues['warning'])

        if error_count > 0:
            results.append("⛔: {}".format(error_count))
        if warning_count > 0:
            results.append("✋: {}".format(warning_count))
        if len(results) == 0:
            results.append("✅")

        view.set_status(self.results_key, "Diagnose {}".format(" ".join(results)))
        self.view = view
