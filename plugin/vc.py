# -*- coding: utf-8 -*-

"""View Controller.

"""

import sublime
import logging
import collections

from . import status
from . import fixits
from . import idle
from . import settings

from functools import partial

log = logging.getLogger("RTags")


class ViewController():

    def __init__(self, view):
        self.view = view
        self.status = status.StatusController(view)
        self.fixits = fixits.Controller(
            view,
            settings.SettingsManager.get('fixits'),
            self.status)
        self.idle = idle.Controller(
            view,
            settings.SettingsManager.get('auto_reindex'),
            5000.0,
            settings.SettingsManager.get('auto_reindex_threshold'),
            partial(fixits.Controller.reindex, self=self.fixits, saved=False))

    def activated(self):
        log.debug("Activating view-id {}".format(self.view.id()))
        self.idle.activated()
        self.fixits.activated()

    def deactivated(self):
        log.debug("Deactivating view-id {}".format(self.view.id()))
        self.idle.deactivated()
        self.fixits.deactivated()

    def close(self):
        self.status.unload()
        self.fixits.unload()
        self.idle.unload()

    def unload(self):
        self.status.unload()
        self.fixits.unload()
        self.idle.unload()


class VCManager():
    """ViewController manager singleton.
    Manages ViewControllers, attaching them to views.
    """

    NAVIGATION_REQUESTED = 1
    NAVIGATION_DONE = 2

    def __init__(self):
        self.controllers = {}
        self.active_controller = None
        # History of navigations.
        # Elements are tuples (filename, line, col).
        self.history = collections.deque()

        # navigation indicator, possible values are:
        # - NAVIGATION_REQUESTED
        # - NAVIGATION_DONE
        self.flag = VCManager.NAVIGATION_DONE
        # rc utility switches to use for callback
        self.switches = []
        # File contents that has been passed to reindexer last time.
        self.data = ''
        self.last_references = []

    def activate_view_controller(self, view):
        view_id = view.id()

        if view_id not in self.controllers.keys():
            self.controllers[view_id] = ViewController(view)

        if self.active_controller and self.active_controller.view.id() == view_id:
            log.debug("Viewcontroller for view-id {} is already active".format(view_id))
            return

        if self.active_controller:
            self.active_controller.deactivated()
        self.active_controller = self.controllers[view_id]
        self.active_controller.activated()

    # Get the viewcontroller for the specified view.
    def view_controller(self, view):
        if not view:
            return None
        view_id = view.id()
        if view_id not in self.controllers.keys():
            self.controllers[view_id] = ViewController(view)
        return self.controllers[view_id]

    def references(self):
        return self.last_references

    def set_references(self, items):
        self.last_references = items

    def add_reference(self, reference):
        self.last_references = [reference]

    # Run a navigational transaction.
    def navigate(self, view, oldfile, oldline, oldcol, file, line, col):
        self.add_reference("{}:{}:{}".format(oldfile, oldline, oldcol))

        self.push_history(oldfile, int(oldline) + 1, int(oldcol) + 1)

        return view.window().open_file(
            '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION)

    # Prepare a navigational transaction.
    def request_navigation(self, view, switches, data):
        self.switches = switches
        self.data = data
        self.flag = VCManager.NAVIGATION_REQUESTED

    def pop_history(self):
        return self.history.popleft()

    def navigation_data(self):
        return self.data

    def push_history(self, file, line, col):
        self.history.append([file, line, col])

        if len(self.history) > int(settings.SettingsManager.get('jump_limit', 10)):
            self.pop_history()

    # Check if we are still in a navigation transaction.
    def is_navigation_done(self):
        return self.flag == VCManager.NAVIGATION_DONE

    # Finalize navigational transaction.
    def navigation_done(self):
        self.flag = VCManager.NAVIGATION_DONE
        self.switches = []

    def unload(self):
        self.close_all()

    def close(self, view):
        if not view.id() in self.controllers.keys():
            return
        self.controllers[view.id()].unload()
        del self.controllers[view.id()]

    def close_all(self):
        for view_id in self.controllers.keys():
            self.controllers[view_id].unload()
        self.controllers = {}
