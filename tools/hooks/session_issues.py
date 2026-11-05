"""SessionStart hook: the repo's issues board is in context before the first word.

Michael, 2026-11-05: work in every repo is tracked on its GitHub issues
(catalogue rule "Work is tracked on the repo's GitHub issues"). The point is
that sessions running at the same time stay out of each other's files, so the
one thing a session must see before its first edit is what is already
claimed. This prints it.

A hook of its own rather than more lines under the brief: Claude Code keeps
about ten thousand characters of one hook's output and swaps the rest for a
preview, and the brief is held just under that.

Prints nothing outside a GitHub checkout. Always exits 0, and gives gh a few
seconds: a board that does not answer is one line saying so, never a session
that will not start.
"""
import json
import os
import re
import shutil
import subprocess
import sys

from _common import read_stdin_json, utf8_streams

MAX_LISTED = 15


def repo_of(cwd):
    """owner/name of the checkout's origin on GitHub, or None."""
    try:
        url = subprocess.run(["git", "-C", cwd, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=4).stdout.strip()
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def board_lines(repo, issues):
    """What the session is told, from the open issues gh answered with."""
    claimed = [i for i in issues
               if any(lab.get("name") == "in progress" for lab in i.get("labels") or [])]
    out = [f"THE ISSUES BOARD, {repo}. Work here starts from a GitHub issue claimed "
           "before the first edit (catalogue rule \"Work is tracked on the repo's "
           "GitHub issues\"): one issue per session in its own worktree, Part of #N "
           "in every commit, closed only when every Done when box is ticked. Work "
           "you find and were not asked to do becomes an issue."]
    if claimed:
        out.append("Claimed right now. Read each one's Where before touching its files:")
        for i in claimed[:MAX_LISTED]:
            who = ", ".join(a.get("login", "") for a in i.get("assignees") or []) or "nobody assigned"
            out.append(f"  #{i['number']} {i.get('title', '')[:90]} ({who})")
        if len(claimed) > MAX_LISTED:
            out.append(f"  and {len(claimed) - MAX_LISTED} more")
    else:
        out.append("Nothing is claimed right now.")
    more = "+" if len(issues) >= 100 else ""
    out.append(f"{len(issues)}{more} open in all: gh issue list -R {repo}")
    return out


def main():
    utf8_streams()
    cwd = read_stdin_json().get("cwd") or os.getcwd()
    repo = repo_of(cwd)
    if not repo:
        return 0
    gh = shutil.which("gh")
    if not gh:
        print(board_lines(repo, [])[0])
        print("gh is not on this machine, so what is claimed could not be listed. "
              f"https://api.github.com/repos/{repo}/issues?labels=in%20progress "
              "answers the same; check it before the first edit.")
        return 0
    try:
        res = subprocess.run([gh, "issue", "list", "-R", repo, "--state", "open",
                              "--limit", "100", "--json", "number,title,labels,assignees"],
                             capture_output=True, text=True, timeout=8)
        issues = json.loads(res.stdout or "[]") if res.returncode == 0 else None
        err = (res.stderr or "").strip()[:200]
    except Exception as exc:  # noqa: BLE001
        issues, err = None, str(exc)[:200]
    if issues is None:
        print(board_lines(repo, [])[0])
        print(f"The board could not be read ({err or 'no answer'}). Say so once, "
              "and look at what is claimed yourself before the first edit.")
        return 0
    print("\n".join(board_lines(repo, issues)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
