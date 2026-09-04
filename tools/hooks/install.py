"""Put the three hooks into ~/.claude/settings.json, merging with whatever
is there. Run by the bootstrap; safe to run again - it replaces its own
entries and touches nothing else.

    python tools/hooks/install.py            install for this checkout
    python tools/hooks/install.py --remove   take them out
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = "tools/hooks/"  # every command we install carries this; nothing else does

EVENTS = {
    "SessionStart": (None, "session_start.py", 20),
    "PostToolUse": ("Edit|Write", "post_tool.py", 10),
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
    return 0


if __name__ == "__main__":
    sys.exit(main(remove="--remove" in sys.argv))
