# -*- coding: utf-8 -*-

"""Completion.

Completion descision logic.

"""

import sublime

import logging

from . import jobs
from . import settings
from . import vc_manager

log = logging.getLogger("RTags")


class PositionStatus:
    """Enum class for position status.
    Taken from EasyClangComplete by Igor Bogoslavskyi

    Attributes:
        COMPLETION_NEEDED (int): completion needed
        COMPLETION_NOT_NEEDED (int): completion not needed
        WRONG_TRIGGER (int): trigger is wrong
    """
    COMPLETION_NEEDED = 0
    COMPLETION_NOT_NEEDED = 1
    WRONG_TRIGGER = 2


def position_status(point, view):
    """Check if the cursor focuses a valid trigger.

    Args:
        point (int): position of the cursor in the file as defined by subl
        view (sublime.View): current view

    Returns:
        PositionStatus: status for this position
    """
    trigger_length = 1

    word_on_the_left = view.substr(view.word(point - trigger_length))
    if word_on_the_left.isdigit():
        # don't autocomplete digits
        log.debug("Trying to auto-complete digit, are we? Not allowed")
        return PositionStatus.WRONG_TRIGGER

    # slightly counterintuitive `view.substr` returns ONE character
    # to the right of given point.
    curr_char = view.substr(point - trigger_length)
    wrong_trigger_found = False
    for trigger in settings.get('triggers'):
        # compare to the last char of a trigger
        if curr_char == trigger[-1]:
            trigger_length = len(trigger)
            prev_char = view.substr(point - trigger_length)
            if prev_char == trigger[0]:
                log.debug("Matched trigger '%s'", trigger)
                return PositionStatus.COMPLETION_NEEDED
            else:
                log.debug("Wrong trigger '%s%s'", prev_char, curr_char)
                wrong_trigger_found = True

    if wrong_trigger_found:
        # no correct trigger found, but a wrong one fired instead
        log.debug("Wrong trigger fired")
        return PositionStatus.WRONG_TRIGGER

    # if nothing fired we don't need to do anything
    log.debug("No completions needed")
    return PositionStatus.COMPLETION_NOT_NEEDED


query_suggestions = []
query_completion_job_id = None


def reset():
    global query_suggestions
    global query_completion_job_id
    query_suggestions = []
    query_completion_job_id = None


def query(view, prefix, locations):
    global query_suggestions
    global query_completion_job_id
    log.debug("Completion prefix: {}".format(prefix))

    # libclang does auto-complete _only_ at whitespace and
    # punctuation chars so "rewind" location to that character
    trigger_position = locations[0] - len(prefix)

    pos_status = position_status(trigger_position, view)

    if pos_status == PositionStatus.WRONG_TRIGGER:
        # We are at a wrong trigger, remove all completions from the list.
        log.debug("Wrong trigger - hiding default completions")
        return (
            [],
            sublime.INHIBIT_WORD_COMPLETIONS |
            sublime.INHIBIT_EXPLICIT_COMPLETIONS)

    if pos_status == PositionStatus.COMPLETION_NOT_NEEDED:
        log.debug("Completion not needed - showing default completions")
        return None

    # Render some unique identifier for us to match a completion request
    # to its original query.
    completion_job_id = "RTCompletionJob{}".format(trigger_position)

    # If we already have a completion for this position, show that.
    if query_completion_job_id == completion_job_id:
        log.debug("We already got a completion for this position")
        log.debug("completion: {}".format(query_suggestions))
        return (
            query_suggestions,
            sublime.INHIBIT_WORD_COMPLETIONS |
            sublime.INHIBIT_EXPLICIT_COMPLETIONS)

    # Cancel a completion that might be in flight.
    if query_completion_job_id:
        jobs.JobController.stop(query_completion_job_id)

    # We do need to trigger a new completion.
    log.debug("Completion job {} triggered on view {}".format(
        completion_job_id,
        view))

    query_view = view
    query_completion_job_id = completion_job_id
    query_trigger_position = trigger_position
    row, col = view.rowcol(trigger_position)

    text = bytes(view.substr(sublime.Region(0, view.size())), "utf-8")

    def completion_done(future):
        global query_suggestions
        log.debug("Completion done callback hit {}".format(future))

        if not future.done():
            log.warning("Completion failed")
            return

        if future.cancelled():
            log.warning(("Completion aborted"))
            return

        (completion_job_id, suggestions, error, view) = future.result()

        vc_manager.view_controller(view).status.update_status(error=error)

        if error:
            log.debug("Completion job {} failed: {}".format(
                completion_job_id,
                error.message))
            return

        log.debug("Finished completion job {} for view {}".format(
            completion_job_id,
            view))

        if view != query_view:
            log.debug("Completion done for different view")
            return

        # Did we have a different completion in mind?
        if completion_job_id != query_completion_job_id:
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

        if query_trigger_position not in valid_positions:
            log.debug("Trigger position {} does not match valid positions"
                      " {}".format(valid_positions, query_trigger_position))
            return

        query_suggestions = suggestions

        # Hide the completion we might currently see as those are sublime's
        # own completions which are not that useful to us C++ coders.
        #
        # This neat trick was borrowed from EasyClangComplete.
        view.run_command('hide_auto_complete')

        # Trigger a new completion event to show the freshly acquired ones.
        view.run_command(
            'auto_complete', {
                'disable_auto_insert': True,
                'api_completions_only': False,
                'next_completion_if_showing': False})

    jobs.JobController.run_async(
        jobs.CompletionJob(
            completion_job_id,
            view.file_name(),
            text,
            view.size(),
            row,
            col,
            view),
        completion_done,
        vc_manager.view_controller(view).status.progress)

    return (
        [],
        sublime.INHIBIT_WORD_COMPLETIONS |
        sublime.INHIBIT_EXPLICIT_COMPLETIONS)
