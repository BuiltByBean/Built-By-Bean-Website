"""PostToolUse hook on Edit and Write: notice a lesson being written down.

Every repo on this machine keeps its lessons in a CLAUDE.md, so an edit
to one is the reliable sign that something was learned. This records
where the transcript stood when it happened; the Stop hook checks whether
a report_lesson or suggest_update followed. It decides nothing itself.
"""
import json
import os
import sys

from _common import utf8_streams, marker_path, read_stdin_json, transcript_lines


def main():
    utf8_streams()
    data = read_stdin_json()
    file_path = str((data.get("tool_input") or {}).get("file_path") or "")
    if os.path.basename(file_path).lower() != "claude.md":
        return 0
    path = marker_path(data.get("session_id"))
    if os.path.exists(path):
        return 0  # the earliest edit is the one to measure from
    marker = {
        "line": len(transcript_lines(data.get("transcript_path") or "")),
        "path": file_path,
        "blocks": 0,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(marker, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
