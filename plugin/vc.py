# -*- coding: utf-8 -*-

"""View Controller.

"""

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
            settings.get('validation'),
            self.status)
        self.idle = idle.Controller(
            view,
            settings.get('auto_reindex'),
            5000.0,
            settings.get('auto_reindex_threshold'),
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
