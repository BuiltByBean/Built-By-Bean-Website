"""SessionEnd hook: the session's time logs itself.

Audit item 3, 2026-11-04. Every transcript line carries a timestamp, so the
hours a session took are already on the machine: the stretches where no gap
was longer than fifteen minutes. This reads them as the session ends, finds
the repo it ran in from git, and posts both to /api/guidance/time with the
session id. The board decides the project, the rate, and whether the work is
Michael's own (which is never logged), and a second run for the same session
corrects the entry rather than adding one (session_time.py).

Skipped, with a line in ~/.claude/pm-guidance/session-time.log saying why:
no key, no transcript, nothing worth a minute, or a session that already
called log_time itself (it measured its own hours, and two entries for one
session would bill the hour twice).

Zero dependencies and Windows and Mac alike: the standard library and git.
Never raises and never prints to the session, which has ended.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (  # noqa: E402
    BOARD, board_key, marker_dir, read_stdin_json, transcript_lines, utf8_streams,
)

GAP = timedelta(minutes=15)
# Below this a session is a question asked and answered, not work to bill.
MIN_HOURS = 0.05
LOG_TIME_TOOL = "mcp__pm-guidance__log_time"


def _log(line):
    try:
        path = os.path.join(marker_dir(), "session-time.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} {line}\n")
    except Exception:  # noqa: BLE001
        pass


def _stamp(value):
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def read_session(lines):
    """(spans, first prompt, logged_itself) from the transcript's lines."""
    stamps, prompt, logged = [], "", False
    for raw in lines:
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        # A real call, not the name mentioned: a session working on these
        # hooks writes the tool's name a dozen times without calling it.
        content = (row.get("message") or {}).get("content")
        if row.get("type") == "assistant" and isinstance(content, list):
            if any(isinstance(part, dict) and part.get("type") == "tool_use"
                   and part.get("name") == LOG_TIME_TOOL for part in content):
                logged = True
        when = _stamp(row.get("timestamp"))
        if when is not None:
            stamps.append(when)
        if not prompt and row.get("type") == "user" and not row.get("isSidechain"):
            content = (row.get("message") or {}).get("content")
            if isinstance(content, list):
                content = " ".join(part.get("text", "") for part in content
                                   if isinstance(part, dict) and part.get("type") == "text")
            text = " ".join(str(content or "").split())
            if text and not text.startswith("<"):
                prompt = text[:160]
    stamps.sort()
    spans = []
    for when in stamps:
        if spans and when - spans[-1][1] <= GAP:
            spans[-1][1] = when
        else:
            spans.append([when, when])
    return [s for s in spans if s[1] > s[0]], prompt, logged


def _git(cwd, *args):
    try:
        out = subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                             text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001 - no git is an answer, not a crash
        return ""


def where(cwd):
    """(repo remote, folder name) for the folder the session ran in. A
    worktree answers with its main repo's remote and folder."""
    cwd = cwd or os.getcwd()
    remote = _git(cwd, "remote", "get-url", "origin")
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    top = os.path.dirname(common) if common.endswith(".git") else _git(cwd, "rev-parse", "--show-toplevel")
    folder = os.path.basename((top or cwd).rstrip("/\\"))
    return remote, folder


def post(body, key, timeout=8):
    req = urllib.request.Request(
        BOARD + "/api/guidance/time", data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "pm-guidance-hook/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace") or "{}"), None
    except urllib.error.HTTPError as err:
        return None, f"the board answered {err.code}"
    except Exception as err:  # noqa: BLE001
        return None, f"could not reach the board: {err}"


def build(data, lines):
    """The body to post, or (None, why not)."""
    spans, prompt, logged = read_session(lines)
    if logged:
        return None, "the session logged its own time"
    hours = sum((e - s).total_seconds() for s, e in spans) / 3600.0
    if hours < MIN_HOURS:
        return None, f"only {hours * 60:.0f} minutes of work"
    remote, folder = where(data.get("cwd"))
    last = spans[-1][1].astimezone()  # his own day, not UTC's
    return {
        "session_ref": str(data.get("session_id") or "")[:80],
        "repo": remote, "folder": folder,
        "spans": [[s.isoformat(), e.isoformat()] for s, e in spans],
        "date": last.date().isoformat(),
        "description": prompt or "Claude Code session",
        "source": "SessionEnd hook",
    }, None


def main():
    utf8_streams()
    data = read_stdin_json()
    sid = data.get("session_id") or "?"
    lines = transcript_lines(data.get("transcript_path") or "")
    if not lines:
        _log(f"{sid} skipped: no transcript")
        return 0
    body, why = build(data, lines)
    if body is None:
        _log(f"{sid} skipped: {why}")
        return 0
    key = board_key()
    if not key:
        _log(f"{sid} skipped: no PM_GUIDANCE_KEY on this machine")
        return 0
    answer, err = post(body, key)
    if err:
        _log(f"{sid} failed: {err}")
        return 0
    _log(f"{sid} {body['folder']}: {json.dumps(answer)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - the session is over; say it in the log
        _log(f"crashed: {exc}")
        sys.exit(0)
