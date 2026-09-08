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
# Recording work against a client. A commit means one of these is owed.
TIME_TOOLS = ("mcp__pm-guidance__log_time", "mcp__pm-guidance__log_expense")
# Consulting the catalogue before building. Owed BEFORE a feature is written,
# so the Stop hook looks for it across the whole transcript, not after a mark.
GUIDANCE_TOOL = "mcp__pm-guidance__get_feature_guidance"
# Reading a vendor's runbook before setting the vendor up.
PLAYBOOK_TOOL = "mcp__pm-guidance__get_playbook"


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


def _safe(session_id):
    return "".join(ch for ch in str(session_id or "unknown") if ch.isalnum() or ch in "-_")[:80]


def marker_path(session_id):
    return os.path.join(marker_dir(), f"lesson-pending-{_safe(session_id)}.json")


def vendors_path():
    """The board's playbook list, cached at session start so the PostToolUse
    hook can recognise a vendor without a network call per command."""
    return os.path.join(marker_dir(), "playbooks.json")


def work_marker_path(session_id):
    """Commits made this session. A separate file from the lesson marker so
    the two nudges cannot cancel each other out."""
    return os.path.join(marker_dir(), f"work-done-{_safe(session_id)}.json")


# ── which fixes need the MACHINE, and which do not ────────────────────
#
# Two kinds of gap, and only one of them is anybody's problem twice.
#
# A BOARD-side fix — a playbook trap, a rule, a feature's gold standard —
# is written once through suggest_update and is live for every machine and
# every session immediately, because the board is the one copy they all
# read. Nothing to install, nothing to remember, nothing to note.
#
# A MACHINE-side fix is not. The hooks, the standing order in
# ~/.claude/CLAUDE.md and the bridge registration live on each machine and
# travel only by pulling this repo and re-running the bootstrap. On
# 2026-09-04 a laptop had none of the three and nothing said so; the
# bootstrap fixed that machine, and nothing told the OTHER machine it was
# now behind.
#
# So: bump ECOSYSTEM_VERSION whenever a change here wants a bootstrap —
# any hook, the installer, or the standing order. The bootstrap stamps the
# number it installed, session_start compares the two, and a machine that
# is behind says so on every session until it is not.
#
# The one boundary, stated because it is real: this compares the CHECKOUT
# against what is installed FROM it. A checkout nobody has pulled cannot
# know a newer version exists — it is not stale from its own point of
# view. Keeping this repo pulled is the standing order's job; this is what
# catches the far more common half, where the pull happened and the
# bootstrap did not.

def ecosystem_version():
    """The tooling version in THIS checkout. 0 when the file predates the
    mechanism, which reads as "nothing to say" rather than as an error."""
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "ECOSYSTEM_VERSION")
        with open(path, encoding="utf-8") as fh:
            return int((fh.read() or "0").strip() or 0)
    except Exception:  # noqa: BLE001 - unreadable is 0, never a crash
        return 0


def installed_version_path():
    return os.path.join(marker_dir(), "ecosystem-installed")


def installed_version():
    """What the last bootstrap on this machine installed. 0 when it has
    never run, or ran before this mechanism existed — both of which mean
    the same thing to the caller: behind."""
    try:
        with open(installed_version_path(), encoding="utf-8") as fh:
            return int((fh.read() or "0").strip() or 0)
    except Exception:  # noqa: BLE001
        return 0


def stamp_installed_version(version):
    """Record what the bootstrap just installed. Only the installer calls
    this — a hook that stamped its own version would clear the very notice
    it exists to raise."""
    try:
        with open(installed_version_path(), "w", encoding="utf-8") as fh:
            fh.write(str(int(version)))
        return True
    except Exception:  # noqa: BLE001
        return False


def clear_installed_version():
    try:
        os.remove(installed_version_path())
    except OSError:
        pass


def transcript_lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except Exception:  # noqa: BLE001
        return []
