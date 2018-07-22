# -*- coding: utf-8 -*-

"""View Controller.

"""

import sublime
import logging

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

    def __init__(self):
        self.controllers = {}
        self.active_controller = None

    def activate_view_controller(self, view):
        view_id = view.id()
        if not view_id in self.controllers.keys():
            self.controllers[view_id] = ViewController(view)
        if self.active_controller:
            self.active_controller.deactivated()
        self.active_controller = self.controllers[view_id]
        self.active_controller.activated()

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

    def view_controller(self, view):
        view_id = view.id()
        if not view_id in self.controllers.keys():
            self.controllers[view_id] = ViewController(view)
        return self.controllers[view_id]
