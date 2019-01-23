# -*- coding: utf-8 -*-

"""Fixits handling.

Indexing result evaluation, the frontend for the monitor process.

"""

import sublime

import logging
import re

from functools import partial

from . import jobs
from . import settings
from . import tools
from . import watchdog

log = logging.getLogger("RTags")


class Category:
    WARNING = "warning"
    ERROR = "error"
    FIXIT = "fixit"
    NOTE = "note"


class Controller():
    CATEGORIES = [Category.WARNING, Category.ERROR, Category.FIXIT]

    CATEGORY_FLAGS = {
        Category.WARNING: sublime.DRAW_SQUIGGLY_UNDERLINE | sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE,
        Category.ERROR: sublime.DRAW_SQUIGGLY_UNDERLINE | sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE,
        Category.FIXIT: sublime.DRAW_SOLID_UNDERLINE | sublime.DRAW_NO_FILL
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

    def region(view, line, column, length):
        start = view.text_point(
            line - 1,
            column - 1)

        if length:
            end = view.text_point(
                line - 1,
                column - 1 + length)
        else:
            end = view.line(start).b

        return sublime.Region(start, end)

    def substring(view, line, column, length):
        return view.substr(Controller.region(view, line, column, length))

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

        def issue_to_tuple(issue):
            return [
                issue['type'],
                issue['message'],
                self.filename,
                issue['line'],
                issue['column']]

        tuples = list(map(issue_to_tuple, self.issues['error']))
        tuples += list(map(issue_to_tuple, self.issues['warning']))
        tuples += list(map(issue_to_tuple, self.issues['fixit']))

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
        scope_names = {
            'error': 'region.redish',
            'warning': 'region.yellowish',
            'fixit': 'region.bluish',
            'note': None,
        }
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

        def phantom_navigate(link):
            (file, line_, column_, length_, message) = re.findall(
                r'(.*):(\d+):(\d+):(\d+):(.*)',
                link)[0]

            line = int(line_)
            column = int(column_)
            length = int(length_)

            old = Controller.substring(self.view, line, column, length)

            mutations = {}
            mutations[line] = [column]

            tools.Utilities.replace_in_file(
                old,
                message,
                file,
                mutations)

            self.view.window().open_file(file)

            self.reindex(True)

        def issue_to_phantom(start, issue):
            html = ""

            if 'link' in issue:
                html = settings.template_as_html(
                    issue['type'],
                    'phantom',
                    issue['link'],
                    tools.Utilities.html_escape(issue['message']))
            else:
                html = settings.template_as_html(
                    issue['type'],
                    'phantom',
                    tools.Utilities.html_escape(issue['message']))

            return sublime.Phantom(
                sublime.Region(start, start+1),
                html,
                sublime.LAYOUT_BLOCK,
                phantom_navigate)

        phantoms = []

        order = ['warning', 'error', 'fixit']

        for key in order:
            if key in issues:
                for issue in issues[key]:
                    point = self.view.text_point(issue['line']-1, 0)
                    start = self.view.line(point).a
                    phantom = issue_to_phantom(start, issue)
                    phantoms.append(phantom)
                    if 'subissues' in issue:
                        for subissue in issue['subissues']:
                            phantoms.append(issue_to_phantom(start, subissue))

        self.phantom_set.update(phantoms)

    def update_regions(self, issues):

        def issue_to_region(issue):
            start = self.view.text_point(issue['line']-1, issue['column']-1)

            if 'length' in issue and issue['length'] > 0:
                end = self.view.text_point(
                    issue['line']-1,
                    issue['column']-1 + issue['length'])
            else:
                end = self.view.line(start).b

            return {
                "region": sublime.Region(start, end),
                "message": issue['message']}

        self.regions = {}

        if 'warning' in issues:
            self.regions['warning'] = list(map(
                issue_to_region,
                issues['warning']))
        if 'error' in issues:
            self.regions['error'] = list(map(
                issue_to_region,
                issues['error']))
        if 'fixit' in issues:
            self.regions['fixit'] = list(map(
                issue_to_region,
                issues['fixit']))

    def clear(self):
        # Clear anything we might have mutated.
        self.status.clear_status()
        self.status.clear_results()
        self.clear_regions()
        self.clear_phantoms()
        self.regions = {}
        self.issues = {}

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

        log.debug("Got indexing {}".format(issues))

        for key in issues:
            if key not in self.issues:
                self.issues[key] = []
            self.issues[key] = issues[key]

        warning_count = 0
        if 'warning' in self.issues:
            warning_count = len(self.issues['warning'])

        error_count = 0
        if 'error' in self.issues:
            error_count = len(self.issues['error'])

        self.status.update_results(error_count, warning_count)

        self.update_regions(self.issues)
        self.update_phantoms(self.issues)
        self.show_regions()

    def fixits_callback(self, future):
        log.debug("Fixits callback hit")

        if not future.done():
            log.warning("Fixits failed")
            return

        if future.cancelled():
            log.warning(("Fixits aborted"))
            return

        (job_id,  out, error) = future.result()

        log.debug("Fixits received: {}".format(out))

        def out_to_fixit(line):
            (line_, column_, length_, message_) = re.findall(
                r'(\d+):(\d+) (\d+) (.*)',
                line)[0]

            line = int(line_)
            column = int(column_)
            length = int(length_)
            message = message_.strip()

            content = None

            fixit = {}

            if line > 0 and column > 0:
                if length > 0 and len(message):
                    context = Controller.substring(self.view, line, column, length)
                    content = "Replace '{}' with '{}'!".format(context, message)
                elif length > 0:
                    context = Controller.substring(self.view, line, column, length)
                    content = "Remove '{}'!".format(context)
                elif len(message) > 0:
                    content = "Add '{}'!".format(message)

            fixit['file'] = self.filename
            fixit['line'] = line
            fixit['length'] = length
            fixit['column'] = column
            fixit['message'] = content
            fixit['type'] = 'fixit'
            fixit['link'] = "{}:{}:{}:{}:{}".format(
                self.filename,
                line,
                column,
                length,
                message)

            return fixit

        issues = {}
        issues['fixit'] = list(map(out_to_fixit, out.decode('utf-8').splitlines()))

        log.debug("Got fixits to send")

        sublime.active_window().active_view().run_command(
            'rtags_fixit',
            {
                'filename': self.filename,
                'issues': issues
            })

    def indexing_callback(self, complete, error=None):
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

        jobs.JobController.run_async(
            jobs.RTagsJob(
                "RTFixitsJob" + jobs.JobController.next_id(),
                [
                    '--fixits', self.filename
                ],
                **{'view': self.view}
            ),
            self.fixits_callback,
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
        self.watchdog.start(self.indexing_callback)

        log.debug("Expecting indexing results for {}".format(self.filename))
