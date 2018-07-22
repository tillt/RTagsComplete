# -*- coding: utf-8 -*-

"""Fixits handling.

Indexing result evaluation, the frontend for the monitor process.

"""

import sublime
import sublime_plugin

import logging

from os import path

from . import jobs
from . import settings
from . import indicator
from . import status
from . import watchdog

log = logging.getLogger("RTags")

class Category:
    WARNING = "warning"
    ERROR = "error"

class Controller():
    CATEGORIES = [ Category.WARNING, Category.ERROR ]

    CATEGORY_FLAGS = {
        Category.WARNING: sublime.DRAW_NO_FILL,
        Category.ERROR: sublime.DRAW_NO_FILL
    }

    PHANTOMS_TAG = "rtags_phantoms"

    def __init__(self, view, supported, status):
        self.supported = supported
        self.regions = {}
        self.issues = None
        self.waiting = False
        self.expecting = False
        self.navigation_items = None
        self.view = view
        self.filename = view.file_name()
        self.status = status
        self.watchdog = watchdog.IndexWatchdog()

    def activated(self):
        log.debug("Activated")

    def deactivated(self):
        log.debug("Deactivated")

    def on_select(self, res):
        (file, line, col) = self.navigation_items[res]
        view = self.view.window().open_file(
            '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION)

    def on_highlight(self, res):
        (file, line, col) = self.navigation_items[res]
        view = self.view.window().open_file(
            '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION | sublime.TRANSIENT)

    def show_selector(self):
        def issue_to_panel_item(issue):
            return [
                issue['message'],
                "{}:{}:{}".format(self.filename.split('/')[-1], issue['line'], issue['column'])]

        if not self.issues:
            log.debug("No warnings, errors or fixits to show")
            return

        items = list(map(issue_to_panel_item, self.issues['error']))
        items += list(map(issue_to_panel_item, self.issues['warning']))

        def issue_to_navigation_item(issue):
            return [self.filename, issue['line'], issue['column']]

        self.navigation_items = list(map(issue_to_navigation_item, self.issues['error']))
        self.navigation_items += list(map(issue_to_navigation_item, self.issues['warning']))

        # If there is only one result no need to show it to user
        # just do navigation directly.
        if len(items) == 1:
            self.on_select(0)
            return

        self.view.window().show_quick_panel(
            items,
            self.on_select,
            sublime.MONOSPACE_FONT,
            -1,
            self.on_highlight)

    def category_key(self, category):
        return "rtags-{}-mark".format(category)

    def clear_regions(self):
        log.debug("Clearing regions from view")
        for key in self.regions.keys():
            self.view.erase_regions(self.category_key(key));

    def show_regions(self):
        scope_names = {'error': 'region.redish', 'warning': 'region.yellowish'}
        for category, regions in self.regions.items():
            self.view.add_regions(
                self.category_key(category),
                [region['region'] for region in regions],
                scope_names[category],
                "",
                Controller.CATEGORY_FLAGS[category])

    def clear_phantoms(self):
        log.debug("Clearing phantoms from view")
        self.view.erase_phantoms(Controller.PHANTOMS_TAG)

    def update_phantoms(self, issues):
        self.phantom_set = sublime.PhantomSet(self.view, Controller.PHANTOMS_TAG)

        def issue_to_phantom(category, issue):
            point = self.view.text_point(issue['line']-1, 0)
            start = self.view.line(point).a
            return sublime.Phantom(
                sublime.Region(start, start+1),
                settings.SettingsManager.template_as_html(
                    category,
                    'phantom',
                    issue['message']),
                sublime.LAYOUT_BLOCK)

        phantoms = list(map(lambda p: issue_to_phantom('error', p), issues['error']))
        phantoms += list(map(lambda p: issue_to_phantom('warning', p), issues['warning']))

        self.phantom_set.update(phantoms)

    def update_regions(self, issues):

        def issue_to_region(issue):
            start = self.view.text_point(issue['line']-1, issue['column']-1)

            if issue['length'] > 0:
                end = self.view.text_point(issue['line']-1, issue['column']-1 + issue['length'])
            else:
                end = self.view.line(start).b

            return {
                "region": sublime.Region(start, end),
                "message": issue['message']}

        self.regions = {
            'warning': list(map(issue_to_region, issues['warning'])),
            'error': list(map(issue_to_region, issues['error']))
        }

    def clear(self):
        # Clear anything we might have mutated.
        self.status.clear_status()
        self.status.clear_results()
        self.clear_regions()
        self.clear_phantoms()
        self.regions = {}
        self.issues = None

    def unload(self):
        # Stop the watchdog and clear.
        self.watchdog.stop()
        self.clear()

    def update(self, filename, issues):
        log.debug("Got indexing results for {}".format(filename))

        if not self.supported:
            log.debug("Fixits are disabled")
            return

        if not self.view:
            log.warning("There is no view")
            return

        if filename != self.filename:
            log.warning("Got update for {} which is not {}".format(filename, self.filename))
            return

        self.status.update_results(issues)
        self.update_regions(issues)
        self.update_phantoms(issues)
        self.show_regions()
        self.issues = issues

    def indexing_done_callback(self, complete, error=None):
        log.debug("Indexing callback hit")

        self.status.progress.stop()

        self.status.update_status(error)

        if not complete:
            log.debug("Indexing not completed")
            return

        log.debug("Triggering diagnosis for the indexed file")

        # For some bizarre reason a reindexed file that does not have any
        # fixits or warnings will not return anything in `rc -m`, hence
        # we need to force such result again via `rc --diagnose`.
        jobs.JobController.run_async(
            jobs.RTagsJob(
                "RTDiagnoseJob" + jobs.JobController.next_id(),
                [
                    '--diagnose', self.filename
                ],
                **{'view': self.view}
            ),
            indicator=self.status.progress)

    def reindex(self, saved):
        log.debug("Reindex hit {} {} {}".format(self, self.view, saved))

        self.clear()

        if not self.supported:
            log.debug("Fixits are disabled")
            return

        self.status.progress.start()

        jobs.JobController.run_async(jobs.MonitorJob("RTMonitorJob"))

        text = b''

        if not saved:
            text = bytes(self.view.substr(sublime.Region(0, self.view.size())), "utf-8")

        jobs.JobController.run_async(
            jobs.ReindexJob(
                "RTReindexJob",
                self.filename,
                text,
                self.view
            )
        )

        # Start a watchdog that polls if we were still indexing.
        self.watchdog.start(self.indexing_done_callback)

        log.debug("Expecting indexing results for {}".format(self.filename))
