# -*- coding: utf-8 -*-

"""Fixits handling.

Indexing result evaluation, the frontend for the monitor process.

"""

import sublime

import logging

from functools import partial

from . import jobs
from . import settings
from . import watchdog

log = logging.getLogger("RTags")


class Category:
    WARNING = "warning"
    ERROR = "error"


class Controller():
    CATEGORIES = [Category.WARNING, Category.ERROR]

    CATEGORY_FLAGS = {
        Category.WARNING: sublime.DRAW_NO_FILL,
        Category.ERROR: sublime.DRAW_NO_FILL
    }

    PHANTOMS_TAG = "rtags_phantoms"

    def __init__(self, view, supported, status):
        self.supported = supported
        self.regions = {}
        self.issues = None
        self.navigation_items = None
        self.view = view
        self.filename = view.file_name()
        self.status = status
        self.watchdog = watchdog.IndexWatchdog()
        self.reindex_job_id = None

    def activated(self):
        log.debug("Activated")

    def deactivated(self):
        log.debug("Deactivated")

    def select(self, res):
        (file, line, col) = self.navigation_items[res]
        self.view.window().open_file(
            '%s:%s:%s' % (file, line, col),
            sublime.ENCODED_POSITION)

    def highlight(self, res):
        (file, line, col) = self.navigation_items[res]
        self.view.window().open_file(
            '%s:%s:%s' % (file, line, col),
            sublime.ENCODED_POSITION | sublime.TRANSIENT)

    def show_selector(self, on_highlight, on_select):
        if not self.issues:
            log.debug("No warnings, errors or fixits to show")
            return

        def issue_to_tuple(issue, kind):
            return [
                kind,
                issue['message'],
                self.filename,
                issue['line'],
                issue['column']]

        tuples = list(map(
            partial(issue_to_tuple, kind='ERROR'),
            self.issues['error']))

        tuples += list(map(
            partial(issue_to_tuple,  kind='WARNING'),
            self.issues['warning']))

        # Sort the tuples by file and then line number and column.
        def file_line_col(item):
            return (item[2], item[3], item[4])

        tuples.sort(key=file_line_col)

        def tuple_to_navigation_item(item):
            return [item[2], item[3], item[4]]

        self.navigation_items = list(map(tuple_to_navigation_item, tuples))

        def tuple_to_panel_item(item):
            return [
                "{}: {}".format(item[0], item[1]),
                "{}:{}:{}".format(
                    item[2].split('/')[-1],
                    item[3],
                    item[4])]

        items = list(map(tuple_to_panel_item, tuples))

        log.debug("Items for panel: {}".format(items))

        # If there is only one result no need to show it to user
        # just do navigation directly.
        if len(items) == 1:
            on_select(0)
            return

        self.view.window().show_quick_panel(
            items,
            on_select,
            sublime.MONOSPACE_FONT,
            -1,
            on_highlight)

    def category_key(self, category):
        return "rtags-{}-mark".format(category)

    def clear_regions(self):
        log.debug("Clearing regions from view")
        for key in self.regions.keys():
            self.view.erase_regions(self.category_key(key))

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
        self.phantom_set = sublime.PhantomSet(
            self.view,
            Controller.PHANTOMS_TAG)

        def issue_to_phantom(category, issue):
            point = self.view.text_point(issue['line']-1, 0)
            start = self.view.line(point).a
            return sublime.Phantom(
                sublime.Region(start, start+1),
                settings.template_as_html(
                    category,
                    'phantom',
                    issue['message']),
                sublime.LAYOUT_BLOCK)

        phantoms = list(map(
            lambda p: issue_to_phantom('error', p),
            issues['error']))
        phantoms += list(map(
            lambda p: issue_to_phantom('warning', p),
            issues['warning']))

        self.phantom_set.update(phantoms)

    def update_regions(self, issues):

        def issue_to_region(issue):
            start = self.view.text_point(issue['line']-1, issue['column']-1)

            if issue['length'] > 0:
                end = self.view.text_point(
                    issue['line']-1,
                    issue['column']-1 + issue['length'])
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
            log.warning("Got update for {} which is not {}".format(
                filename,
                self.filename))
            return

        self.status.update_results(issues)
        self.update_regions(issues)
        self.update_phantoms(issues)
        self.show_regions()
        self.issues = issues

    def indexing_done_callback(self, complete, error=None):
        log.debug("Indexing callback hit")

        self.status.progress.stop()

        self.reindex_job_id = None

        self.status.update_status(error)

        if not complete or error:
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

        if not self.supported:
            log.debug("Fixits are disabled")
            return

        if self.reindex_job_id:
            log.debug("Reindex already requested")
            return

        self.clear()

        self.status.progress.start()

        jobs.JobController.run_async(jobs.MonitorJob("RTMonitorJob"))

        text = b''

        if not saved:
            text = bytes(
                self.view.substr(sublime.Region(0, self.view.size())),
                "utf-8")

        self.reindex_job_id = "RTReindexJob"

        jobs.JobController.run_async(
            jobs.ReindexJob(
                self.reindex_job_id,
                self.filename,
                text,
                self.view
            )
        )

        # Start a watchdog that polls if we were still indexing.
        self.watchdog.start(self.indexing_done_callback)

        log.debug("Expecting indexing results for {}".format(self.filename))
