"""SessionStart hook: the house rules are in context before the first word.

Whatever this prints, Claude Code adds to the session's context. So every
session on the machine starts already briefed by the live board, and
consulting the rules stops being a decision the session has to make. If
the bridge is not registered, or the board refuses the key, that is said
LOUDLY here instead of discovered three files in.

Always exits 0: a hook that fails at session start would only add noise,
and the words below are the whole point.
"""
import json
import sys

from _common import (
    utf8_streams, board_get, board_key, ecosystem_version, installed_version,
    vendors_path,
)


def pending_machine_updates():
    """Say so when this machine is behind the tooling it is running from.

    A board-side fix reaches every machine the moment it is filed, so it is
    never mentioned here. A MACHINE-side one — a hook, the installer, the
    standing order — travels only by pulling this repo and re-running the
    bootstrap, and until 2026-09-07 nothing anywhere said a machine had
    fallen behind. You found out by noticing the wrong behaviour.

    Prints rather than blocks, and keeps printing until the bootstrap
    clears it: this is a standing debt, not a one-off warning, and a
    warning shown once at the top of a long session is a warning nobody
    reads.
    """
    checkout, installed = ecosystem_version(), installed_version()
    if checkout <= installed:
        return
    print("=" * 66)
    print(f"THIS MACHINE HAS PENDING PM-ECOSYSTEM UPDATES — it last installed "
          f"v{installed}, and the Built-By-Bean-Website checkout it is running "
          f"from is v{checkout}. Something in the hooks, the installer or the "
          "standing order changed and has not been applied here yet, so this "
          "session is running older enforcement than the repo describes.")
    print()
    print("Tell the user, in their first reply, to run this from the "
          "Built-By-Bean-Website repo and then start a fresh session:")
    print()
    print("    .\\tools\\bootstrap_guidance.ps1 -Key <PM_GUIDANCE_KEY>")
    print()
    print("It is safe to re-run and takes a second. If they just pulled the "
          "repo, this is exactly the expected next step.")
    print("=" * 66)
    print()


def cache_vendors(key):
    """Write the board's playbook list to disk for the PostToolUse hook.

    Fetched once here rather than per command: the Stop hook wants to know
    whether a vendor was touched without its runbook being read, and a
    network call on every shell command would be intolerable. A failure is
    silent — the vendor check is a nicety and the brief is the point.
    """
    text, err = board_get("/api/guidance/playbooks", key)
    if err or not text:
        return
    try:
        rows = (json.loads(text) or {}).get("playbooks") or []
        slugs = {r["slug"]: r.get("name") or r["slug"] for r in rows if r.get("slug")}
    except Exception:  # noqa: BLE001
        return
    try:
        with open(vendors_path(), "w", encoding="utf-8") as fh:
            json.dump(slugs, fh)
    except Exception:  # noqa: BLE001
        pass


def main():
    utf8_streams()
    key = board_key()
    if not key:
        print("PM-GUIDANCE BRIDGE IS NOT REGISTERED ON THIS MACHINE. Nothing "
              "this session builds can consult the project manager or file "
              "lessons back. Before building anything, tell the user to run "
              "tools/bootstrap_guidance.ps1 -Key <key> in the "
              "Built-By-Bean-Website repo and start a fresh session.")
        return 0
    # Before the brief, not after it. A notice printed under two hundred
    # lines of house rules is a notice nobody reads.
    pending_machine_updates()
    cache_vendors(key)
    text, err = board_get("/api/guidance/brief", key)
    if err:
        print(f"PM-GUIDANCE: {err}. The rules brief could not be fetched at "
              "session start. Say so to the user before building anything; "
              "do not build from memory of the rules.")
        return 0
    print("HOUSE RULES FROM THE PROJECT MANAGER, fetched live at session "
          "start. Follow these over habit. The pm-guidance tools are in this "
          "session: get_feature_guidance before building a feature, "
          "get_playbook before a vendor, report_lesson or suggest_update the "
          "moment something is learned.")
    print()
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
