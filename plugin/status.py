# -*- coding: utf-8 -*-

"""Status Controller.

"""

import sublime
import logging

from . import settings
from . import indicator

log = logging.getLogger("RTags")

class Status():

    def __init__(self, view):
        self.view = view
        self.progress = indicator.ProgressIndicator()
        self.status_key = settings.SettingsManager.get('status_key')
        self.results_key = settings.SettingsManager.get('results_key')

    def clear_status(self):
        log.debug("Clearing status from view {}".format(self.view))

        self.view.erase_status(self.status_key)

    def signal_status(self, error=None):
        log.debug("Signalling status with error={}".format(error))

        self.clear_status()

        if error:
            self.view.set_status(self.status_key, "RTags ❌")

    def clear_results(self):
        log.debug("Clearing results from view {}".format(self.view))

        self.view.erase_status(self.results_key)

    def update_results(self, issues):
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


class StatusController():

    def __init__(self):
        self.status = {}

    def progress_controller(self, view):
        if not view.file_name() in self.status.keys():
            self.status[view.file_name()] = Status(view)
        return self.status[view.file_name()].progress

    def clear_status(self, view=None):
        if not view:
            return

        if not view.file_name() in self.status.keys():
            self.status[view.file_name()] = Status(view)

        self.status[view.file_name()].clear_status()

    def signal_status(self, view, error=None):
        if not view.file_name() in self.status.keys():
            self.status[view.file_name()] = Status(view)

        self.status[view.file_name()].signal_status(error)

    def clear_results(self, view=None):
        if not view:
            return

        if not view.file_name() in self.status.keys():
            self.status[view.file_name()] = Status(view)

        self.status[view.file_name()].clear_results()

    def update_results(self, view, issues):
        if not view.file_name() in self.status.keys():
            self.status[view.file_name()] = Status(view)

        self.status[view.file_name()].update_results(issues)
