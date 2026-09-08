"""Put the three hooks into ~/.claude/settings.json, merging with whatever
is there. Run by the bootstrap; safe to run again - it replaces its own
entries and touches nothing else.

    python tools/hooks/install.py            install for this checkout
    python tools/hooks/install.py --remove   take them out
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (  # noqa: E402 - path has to be set first
    clear_installed_version, ecosystem_version, stamp_installed_version,
)

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = "tools/hooks/"  # every command we install carries this; nothing else does

EVENTS = {
    "SessionStart": (None, "session_start.py", 20),
    # Bash and PowerShell too, since 2026-09-05: a commit is the moment
    # work is owed to the board, and it arrives as a shell command.
    "PostToolUse": ("Edit|Write|Bash|PowerShell", "post_tool.py", 10),
    "Stop": (None, "stop.py", 10),
}


def _command(script):
    # Forward slashes: Python accepts them on Windows, and they survive
    # every shell and JSON layer this string passes through.
    path = os.path.join(HERE, script).replace("\\", "/")
    return f'python "{path}"'


def _ours(entry):
    return any(MARK in str(h.get("command", "")) for h in entry.get("hooks", []))


def main(remove=False):
    settings_path = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    settings = {}
    if os.path.exists(settings_path):
        with open(settings_path, encoding="utf-8") as fh:
            settings = json.load(fh)
    hooks = settings.setdefault("hooks", {})

    for event, (matcher, script, timeout) in EVENTS.items():
        kept = [e for e in hooks.get(event, []) if not _ours(e)]
        if not remove:
            entry = {"hooks": [{"type": "command", "command": _command(script),
                                "timeout": timeout}]}
            if matcher:
                entry["matcher"] = matcher
            kept.append(entry)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)

    with open(settings_path, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
    verb = "removed from" if remove else "installed in"
    print(f"hooks {verb} {settings_path}")
    if not remove:
        for event, (matcher, script, _) in EVENTS.items():
            print(f"  {event:13} {('on ' + matcher + ' ') if matcher else ''}-> {script}")

    # The stamp is what tells the NEXT session this machine is current. Written
    # only here: the installer is the one thing that actually applies a
    # machine-side change, so it is the only thing entitled to say it was
    # applied. A hook that stamped itself would clear the notice it exists to
    # raise, and the machine would look up to date for ever.
    if remove:
        clear_installed_version()
    else:
        version = ecosystem_version()
        if stamp_installed_version(version):
            print(f"  ecosystem     -> v{version} recorded for this machine")
    return 0


if __name__ == "__main__":
    sys.exit(main(remove="--remove" in sys.argv))
