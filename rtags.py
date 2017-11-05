# -*- coding: utf-8 -*-

"""RTagsComplete plugin for Sublime Text 3.

Provides completion suggestions and much more for C/C++ languages
based on RTags.

Original code by Sergei Turukin.
Hacked with plenty of new features by Till Toenshoff.
Some code lifted from EasyClangComplete by Igor Bogoslavskyi.

TODO(tillt): The current tests are broken and need to get redone.
"""

import collections
import logging
import html
import re
import sublime
import sublime_plugin

from datetime import datetime
from os import path
from functools import partial

from .plugin import completion
from .plugin import fixits
from .plugin import idle
from .plugin import indicator
from .plugin import jobs
from .plugin import settings
from .plugin import tools


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

    def command_done(self, future, **kwargs):
        log.debug("Command done callback hit {}".format(future))

        if not future.done():
            log.warning("Command failed")
            return

        if future.cancelled():
            log.warning(("Command aborted"))
            return

        (job_id, out, error) = future.result()

        location = -1
        if 'col' in kwargs:
            location = self.view.text_point(kwargs['row'], kwargs['col'])

        if error:
            fixits_controller.signal_failure(view=self.view)
            self.view.show_popup(
                "<nbsp/>{}<nbsp/>".format(error.message),
                sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                location=location)
            return

        log.debug("Finished Command job {}".format(job_id))

        # We never needed this - maybe it got fixed in RTags?
        #
        # Dirty hack.
        # TODO figure out why rdm responds with 'Project loading'
        # for now just repeat query.
        #if error and error.code == jobs.JobError.PROJECT_LOADING:
        #    def rerun():
        #        self.view.run_command('rtags_location', {'switches': switches})
        #    sublime.set_timeout_async(rerun, 500)
        #    return

        # Drop the flag, we are going to navigate.
        navigation_helper.flag = NavigationHelper.NAVIGATION_DONE
        navigation_helper.switches = []

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
        if (navigation_helper.flag == NavigationHelper.NAVIGATION_DONE and
                self.view.is_dirty() and
                navigation_helper.data != get_view_text(self.view)):
            navigation_helper.switches = switches
            navigation_helper.data = get_view_text(self.view)
            navigation_helper.flag = NavigationHelper.NAVIGATION_REQUESTED
            fixits_controller.reindex(view=self.view, saved=False)
            # Never go further.
            return

        job_args = kwargs
        job_args.update({'view': self.view})

        jobs.JobController.run_async(
            jobs.RTagsJob(
                "RTBaseCommand" + jobs.JobController.next_id(),
                switches + [self._query(*args, **kwargs)],
                **job_args),
            partial(self.command_done, **kwargs),
            progress_indicator)

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

    def _action(self, out, **kwargs):

        # Pretty format the results.
        items = list(map(lambda x: x.decode('utf-8'), out.splitlines()))
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
        if not supported_view(self.view):
            return
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
        if 'col' in kwargs:
            col = kwargs['col']
            row = kwargs['row']
        else:
            row, col = self.view.rowcol(self.view.sel()[0].a)
        return '{}:{}:{}'.format(self.view.file_name(),
                                 row + 1, col + 1)


class HTMLTemplate:
    THEMES_PATH = "themes/Default"
    PACKAGE_PATH = "Packages/RTagsComplete"

    def __init__(self, name):
        self.template = None
        filepath = path.join(
                    path.dirname(__file__),
                    self.THEMES_PATH,
                    name + ".html")
        with open(filepath, 'rb') as file:
            self.template = file.read().decode('utf-8')

    def as_html(self, message):
        padded = self.template.replace('{', '{{').replace('}', '}}')
        substituted = padded.replace('[', '{').replace(']', '}')
        return substituted.format(message)


class RtagsSymbolInfoCommand(RtagsLocationCommand):
    SYMBOL_INFO_REG = r'(\S+):\s*(.+)'
    MAX_POPUP_WIDTH = 1800
    MAX_POPUP_HEIGHT = 900

    FILTER_TITLES=[
        'SymbolLength',
        'Range']

    def filter_title(self, title):
        return not title in RtagsSymbolInfoCommand.FILTER_TITLES

    def filter_items(self, item):
        return re.match(RtagsSymbolInfoCommand.SYMBOL_INFO_REG, item)

    def _action(self, out, **kwargs):
        items = list(map(lambda x: x.decode('utf-8'), out.splitlines()))
        items = list(filter(self.filter_items, items))

        # Consider dropping: `range` and `SymbolLength` as those add no value.
        if len(items) > 1:
            # Skip first item as that will not bring in any news.
            log.debug("Dropping first info as it is the filename and cursor position")
            del items[0]

        def out_to_items(item):
            (title, info) = re.findall(
                RtagsSymbolInfoCommand.SYMBOL_INFO_REG,
                item)[0]
            if not self.filter_title(title):
                return ''

            return                                                  \
                "<div class=\"info\"><span class=\"header\">{}"     \
                "</span><br /><span class=\"info\">{}</span></div>".format(
                    html.escape(title.strip(), quote=False),
                    html.escape(info.strip(), quote=False))

        info = '\n'.join(list(map(out_to_items, items)))
        rendered = HTMLTemplate("info_popup").as_html(info)
        location = -1
        if 'col' in kwargs:
            location = self.view.text_point(kwargs['row'], kwargs['col'])
        self.view.show_popup(
            rendered,
            sublime.HIDE_ON_MOUSE_MOVE_AWAY,
            max_width=self.MAX_POPUP_WIDTH,
            max_height=self.MAX_POPUP_HEIGHT,
            location=location)


class RtagsHoverInfo(sublime_plugin.EventListener):

    def on_hover(self, view, point, hover_zone):
        if hover_zone != sublime.HOVER_TEXT:
            return

        (row, col) = view.rowcol(point)
        view.run_command(
            'rtags_symbol_info',
            {
                'switches': ['--absolute-path', '--symbol-info'],
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

    def on_modified(self, view):
        if not supported_view(view):
            log.debug("Unsupported view")
            return
        fixits_controller.clear(view)
        idle_controller.trigger(view)

#    def on_selection_modified(self, view):
#        (row, col) = self.cursor_pos(view)
#        region = fixits_controller.cursor_region(view, row, col)
#        if region:
#            fixits_controller.show_fixit(view, region)

    def on_post_save(self, view):
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
            jobs.JobsController.run_async(jobs.ReindexJob(
                "RTPostSaveReindex" + jobs.JobController.next_id(),
                view.file_name(),
                b'',
                view))
            return

        # For some bizarre reason, we need to delay our re-indexing task
        # by substantial amounts of time until we may relatively risk-
        # free will truly be attached to the lifetime of a
        # fully functioning `rc -V ... --wait`. `rc ... --wait` appears to
        # prevent concurrent instances by aborting the old "wait" when new
        # "wait"-request comes in.
        #sublime.set_timeout(lambda self=self,view=view: self._save(view), 400)

        #log.debug("Bizarrely delayed save scheduled")

        idle_controller.sleep()
        fixits_controller.reindex(view=view, saved=True)


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
                jobs.JobController.run_async(jobs.ReindexJob(
                    "RTPostUndoReindex" + jobs.JobController.next_id(),
                    view.file_name(),
                    b'',
                    view))
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
        log.debug("Completion done callback hit {}".format(future))

        if not future.done():
            log.warning("Completion failed")
            return

        if future.cancelled():
            log.warning(("Completion aborted"))
            return

        (completion_job_id, suggestions, error, view) = future.result()

        if error:
            fixits_controller.signal_failure(view=self.view)
            log.debug("Completion job {} failed: {}".format(completion_job_id, error.message))
            return

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
        #
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

        pos_status = completion.position_status(trigger_position, view)

        if pos_status == completion.PositionStatus.WRONG_TRIGGER:
            # We are at a wrong trigger, remove all completions from the list.
            log.debug("Wrong trigger - hiding default completions")
            return ([], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)

        if pos_status == completion.PositionStatus.COMPLETION_NOT_NEEDED:
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
        if self.completion_job_id:
            jobs.JobController.stop(self.completion_job_id)

        # We do need to trigger a new completion.
        log.debug("Completion job {} triggered on view {}".format(completion_job_id, view))

        self.view = view
        self.completion_job_id = completion_job_id
        self.trigger_position = trigger_position
        row, col = view.rowcol(trigger_position)

        jobs.JobController.run_async(
            jobs.CompletionJob(
                completion_job_id,
                view.file_name(),
                get_view_text(view),
                view.size(),
                row,
                col,
                view),
            self.completion_done,
            progress_indicator)

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

    # Initialize settings with their defaults.
    settings.SettingsManager.get('rc_timeout', 0.5)
    settings.SettingsManager.get('rc_path', "/usr/local/bin/rc")
    settings.SettingsManager.get('fixits', False)
    settings.SettingsManager.get('auto_reindex', False)
    settings.SettingsManager.get('auto_reindex_threshold', 30)

    settings.SettingsManager.add_on_change('rc_timeout')
    settings.SettingsManager.add_on_change('rc_path')
    settings.SettingsManager.add_on_change('auto_complete')

    # TODO(tillt): Allow "fixits" setting to get live-updated.
    #settings.add_on_change('fixits', update_settings)

    # TODO(tillt): Allow "verbose_log" settings to get live-updated.
    #settings.add_on_change('verbose_log', update_settings)

    log.info("Settings updated")


def init():
    update_settings()

    globals()['navigation_helper'] = NavigationHelper()
    globals()['progress_indicator'] = indicator.ProgressIndicator()
    globals()['fixits_controller'] = fixits.Controller(
        settings.SettingsManager.get('fixits'),
        progress_indicator)
    globals()['idle_controller'] = idle.Controller(
        settings.SettingsManager.get('auto_reindex'),
        settings.SettingsManager.get('auto_reindex_threshold'),
        partial(fixits.Controller.reindex, self=fixits_controller, saved=False))

def plugin_loaded():
    tools.Reloader.reload_all()
    sublime.set_timeout(init, 200)


def plugin_unloaded():
    # Stop progress indicator, clear any regions, status and phantoms.
    fixits_controller.unload()
    # Stop `rc -m` thread.
    jobs.JobController.stop_all()
