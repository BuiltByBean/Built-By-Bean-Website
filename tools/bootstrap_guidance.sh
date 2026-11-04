#!/bin/sh
# One command puts a Mac on the loop. The twin of bootstrap_guidance.ps1.
#
# Three things have to exist on a machine for a session to consult Best
# Practices and file what it learns, and none of them travels with a repo: the
# standing order in ~/.claude/CLAUDE.md, the pm-guidance bridge registered at
# user scope with the board's key, and the hooks in ~/.claude/settings.json.
# On 2026-11-03 this Mac had none of them, so every MVP build prompt told a
# session to stop and say so, and the fix it named was a PowerShell script.
#
# Safe to run again. Unlike the Windows one it does NOT overwrite
# ~/.claude/CLAUDE.md: that file carries this machine's own standing rules, so
# the order goes between markers and only what is between them is ever replaced.
#
#     tools/bootstrap_guidance.sh            key read from Railway
#     tools/bootstrap_guidance.sh <key>      GUIDANCE_API_KEY, given
#
# The key is never printed. To take the hooks out again:
#     python3 tools/hooks/install.py --remove
set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python=$(command -v python3)

key=${1:-${PM_GUIDANCE_KEY:-}}
if [ -z "$key" ]; then
    key=$(cd "$repo" && railway variables --kv 2>/dev/null | sed -n 's/^GUIDANCE_API_KEY=//p')
fi
if [ -z "$key" ]; then
    echo "no key: pass GUIDANCE_API_KEY, or run where the Railway CLI is linked" >&2
    exit 1
fi

PM_KEY="$key" PM_REPO="$repo" PM_PYTHON="$python" "$python" - <<'PY'
import json, os, re, stat, tempfile

repo, python, key = os.environ["PM_REPO"], os.environ["PM_PYTHON"], os.environ["PM_KEY"]
home = os.path.expanduser("~")

# The standing order: between markers, and nothing else in the file moves.
BEGIN, END = "<!-- pm-guidance standing order -->", "<!-- /pm-guidance standing order -->"
target = os.path.join(home, ".claude", "CLAUDE.md")
os.makedirs(os.path.dirname(target), exist_ok=True)
order = open(os.path.join(repo, "tools", "STANDING_ORDER.md"), encoding="utf-8").read().strip()
block = f"{BEGIN}\n{order}\n{END}"
text = open(target, encoding="utf-8").read() if os.path.exists(target) else ""
if BEGIN in text and END in text:
    text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)
else:
    text = (text.rstrip() + "\n\n" if text.strip() else "") + block + "\n"
with open(target, "w", encoding="utf-8") as fh:
    fh.write(text)
print(f"standing order  -> {target}")

# The bridge, in the file Claude Code reads user-scoped servers from. Written
# whole to a temp file and renamed, because a half-written ~/.claude.json is
# every setting on the machine, and kept readable by this user alone.
path = os.path.join(home, ".claude.json")
config = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
config.setdefault("mcpServers", {})["pm-guidance"] = {
    "type": "stdio", "command": python,
    "args": [os.path.join(repo, "tools", "pm_guidance_mcp.py")],
    "env": {"PM_GUIDANCE_KEY": key},
}
fd, tmp = tempfile.mkstemp(dir=home, prefix=".claude.json.")
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    json.dump(config, fh, indent=2)
os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
os.replace(tmp, path)
print(f"bridge          -> registered at user scope in {path}")
PY

"$python" "$repo/tools/hooks/install.py"

# Ask the board, not the exit codes above: a registration that cannot reach it
# is not a registration.
PM_GUIDANCE_KEY="$key" "$python" - <<'PY'
import os, urllib.request
req = urllib.request.Request("https://builtbybeans.com/api/guidance/brief",
    headers={"Authorization": "Bearer " + os.environ["PM_GUIDANCE_KEY"],
             "User-Agent": "pm-guidance-bootstrap/1.0"})
with urllib.request.urlopen(req, timeout=20) as r:
    print(f"the board       -> answered {r.status}, brief of {len(r.read()):,} characters")
PY
echo "Start a fresh session: tools appear when a session starts, not during one."
