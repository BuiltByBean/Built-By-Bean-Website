"""SessionStart hook: the house rules are in context before the first word.

Whatever this prints, Claude Code adds to the session's context. So every
session on the machine starts already briefed by the live board, and
consulting the rules stops being a decision the session has to make. If
the bridge is not registered, or the board refuses the key, that is said
LOUDLY here instead of discovered three files in.

Always exits 0: a hook that fails at session start would only add noise,
and the words below are the whole point.
"""
import sys

from _common import utf8_streams, board_get, board_key


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
