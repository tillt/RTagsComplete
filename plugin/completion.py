import logging

from . import settings


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
    for trigger in settings.SettingsManager.get('triggers'):
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
