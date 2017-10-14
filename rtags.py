# -*- coding: utf-8 -*-

"""RTagsComplete plugin for Sublime Text 3.

Provides completion suggestions and much more for C/C++ languages
based on rtags.

Original code by Sergei Turukin.
Enhanced code by Till Toenshoff.
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
from threading import RLock


# RTagsComplete settings
settings = None
# Path to rc utility.
RC_PATH = ''
# Timeout for common rc incocations.
RC_TIMEOUT = 0.5
# Enable RTagsComplete autocompletion.
auto_complete = True


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


def run_rc(switches, input=None, quote=True, *args):
    p = subprocess.Popen([RC_PATH] + switches + list(args),
                         stderr=subprocess.PIPE,
                         stdout=subprocess.PIPE,
                         stdin=subprocess.PIPE)
    if quote:
        log.debug(' '.join(p.args))
    return p.communicate(input=input, timeout=RC_TIMEOUT)


def rc_is_indexing():
    (out, _) = run_rc(['--is-indexing', '--silent-query'], None, False)
    return out.decode().strip() == "1"


def get_view_text(view):
    return bytes(view.substr(sublime.Region(0, view.size())), "utf-8")


def supported_view(view):
    if not view:
        return False

    if settings == None:
        return False

    file_types = settings.get('file_types', ["source.c", "source.c++"])
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


class ProgressIndicator():
    # Borrowed from EasyClangComplete.
    MSG_CHARS_COLOR_SUBLIME = u'⣾⣽⣻⢿⡿⣟⣯⣷'

    def __init__(self):
        self.size = 8
        self.view = None
        self.busy = False
        self.stopping = False
        self.status_key = settings.get('status_key', 'rtags_status_indicator')

    def start(self, view):
        if self.view != view:
            self.stop()
        self.busy = True
        self.view = view
        sublime.set_timeout(lambda: self.run(1), 0)

    def stop(self):
        if not self.busy:
            return;
        self.stopping = True
        sublime.set_timeout(lambda: self.run(1), 0)

    def run(self, i):
        if self.stopping or not self.busy or not rc_is_indexing():
            self.busy = False
            self.stopping = False
            if self.view:
                self.view.erase_status(self.status_key)
            return

        from random import sample

        mod = len(ProgressIndicator.MSG_CHARS_COLOR_SUBLIME)
        rands = [ProgressIndicator.MSG_CHARS_COLOR_SUBLIME[x] for x in sample(range(mod), mod)]

        self.view.set_status(self.status_key, 'RTags {}'.format(''.join(rands)))

        sublime.set_timeout(lambda: self.run(i), 100)


class RConnectionThread(threading.Thread):

    def __init__(self):
        threading.Thread.__init__(self)
        self.killing = False
        self.p = None

    def notify(self):
        sublime.active_window().active_view().run_command(
            'rtags_location',
            {'switches': navigation_helper.switches})

    # `rc -m` will feed stdout with xml like this:
    #
    # <?xml version="1.0" encoding="utf-8"?>
    #  <checkstyle>
    #   <file name="/home/ramp/tmp/pthread_simple.c">
    #    <error line="54" column="5" severity="warning" message="implicit declaration of function 'sleep' is invalid in C99"/>
    #    <error line="59" column="5" severity="warning" message="implicit declaration of function 'write' is invalid in C99"/>
    #    <error line="60" column="5" severity="warning" message="implicit declaration of function 'lseek' is invalid in C99"/>
    #    <error line="78" column="7" severity="warning" message="implicit declaration of function 'read' is invalid in C99"/>
    #   </file>
    #  </checkstyle>
    # <?xml version="1.0" encoding="utf-8"?>
    # <progress index="1" total="1"></progress>
    #
    # So we need to split xml chunks somehow
    # Will start by looking for opening tag (<checkstyle, <progress)
    # and parse accumulated xml when we encounter closing tag
    # TODO deal with < /> style tags

    def run(self):
        started_at = datetime.now()

        log.debug("Restarting rc communication")

        with subprocess.Popen(
            [RC_PATH, '-m', '--silent-query'],
            stderr=subprocess.STDOUT,
            stdout=subprocess.PIPE) as p:

            self.p = p

            rgxp = re.compile(r'<(\w+)')
            buffer = ''  # xml to be parsed
            start_tag = ''

            for line in iter(self.p.stdout.readline, b''):
                line = line.decode('utf-8')
                self.p.poll()

                if not start_tag:
                    start_tag = re.findall(rgxp, line)
                    start_tag = start_tag[0] if len(start_tag) else ''

                buffer += line

                if "Can't seem to connect to server" in line:
                    log.error(line);
                    if sublime.ok_cancel_dialog(
                        "Can't seem to connect to server. Make sure RTags `rdm` is running, then retry.",
                        "Retry"):
                        self.run()

                if '</{}>'.format(start_tag) in line:
                    tree = etree.fromstring(buffer)
                    # OK, we received some chunk
                    # check if it is progress update
                    if (tree.tag == 'progress' and
                            tree.attrib['index'] == tree.attrib['total'] and
                            navigation_helper.flag == NavigationHelper.NAVIGATION_REQUESTED):
                        # notify about event
                        sublime.set_timeout(self.notify, 10)

                    if  tree.tag == 'checkstyle':
                        key = 0

                        mapping = {
                            'warning': 'warning',
                            'error': 'error',
                            'fixit': 'error'
                        }

                        issues = {
                            'warning': [],
                            'error': []
                        }

                        for file in tree.findall('file'):
                            for error in file.findall('error'):
                                if error.attrib["severity"] in mapping.keys():
                                    issue = {}
                                    issue['line'] = int(error.attrib["line"])
                                    issue['column'] = int(error.attrib["column"])
                                    if 'length' in error.attrib:
                                        issue['length'] = int(error.attrib["length"])
                                    else:
                                        issue['length'] = -1
                                    issue['message'] = error.attrib["message"]

                                    issues[mapping[error.attrib["severity"]]].append(issue)

                            sublime.active_window().active_view().run_command(
                                'rtags_fixit',
                                {
                                    'filename': file.attrib["name"],
                                    'issues': issues
                                })

                    buffer = ''
                    start_tag = ''
        self.p = None

        log.debug("RTags client ran for {} seconds".format((datetime.now() - started_at).seconds))
        log.debug("RTags communication thread is quitting")

    def stop(self):
        log.debug("We were asked to stop")

        if self.is_alive():
            self.killing = True
            self.p.kill()
            self.p = None


class CompletionJob():

    def __init__(self, view, completion_job_id, filename, text, size, row, col):
        self.completion_job_id = completion_job_id
        self.filename = filename
        self.text = text
        self.size = size
        self.row = row
        self.col = col
        self.view = view

        self.p = None

    def run(self):
        self.p = None

        switches = []
        # rc itself.
        switches.append(RC_PATH)
        # Auto-complete switch.
        switches.append('-l')
        # The query.
        switches.append('{}:{}:{}'.format(self.filename, self.row + 1, self.col + 1))
        # We want to complete on an unsaved file.
        switches.append('--unsaved-file')
        # We launch rc utility with both filename:line:col and filename:length
        # because we're using modified file which is passed via stdin (see --unsaved-file
        # switch)
        switches.append('{}:{}'.format(self.filename, self.size))
        # Make this query block until getting answered.
        switches.append('--synchronous-completions')

        self.p = subprocess.Popen(
            switches,
            stderr=subprocess.STDOUT,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE)

        # We do not use the regular timeout as this is an async job and
        # hence waiting much longer than usual is entirely fine.
        (out, _) = self.p.communicate(input=self.text, timeout=30)

        suggestions = []
        for line in out.splitlines():
            # line is like this
            # "process void process(CompletionThread::Request *request) CXXMethod"
            # "reparseTime int reparseTime VarDecl"
            # "dump String dump() CXXMethod"
            # "request CompletionThread::Request * request ParmDecl"
            # we want it to show as process()\tCXXMethod
            #
            # output is list of tuples: first tuple element is what we see in popup menu
            # second is what inserted into file. '$0' is where to place cursor.
            # TODO play with $1, ${2:int}, ${3:string} and so on.
            elements = line.decode('utf-8').split()
            suggestions.append(('{}\t{}'.format(' '.join(elements[1:-1]), elements[-1]),
                                '{}$0'.format(elements[0])))

        self.p = None

        return (self.view, self.completion_job_id, suggestions)

    # Unused so far - may be pointless.
    def stop(self):
        self.p.kill()
        self.p = None


class FixitsController():
    THEMES_PATH = "RTagsComplete/themes/Default"
    PACKAGE_PATH = "Packages/RTagsComplete"

    CATEGORY_WARNING = "warning"
    CATEGORY_ERROR = "error"

    CATEGORIES = [ CATEGORY_WARNING, CATEGORY_ERROR]

    CATEGORY_FLAGS = {
        CATEGORY_WARNING: sublime.DRAW_NO_FILL,
        CATEGORY_ERROR: sublime.DRAW_NO_FILL
    }

    PHANTOMS_TAG = "rtags_phantoms"

    def __init__(self, supported):
        self.supported = supported
        self.regions = {}
        self.issues = None
        self.waiting = False
        self.filename = None
        self.view = None
        self.results_key = settings.get('results_key', 'rtags_result_indicator')
        self.templates = {}
        self.navigation_items = None

        names = ["phantom"]

        for category in FixitsController.CATEGORIES:
            self.templates[category] = {}
            for name in names:
                filename = "{}_{}.html".format(category, name)
                filepath = path.join(
                    path.dirname(path.dirname(__file__)),
                    FixitsController.THEMES_PATH,
                    filename)

                with open(filepath, 'rb') as file:
                    self.templates[category][name] = file.read().decode('utf-8')


    def as_html(self, template, message):
        padded = template.replace('{', '{{').replace('}', '}}')
        substituted = padded.replace('[', '{').replace(']', '}')
        return substituted.format(message)


    def on_select(self, res):
        (file, line, col) = self.navigation_items[res]
        view = self.view.window().open_file(
            '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION)


    def on_highlight(self, res):
        (file, line, col) = self.navigation_items[res]
        view = self.view.window().open_file(
            '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION | sublime.TRANSIENT)


    def show_selector(self, view):
        if not supported_view(view):
            return

        if view.file_name() != self.filename:
            return

        def issue_to_panel_item(issue):
            return [
                issue['message'],
                "{}:{}:{}".format(self.filename.split('/')[-1], issue['line'], issue['column'])]

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

        view.window().show_quick_panel(
            items,
            self.on_select,
            sublime.MONOSPACE_FONT,
            -1,
            self.on_highlight)


    def category_key(self, category):
        return "rtags-{}-mark".format(category)

    def clear_regions(self):
        if not self.view:
            return
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
                FixitsController.CATEGORY_FLAGS[category])

    def clear_phantoms(self):
        if not self.view:
            return
        self.view.erase_phantoms(FixitsController.PHANTOMS_TAG)

    def update_phantoms(self, issues):
        if not self.view:
            return

        self.phantom_set = sublime.PhantomSet(self.view, FixitsController.PHANTOMS_TAG)

        def issue_to_phantom(category, issue):
            point = self.view.text_point(issue['line']-1, 0)
            start = self.view.line(point).a
            return sublime.Phantom(
                sublime.Region(start, start+1),
                self.as_html(self.templates[category]['phantom'], issue['message']),
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

    def clear_results(self):
        if not self.view:
            return
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

        self.view.set_status(self.results_key, "RTags {}".format(" ".join(results)))

    def clear(self, view=None):
        if not self.view:
            return

        # Skip of we wanted to clear a specific view but never drew onto it.
        if view and (view != self.view):
            return

        self.clear_results()
        self.clear_regions()
        self.clear_phantoms()
        self.regions = {}
        self.issues = None
        self.view = None
        self.filename = None

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

        self.update_results(issues)
        self.update_regions(issues)
        self.update_phantoms(issues)
        self.show_regions()
        self.issues = issues

    def expect(self, view):
        self.clear()

        if not self.supported:
            log.debug("Fixits are disabled")
            return

        if not rc_thread.is_alive():
            if self.waiting:
                sublime.error_message(
                    "Something went wrong with the rtags communication."
                    " We won't be able to show any errors/warnings/fixits"
                    " after re-index.")
                return

            self.waiting = True
            globals()['rc_thread'] = RConnectionThread()
            rc_thread.start()
            sublime.set_timeout(lambda: self.expect(view), 100)
            return

        self.waiting = False

        run_rc(['-x'], None, True, view.file_name())
        progress_indicator.start(view)
        self.filename = view.file_name()

        log.debug("Expecting indexing results for {}".format(self.filename))

        self.view = view


    #def hover_region(self, view, point):
    #    if self.view != view:
    #        return

    #    for category, regions in self.regions.items():
    #        for region in regions:
    #            if region['region'].contains(point):
    #                self.show_fixit(category, region)
    #                return

    #def cursor_region(self, view, row, col):
    #    if not row:
    #        return

    #    if self.view != view:
    #        return

    #    start = view.text_point(row, 0)
    #    end = view.line(start).b
    #    cursor_region = sublime.Region(start, end)

    #    for category, regions in self.regions.items():
    #        for region in regions:
    #            if cursor_region.contains(region['region']):
    #                self.show_fixit(category, region)
    #                return


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
            self._reindex(self.view.file_name())
            # Never go further.
            return

        (out, err) = run_rc(switches, None, True, self._query(*args, **kwargs))
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

        self._action(out, err)

    def _reindex(self, filename):
        run_rc(['-V'], get_view_text(self.view), True, filename,
               '--unsaved-file', '{}:{}'.format(filename, self.view.size()))

    def on_select(self, res):
        if res == -1:
            return

        (row, col) = self.view.rowcol(self.view.sel()[0].a)

        navigation_helper.history.append(
            (self.view.file_name(), row + 1, col + 1))

        (file, line, col, _) = re.findall(
            RtagsBaseCommand.FILE_INFO_REG,
            self.last_references[res])[0]

        if len(navigation_helper.history) > int(settings.get('jump_limit', 10)):
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

    def _validate(self, stdout, stderr):
        # Check if the file in question is not indexed by rtags.
        if stdout == b'Not indexed\n':
            self.view.show_popup("<nbsp/>Not indexed<nbsp/>")
            return False

        # Check if rtags is actually running.
        if stdout.decode('utf-8').startswith("Can't seem to connect to server"):
            self.view.show_popup("<nbsp/>{}<nbsp/>".format(stdout.decode('utf-8')))
            return False
        return True

    def _action(self, stdout, stderr):
        if not self._validate(stdout, stderr):
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

    def _action(self, out, err):
        if not self._validate(out, err):
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

    #def on_hover(self, view, point, hover_zone):
    #     # Do nothing if not called from supported code.
    #     if not supported_file_type(view):
    #         return
    #     fixits_controller.hover_region(view, point)

    #def on_selection_modified(self, view):
    #    # Do nothing if not called from supported code.
    #    if not supported_file_type(view):
    #        return
    #    (row, col) = self.cursor_pos(view)
    #    fixits_controller.cursor_region(view, row, col)

    def on_modified_async(self, view):
        if not supported_view(view):
            log.debug("Unsupported view")
            return
        fixits_controller.clear(view)

    def on_post_save_async(self, view):
        # Do nothing if not called from supported code.
        if not supported_view(view):
            log.debug("Unsupported view")
            return

        # Do nothing if we dont want to support fixits.
        if not fixits_controller.supported:
            logging.debug("Fixits are disabled")
            # Run rc --check-reindex to reindex just saved files.
            run_rc(['-x'], None, True, view.file_name())
            return

        fixits_controller.expect(view)

    def on_post_text_command(self, view, command_name, args):
        # Do nothing if not called from supported code.
        if not supported_view(view):
            log.debug("Unsupported view")
            return

        # If view get 'clean' after undo check if we need reindex.
        if command_name == 'undo' and not view.is_dirty():
            run_rc(['-V'], None, False, view.file_name())


class RtagsCompleteListener(sublime_plugin.EventListener):

    pool = futures.ThreadPoolExecutor(max_workers=1)
    lock = RLock()

    def __init__(self):
        self.suggestions = []
        self.completion_job_id = None
        self.view = None

    def completion_done(self, future):
        if not future.done():
            log.warning("Completion failed")
            return

        (view, completion_job_id, suggestions) = future.result()

        log.debug("Finished completion job {} for view {}".format(completion_job_id, view))

        # Has the view changed since triggering completion?
        if view != self.view:
            log.debug("Completion done for switched view")
            return

        # Did we have a different completion in mind?
        if completion_job_id != self.completion_job_id:
            log.debug("Completion done for wrong completion")
            return

        self.suggestions = suggestions

        # Hide the completion we might currently see as those are sublime's
        # own completions which are not that useful to us C++ coders.
        # This neat trick was borrowed from EasyClangComplete.
        view.run_command('hide_auto_complete')

        # Trigger a new completion event to show the freshly acquired ones.
        view.run_command('auto_complete', {
            'disable_auto_insert': True,
            'api_completions_only': False,
            'next_competion_if_showing': False})

    def on_query_completions(self, view, prefix, location):
        # Check if autocompletion was disabled for this plugin.
        if not auto_complete:
            return []

        # Do nothing if not called from supported code.
        if not supported_view(view):
            return []

        # libclang does auto-complete _only_ at whitespace and punctuation chars
        # so "rewind" location to that character
        trigger_position = location[0] - len(prefix)

        # Render some unique identifier for us to match a completion request
        # to its original query.
        completion_job_id = "CompletionJobId{}".format(trigger_position)

        # If we already have a completion for this position, show that.
        if self.completion_job_id == completion_job_id:
            return self.suggestions, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS

        # We do need to trigger a new completion.
        log.debug("Completion job {} triggered on view {}".format(completion_job_id, view))

        self.view = view
        self.completion_job_id = completion_job_id
        text = get_view_text(view)
        row, col = view.rowcol(trigger_position)
        filename = view.file_name()
        size = view.size()

        job = CompletionJob(view, completion_job_id, filename, text, size, row, col)

        with RtagsCompleteListener.lock:
            future = RtagsCompleteListener.pool.submit(job.run)
            future.add_done_callback(self.completion_done)

        return ([], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)


def update_settings():
    log.info("Settings updated")

    globals()['settings'] = sublime.load_settings(
        'RtagsComplete.sublime-settings')

    globals()['RC_PATH'] = settings.get('rc_path', 'rc')
    globals()['RC_TIMEOUT'] = settings.get('rc_timeout', 0.5)
    globals()['auto_complete'] = settings.get('auto_complete', True)

    if settings.get('verbose_log', True):
        log.info("Enabled verbose logging")
        ch.setFormatter(formatter_verbose)
        ch.setLevel(logging.DEBUG)
    else:
        log.info("Enabled normal logging")
        ch.setFormatter(formatter_default)
        ch.setLevel(logging.INFO)


def init():
    update_settings()

    globals()['rc_thread'] = RConnectionThread()
    globals()['navigation_helper'] = NavigationHelper()
    globals()['progress_indicator'] = ProgressIndicator()
    globals()['fixits_controller'] = FixitsController(settings.get('fixits', False))

    rc_thread.start()

    settings.add_on_change('rc_path', update_settings)
    settings.add_on_change('rc_timeout', update_settings)
    settings.add_on_change('auto_complete', update_settings)
    settings.add_on_change('verbose_log', update_settings)

    # TODO(tillt): Allow "fixits" setting to get live-updated.
    #settings.add_on_change('fixits', update_settings)

    # TODO(tillt): Allow "verbose_log" settings to get live-updated.
    #settings.add_on_change('verbose_log', update_settings)


def plugin_loaded():
    sublime.set_timeout(init, 200)


def plugin_unloaded():
    # Stop progress indicator.
    progress_indicator.stop()
    # Stop `rc -m` thread.
    sublime.set_timeout(rc_thread.stop, 100)
