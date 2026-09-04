"""Shared by the three hooks. Zero dependencies, like the bridge.

The key is read from the bridge's own registration in ~/.claude.json, so
there is one copy of it on a machine and the bootstrap is the only thing
that ever writes it. PM_GUIDANCE_KEY in the environment wins if set.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BOARD = os.environ.get("PM_GUIDANCE_URL", "https://builtbybeans.com").rstrip("/")
LESSON_TOOLS = ("mcp__pm-guidance__report_lesson", "mcp__pm-guidance__suggest_update")


def utf8_streams():
    """Windows gives a hook a cp1252 stdout, and the brief is UTF-8: one
    minus sign in a rule and the whole injection died after its header.
    Every hook calls this first. Replace, never raise: a hook that
    crashes has said nothing, which is the one thing it must not do."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def board_key():
    key = os.environ.get("PM_GUIDANCE_KEY", "")
    if key:
        return key
    try:
        with open(os.path.expanduser("~/.claude.json"), encoding="utf-8") as fh:
            config = json.load(fh)
        server = (config.get("mcpServers") or {}).get("pm-guidance") or {}
        return (server.get("env") or {}).get("PM_GUIDANCE_KEY", "") or ""
    except Exception:  # noqa: BLE001 - no config is the answer, not a crash
        return ""


def board_get(path, key, timeout=8):
    """(text, error). Never raises."""
    req = urllib.request.Request(
        BOARD + path,
        headers={"Authorization": f"Bearer {key}",
                 "User-Agent": "pm-guidance-hook/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as err:
        return None, f"the board answered {err.code}"
    except Exception as err:  # noqa: BLE001
        return None, f"could not reach the board: {err}"


def read_stdin_json():
    try:
        return json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}


def marker_dir():
    path = os.path.join(os.path.expanduser("~"), ".claude", "pm-guidance")
    os.makedirs(path, exist_ok=True)
    return path


def marker_path(session_id):
    safe = "".join(ch for ch in str(session_id or "unknown") if ch.isalnum() or ch in "-_")[:80]
    return os.path.join(marker_dir(), f"lesson-pending-{safe}.json")


def transcript_lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except Exception:  # noqa: BLE001
        return []
