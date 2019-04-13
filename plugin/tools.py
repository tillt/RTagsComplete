# -*- coding: utf-8 -*-

"""Tools.

Various helpers.

"""

from os import path

import logging

import html
import imp
import sys

PKG_NAME = path.basename(path.dirname(path.dirname(__file__)))

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


class Utilities:
    """Random utilities."""

    @staticmethod
    def html_escape(text):
        escaped = html.escape(text, False)
        escaped = escaped.replace('\n', "<br />")
        escaped = escaped.replace('\a', "<pre>")
        escaped = escaped.replace('\b', "</pre>")
        escaped = escaped.replace('\v', "<i>")
        escaped = escaped.replace('\f', "</i>")
        return escaped

    @staticmethod
    def file_content(file, line, column=1, length=0):
        """
        """
        text = ""

        with open(file) as in_file:
            file_lines = in_file.read().splitlines()

            if line > len(file_lines):
                log.error("Line index {} exceeds line count {}".format(line, len(file_lines)))
                return ""

            if column > len(file_lines[line - 1]):
                log.error("Column index {} exceeds line size {}".format(column, len(file_lines[line - 1])))
                return ""

            if length == 0 and column == 1:
                length = len(file_lines[line - 1])

            text = file_lines[line - 1][column - 1:column - 1 + length]

        return text

    @staticmethod
    def replace_in_file(old, new, file, target_map):
        """
        Replace 'old' with 'new' in 'file' at locations identified
        by 'target_map' dictionary { row => [col] }.
        """
        with open(file) as in_file:
            file_lines = in_file.read().splitlines()

            for row, cols in target_map.items():
                col_skew = 0

                for col in cols:
                    start = col_skew + col - 1

                    # We may have a leading '~' here.
                    # TODO(tillt): Is that really the only case where
                    # the reference location does not match the exact
                    # string position?
                    if file_lines[row - 1][start:start + 1] == "~":
                        start += 1
                        col_skew += 1

                    # Safety first, only replace matching symbols.
                    if file_lines[row - 1][start:start+len(old)] == old:
                        out_line = file_lines[row - 1][:start]
                        out_line += new
                        out_line += file_lines[row - 1][start + len(old):]

                        col_skew += len(new) - len(old)

                        file_lines[row - 1] = out_line
                    else:
                        log.error(
                            "Symbol name does not match,"
                            " skipping line {} column {} in file {}".format(
                                row,
                                col,
                                file))

        with open(file, 'w') as out_file:
            for line in file_lines:
                out_file.write("{}\n".format(line))
