# -*- coding: utf-8 -*-

"""Settings.

Settings manager.

"""

import sublime
import logging

from . import tools

from os import path

log = logging.getLogger("RTags")


PACKAGE_PATH = "Packages"
THEMES_PATH = "themes"
THEME_NAME = "Default"

setup = None
templates = None


def update_settings():
    global setup

    log.debug("Settings update")

    setup = sublime.load_settings('RTagsComplete.sublime-settings')


def update_templates():
    global templates

    log.debug("Templates update")

    # Init templates.
    templates = {}
    types = {
        "phantom": ["error", "warning", "fixit", "note"],
        "popup": ["error", "info"]
    }

    for key in types.keys():
        templates[key] = {}

        for name in types[key]:
            filepath = path.join(
                PACKAGE_PATH,
                tools.PKG_NAME,
                THEMES_PATH,
                THEME_NAME,
                "{}_{}.html".format(name, key))

            log.debug("load_binary_resource of {}".format(filepath))

            templates[key][name] = \
                sublime.load_binary_resource(filepath).decode('utf-8')


def update():
    global setup
    global templates

    setup = None
    templates = None


def template_as_html(category, typename, *args):
    global templates

    if not templates:
        update_templates()

    if typename not in templates.keys():
        return None
    if category not in templates[typename].keys():
        return None

    template = templates[typename][category]
    padded = template.replace('{', '{{').replace('}', '}}')
    substituted = padded.replace('[', '{').replace(']', '}')

    return substituted.format(*args)


def get(key, default=None):
    global setup

    if not setup:
        update_settings()

    value = setup.get(key, default)
    # log.debug("Setting {}={}".format(key, value))
    return value


def add_on_change(key):
    global setup

    log.debug("Settings watching {}".format(key))
    setup.add_on_change(key, update)
