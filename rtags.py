# -*- coding: utf-8 -*-

"""RTagsComplete plugin for Sublime Text 3.

Provides completion suggestions and much more for C/C++ languages
based on RTags.

Original code by Sergei Turukin.
Hacked with plenty of new features by Till Toenshoff.
Some code lifted from EasyClangComplete by Igor Bogoslavskyi.
"""
import sublime
import sublime_plugin

import logging
import re

from functools import partial

from .plugin import completion
from .plugin import info
from .plugin import jobs
from .plugin import settings
from .plugin import tools
from .plugin import vc_manager


log = logging.getLogger("RTags")
log.setLevel(logging.DEBUG)
log.propagate = False

formatter_default = logging.Formatter(
    '%(name)s:%(levelname)s: %(message)s')
formatter_verbose = logging.Formatter(
    '%(name)s:%(levelname)s: %(asctime)-15s %(filename)s::%(funcName)s'
    ' [%(threadName)s]: %(message)s')

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(formatter_default)
if not log.hasHandlers():
    log.addHandler(ch)


def get_view_text(view):
    return bytes(view.substr(sublime.Region(0, view.size())), "utf-8")


def get_word_under_cursor(view):
    word = None

    for region in view.sel():
        if region.begin() == region.end():
            wordRegion = view.word(region)
        else:
            wordRegion = region

        if not wordRegion.empty():
            word = view.substr(wordRegion)

    return word


def supported_view(view):
    if not view:
        log.error("There is no view")
        return False

    if view.is_scratch():
        log.error("View is scratch view")
        return False

    if view.buffer_id() == 0:
        log.error("View buffer id is 0")
        return False

    selection = view.sel()

    if not selection:
        log.error("Could not get a selection from this view")
        return False

    if not len(selection):
        log.error("Selection for this view is empty")
        return False

    scope = view.scope_name(selection[0].a)

    if not scope:
        log.error("Could not get a scope from this view position")
        return False

    scope_types = scope.split()

    if not len(scope_types):
        log.error("Scope types for this view is empty")
        return False

    file_types = settings.get(
        'file_types',
        ["source.c", "source.c++"])

    if not len(file_types):
        log.error("No supported file types set - go update your settings")
        return False

    if scope_types[0] not in file_types:
        log.debug("File type {} is not supported".format(scope_types[0]))
        return False

    return True


class RtagsBaseCommand(sublime_plugin.TextCommand):
    FILE_INFO_REG = r'(\S+):(\d+):(\d+):(.*)'
    MAX_POPUP_WIDTH = 1800
    MAX_POPUP_HEIGHT = 900

    def command_done(self, future, **kwargs):
        log.debug("Command done callback hit {}".format(future))

        if not future.done():
            log.warning("Command future failed")
            return

        if future.cancelled():
            log.warning(("Command future aborted"))
            return

        (job_id, out, error) = future.result()

        location = -1
        if 'col' in kwargs:
            location = self.view.text_point(kwargs['row'], kwargs['col'])

        vc_manager.view_controller(self.view).status.update_status(error=error)

        if error:
            log.error("Command task failed: {}".format(error.message))

            rendered = settings.template_as_html(
                "error",
                "popup",
                error.html_message())

            self.view.show_popup(
                rendered,
                sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                max_width=self.MAX_POPUP_WIDTH,
                max_height=self.MAX_POPUP_HEIGHT,
                location=location)
            return

        log.debug("Finished Command job {}".format(job_id))

        vc_manager.navigation_done()

        self._action(out, **kwargs)

    def run(self, edit, switches, *args, **kwargs):
        # Do nothing if not called from supported code.
        if not supported_view(self.view):
            return
        # File should be reindexed only when
        # 1. file buffer is dirty (modified)
        # 2. there is no pending reindexation (navigation_helper flag)
        # 3. current text is different from previous one
        # It takes ~40-50 ms to reindex 2.5K C file and
        # miserable amount of time to check text difference.
        if (vc_manager.is_navigation_done() and
            self.view.is_dirty() and
                vc_manager.navigation_data() != get_view_text(self.view)):

            vc_manager.request_navigation(
                self.view, switches,
                get_view_text(self.view))
            vc_manager.view_controller(self.view).fixits.reindex(saved=False)
            # Never go further.
            return

        # Run an `RTagsJob` named 'RTBaseCommandXXXX' for this is a
        # command job.
        job_args = kwargs
        job_args.update({'view': self.view})

        jobs.JobController.run_async(
            jobs.RTagsJob(
                "RTBaseCommand" + jobs.JobController.next_id(),
                switches + [self._query(*args, **kwargs)],
                **job_args),
            partial(self.command_done, **kwargs),
            vc_manager.view_controller(self.view).status.progress)

    def on_select(self, res):
        if res == -1:
            vc_manager.return_in_history(self.view)
            return

        (file, line, col, _) = re.findall(
            RtagsBaseCommand.FILE_INFO_REG,
            vc_manager.references()[res])[0]

        self.view.window().open_file(
            '%s:%s:%s' % (file, line, col),
            sublime.ENCODED_POSITION)

    def on_highlight(self, res):
        if res == -1:
            vc_manager.return_in_history(self.view)
            return

        (file, line, col, _) = re.findall(
            RtagsBaseCommand.FILE_INFO_REG,
            vc_manager.references()[res])[0]

        self.view.window().open_file(
            '%s:%s:%s' % (file, line, col),
            sublime.ENCODED_POSITION | sublime.TRANSIENT)

    def _query(self, *args, **kwargs):
        return ''

    def _action(self, out, **kwargs):
        # Get current cursor location.
        cursorLine, cursorCol = self.view.rowcol(self.view.sel()[0].a)
        vc_manager.push_history(
            self.view.file_name(),
            int(cursorLine) + 1,
            int(cursorCol) + 1)

        # Pretty format the results.
        items = list(map(lambda x: x.decode('utf-8'), out.splitlines()))
        log.debug("Got items from command: {}".format(items))

        def out_to_tuple(item):
            (file, line, col, usage) = re.findall(
                RtagsBaseCommand.FILE_INFO_REG,
                item)[0]
            return [usage.strip(), file, int(line), int(col)]

        tuples = list(map(out_to_tuple, items))

        # If there is only one result no need to show it to user
        # just do navigation directly.
        if len(tuples) == 1:
            vc_manager.set_references(items)
            self.on_select(0)
            return

        # Sort the tuples by file and then line number and column.
        def file_line_col(item):
            return (item[1], item[2], item[3])
        tuples.sort(key=file_line_col)

        cursorIndex = -1

        # TODO(tillt): This smells a lot like not proper for Python.
        for i in range(0, len(tuples)):
            if tuples[i][2] == int(cursorLine) + 1:
                cursorIndex = i
                break

        def tuples_to_references(current):
            return "{}:{}:{}:".format(current[1], current[2], current[3])

        references = list(map(tuples_to_references, tuples))

        vc_manager.set_references(references)

        def tuples_to_items(current):
            return [current[0], "{}:{}:{}".format(
                        current[1].split('/')[-1],
                        current[2],
                        current[3])]

        items = list(map(tuples_to_items, tuples))

        self.view.window().show_quick_panel(
            items,
            self.on_select,
            sublime.MONOSPACE_FONT,
            cursorIndex,
            self.on_highlight)


# Commands that need the current filename and the cursor location
# in their query.
class RtagsLocationCommand(RtagsBaseCommand):

    def _query(self, *args, **kwargs):
        if 'col' in kwargs:
            col = kwargs['col']
            row = kwargs['row']
        else:
            row, col = self.view.rowcol(self.view.sel()[0].a)

        return '{}:{}:{}'.format(self.view.file_name(),
                                 row + 1, col + 1)


# Commands that need the current filename in their query.
class RtagsFileCommand(RtagsBaseCommand):

    def _query(self, *args, **kwargs):
        return '{}'.format(self.view.file_name())


class RtagsGetIncludeCommand(RtagsBaseCommand):

    def _query(self):
        return '--current-file={}'.format(self.view.file_name())

    def _action(self, out, **kwargs):
        # Pretty format the results.
        items = list(map(lambda x: x.decode('utf-8'), out.splitlines()))
        log.debug("Got items from command: {}".format(items))

        def on_select(index):
            if index == -1:
                return
            sublime.set_clipboard(items[index])

        self.view.window().show_quick_panel(
            items,
            on_select,
            sublime.MONOSPACE_FONT,
            -1)

    def run(self, edit, *args, **kwargs):
        # Do nothing if not called from supported code.
        if not supported_view(self.view):
            return

        symbol = get_word_under_cursor(self.view)
        if not symbol:
            return
        if not len(symbol):
            return

        job_args = kwargs
        job_args.update({'view': self.view})

        jobs.JobController.run_async(
            jobs.RTagsJob(
                "RTGetInclude" + jobs.JobController.next_id(),
                [self._query(), '--include-file', symbol],
                **job_args),
            partial(self.command_done, **kwargs),
            vc_manager.view_controller(self.view).status.progress)


class RtagsShowHistory(sublime_plugin.TextCommand):

    def run(self, edit):
        if not supported_view(self.view):
            return

        if not vc_manager.history_size():
            log.debug("History is empty")
            return

        # Get current cursor location.
        cursorLine, cursorCol = self.view.rowcol(self.view.sel()[0].a)

        vc_manager.push_history(
            self.view.file_name(),
            int(cursorLine) + 1,
            int(cursorCol) + 1)

        jump_items = list(vc_manager.history)

        def queue_to_panel_item(item):
            name = item[0].split('/')[-1]
            return [name, "{}:{}:{}".format(name, item[1], item[2])]

        panel_items = list(map(queue_to_panel_item, jump_items))

        def on_select(index):
            if index == -1:
                vc_manager.return_in_history(self.view)
                return

            for x in range(0, len(vc_manager.history) - index):
                vc_manager.history.pop()

            self.view.window().open_file(
                '%s:%s:%s' % (
                    jump_items[index][0],
                    jump_items[index][1],
                    jump_items[index][2]),
                sublime.ENCODED_POSITION)

        def on_highlight(index):
            if index == -1:
                vc_manager.return_in_history(self.view)
                return

            self.view.window().open_file(
                '%s:%s:%s' % (
                    jump_items[index][0],
                    jump_items[index][1],
                    jump_items[index][2]),
                sublime.ENCODED_POSITION | sublime.TRANSIENT)

        self.view.window().show_quick_panel(
            panel_items,
            on_select,
            sublime.MONOSPACE_FONT,
            len(panel_items) - 1,
            on_highlight)


class RtagsShowFixitsCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        if not supported_view(self.view):
            return

        # Get current cursor location.
        cursorLine, cursorCol = self.view.rowcol(self.view.sel()[0].a)
        vc_manager.push_history(
            self.view.file_name(),
            int(cursorLine) + 1,
            int(cursorCol) + 1)

        fixits = vc_manager.view_controller(self.view).fixits

        def on_select(res):
            if res == -1:
                vc_manager.return_in_history(self.view)
                return

            fixits.select(res)

        def on_highlight(res):
            if res == -1:
                vc_manager.return_in_history(self.view)
                return

            fixits.highlight(res)

        vc_manager.view_controller(self.view).fixits.show_selector(
            on_highlight,
            on_select)


class RtagsFixitCommand(RtagsBaseCommand):

    def run(self, edit, **args):
        vc_manager.view_controller(self.view).fixits.update(
            args['filename'],
            args['issues'])


class RtagsGoBackwardCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        vc_manager.return_in_history(self.view)


class RtagsSymbolRenameCommand(RtagsLocationCommand):

    def _action(self, out, **kwargs):

        items = list(map(lambda x: x.decode('utf-8'), out.splitlines()))

        def out_to_items(item):
            (file, row, col, _) = re.findall(
                RtagsBaseCommand.FILE_INFO_REG,
                item)[0]
            return [file, int(row), int(col)]

        items = list(map(out_to_items, items))

        if len(items) == 0:
            return

        self.old_name = ""

        word = get_word_under_cursor(self.view)
        if not word:
            return
        if not len(word):
            return

        self.old_name = word
        self.mutations = {}

        for (file, row, col) in items:
            log.debug("file {}, row {}, col {}".format(file, row, col))

            # Group all source file and line mutations.
            if file not in self.mutations:
                self.mutations[file] = {}
            if row not in self.mutations[file]:
                self.mutations[file][row] = []

            self.mutations[file][row].append(col)

        self.view.window().show_input_panel(
            "Rename {} occurance/s in {} file/s to".format(
                len(items),
                len(self.mutations)),
            self.old_name,
            self.on_done,
            None,
            None)

    def on_done(self, new_name):
        active_view = self.view

        for file in self.mutations:
            # Make sure we got the file opened, for undo context.
            self.view.window().open_file(file)

            tools.Utilities.replace_in_file(
                self.old_name,
                new_name,
                file,
                self.mutations[file])

            vc_manager.on_post_updated(self.view)

        # Switch focus back to the orignal active view to reduce confusion.
        self.view.window().focus_view(active_view)


class RtagsSymbolInfoCommand(RtagsLocationCommand):

    def _action(self, out, **kwargs):
        # Hover will give us coordinates here, keyboard-called symbol-
        # info will not give us coordinates, so we need to get em now.
        if 'col' in kwargs:
            row = kwargs['row']
            col = kwargs['col']
        else:
            row, col = self.view.rowcol(self.view.sel()[0].a)

        info.Controller.action(self.view, row, col, out)


class RtagsHoverInfo(sublime_plugin.EventListener):

    def on_hover(self, view, point, hover_zone):
        if hover_zone != sublime.HOVER_TEXT:
            return

        if not supported_view(view):
            log.debug("Unsupported view")
            return

        if not settings.get("hover"):
            return

        # Make sure the underlying view is in focus - enables in turn
        # that the view-controller shows its status.
        view.window().focus_view(view)

        (row, col) = view.rowcol(point)
        view.run_command(
            'rtags_symbol_info',
            {
                'switches': [
                    '--absolute-path',
                    '--json',
                    '--symbol-info'
                ],
                'col': col,
                'row': row
            })


class RtagsNavigationListener(sublime_plugin.EventListener):

    def cursor_pos(self, view, pos=None):
        if not pos:
            pos = view.sel()
            if len(pos) < 1:
                # something is wrong
                return None
            # we care about the first position
            pos = pos[0].a
        return view.rowcol(pos)

    def on_activated(self, view):
        if not supported_view(view):
            log.debug("Unsupported view")
            return

        log.debug("Activated supported view for view-id {}".format(view.id()))
        vc_manager.activate_view_controller(view)

    def on_close(self, view):
        if not supported_view(view):
            log.debug("Unsupported view")
            return

        log.debug("Closing view for view-id {}".format(view.id()))
        vc_manager.close(view)

    def on_modified(self, view):
        if not supported_view(view):
            log.debug("Unsupported view")
            return

        vc_manager.view_controller(view).fixits.clear()
        vc_manager.view_controller(view).idle.trigger()

    def on_post_save(self, view):
        log.debug("Post save triggered")
        # Do nothing if not called from supported code.
        if not supported_view(view):
            log.debug("Unsupported view")
            return

        vc_manager.on_post_updated(view)

    def on_post_text_command(self, view, command_name, args):
        # Do nothing if not called from supported code.
        if not supported_view(view):
            log.debug("Unsupported view")
            return

        if command_name == 'undo' and not view.is_dirty():
            vc_manager.on_post_updated(view)


class RtagsCompleteListener(sublime_plugin.EventListener):

    def on_query_completions(self, view, prefix, locations):
        # Check if autocompletion was disabled for this plugin.
        if not settings.get('auto_complete', True):
            return []

        # Do nothing if not called from supported code.
        if not supported_view(view):
            return []

        return completion.query(view, prefix, locations)


def update_settings():
    settings.update()

    if settings.get('verbose_log', True):
        log.info("Enabled verbose logging")
        ch.setFormatter(formatter_verbose)
        ch.setLevel(logging.DEBUG)
    else:
        log.info("Enabled normal logging")
        ch.setFormatter(formatter_default)
        ch.setLevel(logging.INFO)

    # Initialize settings with their defaults.
    settings.get('rc_timeout', 0.5)
    settings.get('rc_path', "/usr/local/bin/rc")
    settings.get('fixits', False)
    settings.get('hover', False)
    settings.get('auto_reindex', False)
    settings.get('auto_reindex_threshold', 30)

    settings.get('results_key', 'rtags_result_indicator')
    settings.get('status_key', 'rtags_status_indicator')
    settings.get('progress_key', 'rtags_progress_indicator')

    settings.add_on_change('filtered_clang_cursor_kind')

    settings.add_on_change('rc_timeout')
    settings.add_on_change('rc_path')
    settings.add_on_change('auto_complete')

    settings.add_on_change('results_key')
    settings.add_on_change('status_key')
    settings.add_on_change('progress_key')

    log.info("Settings updated")


def plugin_loaded():
    update_settings()
    tools.Reloader.reload_all()


def plugin_unloaded():
    jobs.JobController.stop_all()
