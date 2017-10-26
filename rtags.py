# -*- coding: utf-8 -*-

"""RTagsComplete plugin for Sublime Text 3.

Provides completion suggestions and much more for C/C++ languages
based on RTags.

Original code by Sergei Turukin.
Hacked with plenty of new features by Till Toenshoff.
Some code lifted from EasyClangComplete by Igor Bogoslavskyi.

TODO(tillt): This desperately needs a refactor into submodules with
clean APIs instead of this horrible spaghetti code.
TODO(tillt): The current tests are broken and need to get redone.
TODO(tillt): Life is more important than any of the above, so fuck it.
"""

import collections
import logging
import re
import sublime
import sublime_plugin
import subprocess
import threading

import xml.etree.ElementTree as etree

from concurrent import futures
from datetime import datetime
from os import path
from functools import partial

from .plugin import fixits
from .plugin import indicator
from .plugin import jobs
from .plugin import settings
from .plugin import tools
from .plugin import idle


log = logging.getLogger("RTags")
log.setLevel(logging.DEBUG)
log.propagate = False

formatter_default = logging.Formatter(
    '[%(name)s:%(levelname)s]: %(message)s')
formatter_verbose = logging.Formatter(
    '[%(name)s:%(levelname)s]:[%(filename)s]:[%(funcName)s]:'
    '[%(threadName)s]: %(message)s')

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(formatter_default)
if not log.hasHandlers():
    log.addHandler(ch)


class PosStatus:
    """Enum class for position status.
    Taken from EasyClangComplete by Igor Bogoslavskyi

    Attributes:
        COMPLETION_NEEDED (int): completion needed
        COMPLETION_NOT_NEEDED (int): completion not needed
        WRONG_TRIGGER (int): trigger is wrong
    """
    COMPLETION_NEEDED = 0
    COMPLETION_NOT_NEEDED = 1
    WRONG_TRIGGER = 2

def get_pos_status(point, view):
    """Check if the cursor focuses a valid trigger.

    Args:
        point (int): position of the cursor in the file as defined by subl
        view (sublime.View): current view

    Returns:
        PosStatus: status for this position
    """
    trigger_length = 1

    word_on_the_left = view.substr(view.word(point - trigger_length))
    if word_on_the_left.isdigit():
        # don't autocomplete digits
        log.debug("Trying to auto-complete digit, are we? Not allowed")
        return PosStatus.WRONG_TRIGGER

    # slightly counterintuitive `view.substr` returns ONE character
    # to the right of given point.
    curr_char = view.substr(point - trigger_length)
    wrong_trigger_found = False
    for trigger in settings.SettingsManager.get('triggers'):
        # compare to the last char of a trigger
        if curr_char == trigger[-1]:
            trigger_length = len(trigger)
            prev_char = view.substr(point - trigger_length)
            if prev_char == trigger[0]:
                log.debug("Matched trigger '%s'", trigger)
                return PosStatus.COMPLETION_NEEDED
            else:
                log.debug("Wrong trigger '%s%s'", prev_char, curr_char)
                wrong_trigger_found = True

    if wrong_trigger_found:
        # no correct trigger found, but a wrong one fired instead
        log.debug("Wrong trigger fired")
        return PosStatus.WRONG_TRIGGER

    # if nothing fired we don't need to do anything
    log.debug("No completions needed")
    return PosStatus.COMPLETION_NOT_NEEDED


def get_view_text(view):
    return bytes(view.substr(sublime.Region(0, view.size())), "utf-8")


def supported_view(view):
    if not view:
        return False

    file_types = settings.SettingsManager.get('file_types', ["source.c", "source.c++"])
    if not view.scope_name(view.sel()[0].a).split()[0] in file_types:
        return False

    if not view.file_name():
        return False

    if view.is_scratch():
        return False

    if view.buffer_id() == 0:
        return False

    if not path.exists(view.file_name()):
        return False

    return True


class NavigationHelper(object):
    NAVIGATION_REQUESTED = 1
    NAVIGATION_DONE = 2

    def __init__(self):
        # navigation indicator, possible values are:
        # - NAVIGATION_REQUESTED
        # - NAVIGATION_DONE
        self.flag = NavigationHelper.NAVIGATION_DONE
        # rc utility switches to use for callback
        self.switches = []
        # File contents that has been passed to reindexer last time.
        self.data = ''
        # History of navigations.
        # Elements are tuples (filename, line, col).
        self.history = collections.deque()


class RtagsBaseCommand(sublime_plugin.TextCommand):
    FILE_INFO_REG = r'(\S+):(\d+):(\d+):(.*)'

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
        if (navigation_helper.flag == NavigationHelper.NAVIGATION_DONE and
                self.view.is_dirty() and
                navigation_helper.data != get_view_text(self.view)):
            navigation_helper.switches = switches
            navigation_helper.data = get_view_text(self.view)
            navigation_helper.flag = NavigationHelper.NAVIGATION_REQUESTED
            fixits_controller.reindex(view=self.view, saved=False)
            # Never go further.
            return

        args = self._query(*args, **kwargs)

        (_, out) = jobs.RTagsJob(
            "RTBasicJob" + jobs.ThreadManager.next_job_id(),
            switches + [args]).run_process()

        # Dirty hack.
        # TODO figure out why rdm responds with 'Project loading'
        # for now just repeat query.
        if out == b'Project loading\n':
            def rerun():
                self.view.run_command('rtags_location', {'switches': switches})
            sublime.set_timeout_async(rerun, 500)
            return

        # Drop the flag, we are going to navigate.
        navigation_helper.flag = NavigationHelper.NAVIGATION_DONE
        navigation_helper.switches = []

        self._action(out)

    def on_select(self, res):
        if res == -1:
            return

        (row, col) = self.view.rowcol(self.view.sel()[0].a)

        navigation_helper.history.append(
            (self.view.file_name(), row + 1, col + 1))

        (file, line, col, _) = re.findall(
            RtagsBaseCommand.FILE_INFO_REG,
            self.last_references[res])[0]

        if len(navigation_helper.history) > int(settings.SettingsManager.get('jump_limit', 10)):
            navigation_helper.history.popleft()

        view = self.view.window().open_file(
            '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION)

    def on_highlight(self, res):
        if res == -1:
            return

        (file, line, col, _) = re.findall(
            RtagsBaseCommand.FILE_INFO_REG,
            self.last_references[res])[0]

        view = self.view.window().open_file(
            '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION | sublime.TRANSIENT)

    def _query(self, *args, **kwargs):
        return ''

    def _validate(self, stdout):
        # Check if the file in question is not indexed by rtags.
        if stdout == b'Not indexed\n':
            self.view.show_popup("<nbsp/>Not indexed<nbsp/>")
            return False

        # Check if rtags is actually running.
        if stdout.decode('utf-8').startswith("Can't seem to connect to server"):
            self.view.show_popup("<nbsp/>{}<nbsp/>".format(stdout.decode('utf-8')))
            return False
        return True

    def _action(self, stdout):
        if not self._validate(stdout):
            return

        # Pretty format the results.
        items = list(map(lambda x: x.decode('utf-8'), stdout.splitlines()))
        self.last_references = items

        def out_to_items(item):
            (file, line, _, usage) = re.findall(RtagsBaseCommand.FILE_INFO_REG, item)[0]
            return [usage.strip(), "{}:{}".format(file.split('/')[-1], line)]

        items = list(map(out_to_items, items))

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


class RtagsShowFixitsCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        fixits_controller.show_selector(self.view)


class RtagsFixitCommand(RtagsBaseCommand):

    def run(self, edit, **args):
        fixits_controller.update(args['filename'], args['issues'])


class RtagsGoBackwardCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        try:
            file, line, col = navigation_helper.history.pop()
            view = self.view.window().open_file(
                '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION)
        except IndexError:
            pass


class RtagsLocationCommand(RtagsBaseCommand):

    def _query(self, *args, **kwargs):
        row, col = self.view.rowcol(self.view.sel()[0].a)
        return '{}:{}:{}'.format(self.view.file_name(),
                                 row + 1, col + 1)


class RtagsSymbolInfoCommand(RtagsLocationCommand):
    SYMBOL_INFO_REG = r'(\S+):\s*(.+)'

    def filter_items(self, item):
        return re.match(RtagsSymbolInfoCommand.SYMBOL_INFO_REG, item)

    def _action(self, out):
        if not self._validate(out):
            return

        items = list(map(lambda x: x.decode('utf-8'), out.splitlines()))
        items = list(filter(self.filter_items, items))

        def out_to_items(item):
            (title, info) = re.findall(
                RtagsSymbolInfoCommand.SYMBOL_INFO_REG,
                item)[0]
            return [info.strip(), title.strip()]

        items = list(map(out_to_items, items))

        self.last_references = items

        self.view.window().show_quick_panel(
            items,
            None,
            sublime.MONOSPACE_FONT,
            -1,
            None)


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

    def on_modified(self, view):
        if not supported_view(view):
            log.debug("Unsupported view")
            return
        fixits_controller.clear(view)
        idle_controller.trigger(view)

    def _save(self, view):
        log.debug("Post post save triggered")

        idle_controller.sleep()
        fixits_controller.reindex(view=view, saved=True)

    def on_post_save_async(self, view):
        log.debug("Post save triggered")
        # Do nothing if not called from supported code.
        if not supported_view(view):
            log.debug("Unsupported view")
            return

        # Do nothing if we dont want to support fixits.
        if not fixits_controller.supported:
            logging.debug("Fixits are disabled")
            # Run rc --check-reindex to reindex just saved files.
            # We do this manually even though rtags SHOULD watch
            # all our files and reindex accordingly. However on macOS
            # this feature is broken.
            # See https://github.com/Andersbakken/rtags/issues/1052
            jobs.RTagsJob(
                "RTSyncJob" + jobs.ThreadManager.next_job_id(),
                ['-x', view.file_name()]).run_process()
            return

        # For some bizarre reason, we need to delay our re-indexing task
        # by substantial amounts of time until we may relatively risk-
        # free will truly be attached to the lifetime of a
        # fully functioning `rc -V ... --wait`. `rc ... --wait` appears to
        # prevent concurrent instances by aborting the old "wait" when new
        # "wait"-request comes in.
        sublime.set_timeout(lambda self=self,view=view: self._save(view), 400)

    def on_post_text_command(self, view, command_name, args):
        # Do nothing if not called from supported code.
        if not supported_view(view):
            log.debug("Unsupported view")
            return

        # If view get 'clean' after undo check if we need reindex.
        if command_name == 'undo' and not view.is_dirty():

            if not fixits_controller.supported:
                logging.debug("Fixits are disabled")
                # Run rc --check-reindex to reindex just saved files.
                # We do this manually even though rtags SHOULD watch
                # all our files and reindex accordingly. However on macOS
                # this feature is broken.
                # See https://github.com/Andersbakken/rtags/issues/1052
                jobs.RTagsJob(
                    "RTSyncJob" + jobs.ThreadManager.next_job_id(),
                    ['-V', view.file_name()]).run_process()
                return

            idle_controller.sleep()
            fixits_controller.reindex(view=view, saved=True)


class RtagsCompleteListener(sublime_plugin.EventListener):

    def __init__(self):
        self.suggestions = []
        self.completion_job_id = None
        self.view = None
        self.trigger_position = None

    def completion_done(self, future):
        if not future.done():
            log.warning("Completion failed")
            return

        if future.cancelled():
            log.warning(("Completion aborted"))
            return

        (view, completion_job_id, suggestions) = future.result()

        log.debug("Finished completion job {} for view {}".format(completion_job_id, view))

        if view != self.view:
            log.debug("Completion done for different view")
            return

        # Did we have a different completion in mind?
        if completion_job_id != self.completion_job_id:
            log.debug("Completion done for unexpected completion")
            return

        active_view = sublime.active_window().active_view()

        # Has the view changed since triggering completion?
        if view != active_view:
            log.debug("Completion done for inactive view")
            return

        # We accept both current position and position to the left of the
        # current word as valid as we don't know how much user already typed
        # after the trigger.
        current_position = view.sel()[0].a
        valid_positions = [current_position, view.word(current_position).a]

        if self.trigger_position not in valid_positions:
            log.debug("Trigger position {} does not match valid positions {}".format(
                valid_positions,
                self.trigger_position))
            return

        self.suggestions = suggestions

        #log.debug("suggestiongs: {}".format(suggestions))

        # Hide the completion we might currently see as those are sublime's
        # own completions which are not that useful to us C++ coders.
        # This neat trick was borrowed from EasyClangComplete.
        view.run_command('hide_auto_complete')

        # Trigger a new completion event to show the freshly acquired ones.
        view.run_command('auto_complete', {
            'disable_auto_insert': True,
            'api_completions_only': False,
            'next_competion_if_showing': False})

    def on_query_completions(self, view, prefix, locations):
        # Check if autocompletion was disabled for this plugin.
        if not settings.SettingsManager.get('auto_complete', True):
            return []

        # Do nothing if not called from supported code.
        if not supported_view(view):
            return []

        log.debug("Completion prefix: {}".format(prefix))

        # libclang does auto-complete _only_ at whitespace and punctuation chars
        # so "rewind" location to that character
        trigger_position = locations[0] - len(prefix)

        pos_status = get_pos_status(trigger_position, view)

        if pos_status == PosStatus.WRONG_TRIGGER:
            # We are at a wrong trigger, remove all completions from the list.
            log.debug("Wrong trigger - hiding default completions")
            return ([], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)

        if pos_status == PosStatus.COMPLETION_NOT_NEEDED:
            log.debug("Completion not needed - showing default completions")
            return None

        # Render some unique identifier for us to match a completion request
        # to its original query.
        completion_job_id = "RTCompletionJob{}".format(trigger_position)

        # If we already have a completion for this position, show that.
        if self.completion_job_id == completion_job_id:
            log.debug("We already got a completion for this position available.")
            return self.suggestions, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS

        # Cancel a completion that might be in flight.

        # We do need to trigger a new completion.
        log.debug("Completion job {} triggered on view {}".format(completion_job_id, view))

        self.view = view
        self.completion_job_id = completion_job_id
        self.trigger_position = trigger_position
        text = get_view_text(view)
        row, col = view.rowcol(trigger_position)
        filename = view.file_name()
        size = view.size()

        job = jobs.CompletionJob(view, completion_job_id, filename, text, size, row, col)

        jobs.ThreadManager.run_job(job, self.completion_done)

        return ([], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)


def update_settings():
    settings.SettingsManager.update()

    if settings.SettingsManager.get('verbose_log', True):
        log.info("Enabled verbose logging")
        ch.setFormatter(formatter_verbose)
        ch.setLevel(logging.DEBUG)
    else:
        log.info("Enabled normal logging")
        ch.setFormatter(formatter_default)
        ch.setLevel(logging.INFO)

    log.info("Settings updated")


def init():
    update_settings()

    globals()['navigation_helper'] = NavigationHelper()
    globals()['fixits_controller'] = fixits.Controller(settings.SettingsManager.get('fixits', False))
    globals()['idle_controller'] = idle.Controller(
        settings.SettingsManager.get('auto_reindex', False),
        settings.SettingsManager.get('auto_reindex_threshold', 30),
        partial(fixits.Controller.reindex, self=fixits_controller, saved=False))

    settings.SettingsManager.add_on_change('rc_path')
    settings.SettingsManager.add_on_change('rc_timeout')
    settings.SettingsManager.add_on_change('auto_complete')
    settings.SettingsManager.add_on_change('verbose_log')

    # TODO(tillt): Allow "fixits" setting to get live-updated.
    #settings.add_on_change('fixits', update_settings)

    # TODO(tillt): Allow "verbose_log" settings to get live-updated.
    #settings.add_on_change('verbose_log', update_settings)


def plugin_loaded():
    tools.Reloader.reload_all()
    sublime.set_timeout(init, 200)


def plugin_unloaded():
    # Stop progress indicator, clear any regions, status and phantoms.
    fixits_controller.unload()
    # Stop `rc -m` thread.
    jobs.ThreadManager.stop_all_jobs()
