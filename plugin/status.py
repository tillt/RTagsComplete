# -*- coding: utf-8 -*-

"""Status Controller.

"""

import sublime
import logging

from . import settings
from . import indicator

log = logging.getLogger("RTags")

class StatusController():

    def __init__(self, view):
        self.view = view
        self.progress = indicator.ProgressIndicator(view)
        self.status_key = settings.SettingsManager.get('status_key')
        self.results_key = settings.SettingsManager.get('results_key')

    def unload(self):
        self.progress.unload()
        self.clear()

    def clear(self):
        self.clear_status()
        self.clear_results()

    def clear_status(self):
        log.debug("Clearing status from view-id {}".format(self.view.id()))

        self.view.erase_status(self.status_key)

    def update_status(self, error=None):
        log.debug("Signalling status with error={}".format(error))

        self.clear_status()

        if error:
            self.view.set_status(self.status_key, "RTags ❌")

    def clear_results(self):
        log.debug("Clearing results from view-id {}".format(self.view.id()))

        self.view.erase_status(self.results_key)

    def update_results(self, issues):
        log.debug("Update results with issues={}".format(issues))

        results = []

        error_count = len(issues['error'])
        warning_count = len(issues['warning'])

        if error_count > 0:
            results.append("⛔: {}".format(error_count))
        if warning_count > 0:
            results.append("✋: {}".format(warning_count))
        if len(results) == 0:
            results.append("✅")

        self.view.set_status(self.results_key, "Diagnose {}".format(" ".join(results)))
