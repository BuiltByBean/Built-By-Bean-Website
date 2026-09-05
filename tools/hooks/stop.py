"""Stop hook: a session does not end its turn owing the project manager.

Two debts, checked in order of how badly they were being missed.

**An unfiled lesson.** If a CLAUDE.md was edited this session and no
report_lesson or suggest_update followed, the stop is refused and the
reason goes back to Claude as feedback. This has been here since the
beginning and it works.

**Unlogged work.** If commits were made and no log_time or log_expense
followed, say so once. This is new, and it is here because an audit of
the Robinson & Co. build — a whole new client, built end to end over two
days with the board live — found log_time called ZERO times. Nothing was
watching a commit, so nothing ever asked. The standing order said to log
time as it happens; prose does not survive four hours of building.

Both are refused at most twice, and never when stop_hook_active is set,
so a session that genuinely has nothing to file is not held hostage. The
lesson takes precedence: two demands at once is how a hook gets ignored.
"""
import json
import os
import sys

from _common import (
    utf8_streams, GUIDANCE_TOOL, LESSON_TOOLS, PLAYBOOK_TOOL, TIME_TOOLS,
    marker_path, read_stdin_json,
    transcript_lines, work_marker_path,
)

MAX_BLOCKS = 2


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001 - a broken marker is no marker
        try:
            os.remove(path)
        except OSError:
            pass
        return None


def _bump(path, marker):
    """Record one more refusal, or clear the marker once spent. Returns True
    when this stop should actually be refused."""
    blocks = int(marker.get("blocks") or 0)
    if blocks >= MAX_BLOCKS:
        os.remove(path)
        return False
    marker["blocks"] = blocks + 1
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(marker, fh)
    return True


def check_lesson(data, lines):
    path = marker_path(data.get("session_id"))
    if not os.path.exists(path):
        return 0
    marker = _load(path)
    if marker is None:
        return 0
    after = "\n".join(lines[int(marker.get("line") or 0):])
    if any(tool in after for tool in LESSON_TOOLS):
        os.remove(path)
        return 0
    if not _bump(path, marker):
        return 0
    sys.stderr.write(
        f"{marker.get('path') or 'A CLAUDE.md'} was edited this session and "
        "nothing was filed to the project manager. If that edit recorded a "
        "lesson, a landmine or a better way of doing something, call "
        "report_lesson (or suggest_update for a runbook, feature or rule "
        "change) now, then stop. If it was not a lesson, say so in one line "
        "and stop again.\n")
    return 2


def check_work(data, lines):
    path = work_marker_path(data.get("session_id"))
    if not os.path.exists(path):
        return 0
    marker = _load(path)
    if marker is None:
        return 0
    whole = "\n".join(lines)
    n = int(marker.get("commits") or 0)
    features = list(marker.get("features") or [])

    # All three look at the WHOLE transcript, not at what followed the mark.
    # Guidance and a runbook are owed BEFORE the thing that needs them, so
    # "after" would be wrong by construction. Time reads the same way for a
    # duller reason: a session that logs its hours and then keeps working
    # has engaged with the obligation, and nudging it again teaches it to
    # ignore the nudge. This is a floor, not an accountant.
    owes_time = n and not any(tool in whole for tool in TIME_TOOLS)
    owes_guidance = features and GUIDANCE_TOOL not in whole
    vendors = list(marker.get("vendors") or [])
    owes_playbook = vendors and PLAYBOOK_TOOL not in whole
    if not (owes_time or owes_guidance or owes_playbook):
        os.remove(path)
        return 0
    if not _bump(path, marker):
        return 0

    # One message, however many parts. Two separate nudges is how a hook
    # gets ignored.
    parts = []
    if owes_time:
        parts.append(
            f"{n} commit{'' if n == 1 else 's'} landed this session and no "
            "time was logged. If this was work on a client's project, call "
            "log_time with the client, the project, the hours and what was "
            "built — and log_expense for anything bought. Measure the hours "
            "rather than estimating them: the transcript has timestamps, and "
            "summing the gaps under fifteen minutes is closer than memory.")
    if owes_guidance:
        shown = ", ".join(features[:4]) + ("…" if len(features) > 4 else "")
        parts.append(
            f"{len(features)} feature module{'' if len(features) == 1 else 's'} "
            f"{'was' if len(features) == 1 else 'were'} written ({shown}) and "
            "get_feature_guidance was never called. "
            "The catalogue exists so a feature built before does not get "
            "re-derived, with its landmines, from scratch. If any of these is "
            "worth the next build knowing about, file it with report_lesson "
            "now.")
    if owes_playbook:
        parts.append(
            f"{', '.join(vendors)} {'was' if len(vendors) == 1 else 'were'} "
            "used this session and get_playbook was never called. Each of "
            "those has a runbook holding what only the client can do, the "
            "access to ask for, and the traps — the Robinson & Co. build lost "
            "an afternoon to a Railway config file that had been deprecated "
            "for a year and was silently ignored. If you learned anything "
            "about one of them today, file it.")
    parts.append(
        "If this was your own repo, a spike, or the board's own tooling, say "
        "so in one line and stop again.")
    sys.stderr.write("\n\n".join(parts) + "\n")
    return 2


def main():
    utf8_streams()
    data = read_stdin_json()
    if data.get("stop_hook_active"):
        return 0
    lines = transcript_lines(data.get("transcript_path") or "")
    # One demand at a time. Two at once is how a hook gets ignored.
    return check_lesson(data, lines) or check_work(data, lines)


if __name__ == "__main__":
    sys.exit(main())
