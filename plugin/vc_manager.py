# -*- coding: utf-8 -*-

"""View Controller.

"""

import collections
import logging
import sublime

from . import jobs
from . import settings
from . import vc

log = logging.getLogger("RTags")


"""ViewController manager singleton.
Manages ViewControllers, attaching them to views.
"""

NAVIGATION_REQUESTED = 1
NAVIGATION_DONE = 2

controllers = {}
active_controller = None

# History of navigations.
# Elements are tuples (filename, line, col).
history = None

# navigation indicator, possible values are:
# - NAVIGATION_REQUESTED
# - NAVIGATION_DONE
flag = NAVIGATION_DONE

# rc utility switches to use for callback
switches = []

# File contents that has been passed to reindexer last time.
data = ''
last_references = []


def activate_view_controller(view):
    global active_controller
    global controllers

    view_id = view.id()

    if view_id not in controllers.keys():
        controllers[view_id] = vc.ViewController(view)

    if active_controller and active_controller.view.id() == view_id:
        log.debug("Viewcontroller for view-id {} is already active"
                  .format(view_id))
        return

    if active_controller:
        active_controller.deactivated()
    active_controller = controllers[view_id]
    active_controller.activated()


# Get the viewcontroller for the specified view.
def view_controller(view):
    global controllers

    if not view:
        return None
    view_id = view.id()
    if view_id not in controllers.keys():
        controllers[view_id] = vc.ViewController(view)
    return controllers[view_id]


def references():
    global last_references

    return last_references


def set_references(items):
    global last_references

    last_references = items


def add_reference(reference):
    global last_references

    last_references = [reference]


# Run a navigational transaction.
def navigate(view, oldfile, oldline, oldcol, file, line, col):
    add_reference("{}:{}:{}".format(oldfile, oldline, oldcol))

    push_history(oldfile, int(oldline) + 1, int(oldcol) + 1)

    return view.window().open_file(
        '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION)


# Prepare a navigational transaction.
def request_navigation(view, switches_, data_):
    global switches
    global data
    global flag

    switches = switches_
    data = data_
    flag = NAVIGATION_REQUESTED


def navigation_data():
    global data

    return data


def history_size():
    global history

    if not history:
        return 0

    return len(history)


def pop_history():
    global history

    if not history:
        return None

    return history.pop()


def push_history(file, line, col):
    global history

    if not history:
        history = collections.deque(
            [],
            maxlen=int(settings.get('jump_limit', 10)))

    history.append([file, line, col])


# Check if we are still in a navigation transaction.
def is_navigation_done():
    global flag

    return flag == NAVIGATION_DONE


# Finalize navigational transaction.
def navigation_done():
    global flag
    global switches

    flag = NAVIGATION_DONE
    switches = []


def unload():
    close_all()


def close(view):
    global controllers

    if not view.id() in controllers.keys():
        return
    controllers[view.id()].unload()
    del controllers[view.id()]


def close_all():
    global controllers

    for view_id in controllers.keys():
        controllers[view_id].unload()
    controllers = {}


def on_post_updated(view):
    # Reindex if we support fixits.
    if not view_controller(view).fixits.supported:
        log.debug("Fixits are disabled")
        # Run rc --check-reindex to reindex just saved files.
        # We do this manually even though rtags SHOULD watch
        # all our files and reindex accordingly. However on macOS
        # this feature is broken.
        # See https://github.com/Andersbakken/rtags/issues/1052
        jobs.JobsController.run_async(
            jobs.ReindexJob(
                "RTPostSaveReindex" + jobs.JobController.next_id(),
                view.file_name(),
                b'',
                view),
            indicator=view_controller(view).status.progress)
        return

    # For some bizarre reason, we need to delay our re-indexing task
    # by substantial amounts of time until we may relatively risk-
    # free will truly be attached to the lifetime of a
    # fully functioning `rc -V ... --wait`. `rc ... --wait` appears to
    # prevent concurrent instances by aborting the old "wait" when new
    # "wait"-request comes in.
    # sublime.set_timeout(lambda self=self,view=view: self._save(view), 400)
    # log.debug("Bizarrely delayed save scheduled")

    view_controller(view).idle.sleep()
    view_controller(view).fixits.reindex(saved=True)
