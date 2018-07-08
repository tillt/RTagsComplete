# -*- coding: utf-8 -*-

"""Tools.

Various helpers.

"""

from os import path

import logging

import sys
import imp


log = logging.getLogger("RTags")


class Reloader:
    """Reloader for all dependencies."""

    @staticmethod
    def reload_all():
        """Reload all loaded modules."""
        prefix = path.basename(path.dirname(path.dirname(__file__))) + '.plugin.'
        # reload all twice to make sure all dependencies are satisfied
        log.debug("Reload all modules first time for {}".format(prefix))
        Reloader.reload_once(prefix)
        log.debug("Reload all modules second time")
        Reloader.reload_once(prefix)
        log.debug("All modules reloaded")

    @staticmethod
    def reload_once(prefix):
        """Reload all modules once."""
        for name, module in sys.modules.items():
            if name.startswith(prefix):
                log.debug("Reloading module: '%s'", name)
                imp.reload(module)
