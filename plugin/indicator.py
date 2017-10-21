import sublime
import logging

from random import sample

from . import settings

log = logging.getLogger("RTags")


class ProgressIndicator():
    # Borrowed from EasyClangComplete.
    MSG_CHARS_COLOR_SUBLIME = u'⣾⣽⣻⢿⡿⣟⣯⣷'

    def __init__(self):
        self.size = 8
        self.view = None
        self.stopping = False
        self.is_active_callback = None
        self.indexing_done_callback = None
        self.running = False
        self.status_key = settings.SettingsManager.get('status_key', 'rtags_status_indicator')

    def start(self, view, active_callback, done_callback):
        if self.running:
            log.debug("Indicator already active")
            return
        log.debug("Starting indicator {} {}".format(active_callback, done_callback))
        self.view = view
        self.running = True
        self.active_callback = active_callback
        self.indexing_done_callback = done_callback
        sublime.set_timeout(lambda: self.run(1), 100)

    def stop(self):
        log.debug("Stopping indicator")
        self.stopping = True
        self.view = None

    def run(self, i):
        is_active = self.active_callback()

        if self.stopping or (not is_active):
            log.debug("round stopping {}, indexing {}".format(self.stopping, is_active))
            self.running = False
            self.stopping = False
            if self.view:
                self.view.erase_status(self.status_key)

            # Let the originator know that we are done.
            self.indexing_done_callback()
            return

        mod = len(ProgressIndicator.MSG_CHARS_COLOR_SUBLIME)
        rands = [ProgressIndicator.MSG_CHARS_COLOR_SUBLIME[x] for x in sample(range(mod), mod)]

        self.view.set_status(self.status_key, 'RTags {}'.format(''.join(rands)))

        sublime.set_timeout(lambda: self.run(i), 100)
