"""Stop hook: a session does not end its turn with an unfiled lesson.

If a CLAUDE.md was edited this session and no report_lesson or
suggest_update call appears in the transcript after that edit, the stop
is refused (exit 2) and the reason goes back to Claude as feedback, so
it files the lesson and stops again. Refused at most twice per lesson,
and never when stop_hook_active is set, so a session that genuinely has
nothing to file is not held hostage.
"""
import json
import os
import sys

from _common import utf8_streams, LESSON_TOOLS, marker_path, read_stdin_json, transcript_lines

MAX_BLOCKS = 2


def main():
    utf8_streams()
    data = read_stdin_json()
    if data.get("stop_hook_active"):
        return 0
    path = marker_path(data.get("session_id"))
    if not os.path.exists(path):
        return 0
    try:
        with open(path, encoding="utf-8") as fh:
            marker = json.load(fh)
    except Exception:  # noqa: BLE001 - a broken marker is no marker
        os.remove(path)
        return 0

    lines = transcript_lines(data.get("transcript_path") or "")
    after = "\n".join(lines[int(marker.get("line") or 0):])
    if any(tool in after for tool in LESSON_TOOLS):
        os.remove(path)
        return 0

    blocks = int(marker.get("blocks") or 0)
    if blocks >= MAX_BLOCKS:
        os.remove(path)
        return 0
    marker["blocks"] = blocks + 1
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(marker, fh)

    sys.stderr.write(
        f"{marker.get('path') or 'A CLAUDE.md'} was edited this session and "
        "nothing was filed to the project manager. If that edit recorded a "
        "lesson, a landmine or a better way of doing something, call "
        "report_lesson (or suggest_update for a runbook, feature or rule "
        "change) now, then stop. If it was not a lesson, say so in one line "
        "and stop again.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
