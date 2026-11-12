from galcore.errors import IllegalTransition

TERMINAL = ("failed", "done", "cancelled")
IMPORT_FROM = ("ready_to_translate", "paused", "ready_to_apply")

_TABLE = {
    ("created", "path_resolved"): "detecting",
    ("detecting", "hit"): "extracting",
    ("detecting", "unknown"): "failed",
    ("detecting", "unselected"): "failed",
    ("extracting", "extracted"): "ready_to_translate",
    ("extracting", "extract_failed"): "failed",
    ("ready_to_translate", "start_translate"): "translating",
    ("ready_to_translate", "start_import"): "importing",
    ("ready_to_translate", "keep_source"): "ready_to_apply",
    ("translating", "pause"): "paused",
    ("translating", "no_pending"): "ready_to_apply",
    ("translating", "cancel"): "cancelled",
    ("paused", "resume"): "translating",
    ("paused", "start_import"): "importing",
    ("paused", "keep_source"): "ready_to_apply",
    ("ready_to_apply", "start_import"): "importing",
    ("ready_to_apply", "confirm_apply"): "applying",
    ("applying", "applied"): "verifying",
    ("verifying", "verified"): "done",
    ("verifying", "verify_failed"): "failed",
}


def transition(state, event, import_from=None):
    if state in TERMINAL:
        raise IllegalTransition(state, event)
    if state == "importing":
        return _leave_import(event, import_from)
    try:
        return _TABLE[(state, event)]
    except KeyError:
        raise IllegalTransition(state, event)


def _leave_import(event, import_from):
    if import_from not in IMPORT_FROM:
        raise IllegalTransition("importing", event)
    if event == "no_pending":
        return "ready_to_apply"
    if event == "rejected" and import_from == "ready_to_apply":
        return "ready_to_apply"
    if event in ("still_pending", "rejected") and import_from == "paused":
        return "paused"
    if event in ("still_pending", "rejected") and import_from == "ready_to_translate":
        return "ready_to_translate"
    if event == "still_pending" and import_from == "ready_to_apply":
        return "ready_to_apply"
    raise IllegalTransition("importing", event)
