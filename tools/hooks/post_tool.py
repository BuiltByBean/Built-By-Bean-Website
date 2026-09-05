"""PostToolUse hook: notice the moments that owe the project manager.

Until now this watched exactly one thing — an edit to a file named
CLAUDE.md — on the theory that a repo contract being written is the
reliable sign that something was learned. It is a good sign. It is also
the only one, and an audit of the Robinson & Co. build (a whole new
client, built end to end with the board live) showed what that misses:

  - log_time and log_expense were called ZERO times across a multi-day
    build for a paying client, because nothing watches a commit.
  - Two migration faults the catalogue already described in prose were
    hit twice each in one day, because nothing reads a generated file.

So this now watches three moments, and each one is chosen because it is
where the mistake actually happens rather than where somebody might
remember it later:

  1. **A CLAUDE.md written.** As before: a lesson is owed. Marked here,
     enforced at Stop.
  2. **A commit.** Work happened, so time is owed. Marked here, nudged
     once at Stop. Never blocks: an experiment is a commit too.
  3. **A migration generated.** Linted on the spot, because a migration
     is written by autogenerate rather than by anyone reading it, and
     the three faults below are all invisible until a deploy fails. This
     one speaks immediately (exit 2), since the file is already on disk
     and the fix takes ten seconds now and an afternoon later.

Never raises. A hook that crashes has said nothing, which is the one
thing it must not do.
"""
import json
import os
import re
import sys

from _common import (
    utf8_streams, marker_path, read_stdin_json, transcript_lines, work_marker_path,
)

# ── the migration linter ──────────────────────────────────────────────
#
# Three faults, each one already written down in the catalogue's
# "Migrations beside create_all", each one still shipped by hand more
# than once. A regex is not a review; these are the shapes that are
# unambiguous and cost a failed deploy.

MIGRATION_CHECKS = (
    (re.compile(r"\bmodels\.[A-Z][A-Za-z0-9_]*\("),
     re.compile(r"^\s*(import\s+models|from\s+models\s+import)", re.M),
     "names models.X but never imports models. Autogenerate writes a custom "
     "TypeDecorator by its dotted name and does not import it, so this dies "
     "with NameError the moment it runs. Add `import models` to "
     "migrations/script.py.mako so every future migration carries it."),

    (re.compile(r"create_(foreign_key|unique_constraint)\(\s*(None|['\"]\s*['\"])"),
     None,
     "creates an unnamed constraint. SQLite rebuilds a table in a batch to "
     "add one, and alembic refuses an anonymous constraint with "
     "\"Constraint must have a name\". Name it on the model: "
     "db.ForeignKey(..., name=\"fk_<table>_<column>\")."),

    (re.compile(r"add_column\((?![^\n]*server_default)[^\n]*nullable=False"),
     None,
     "adds a NOT NULL column with no server_default. It succeeds on an empty "
     "table and fails on a populated one, so local passes and production "
     "does not. Give the model a server_default and test against a "
     "populated database."),
)


def lint_migration(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except Exception:  # noqa: BLE001 - unreadable is not a finding
        return []
    found = []
    for pattern, unless, message in MIGRATION_CHECKS:
        if pattern.search(text) and not (unless and unless.search(text)):
            found.append(message)
    return found


def is_migration(path):
    p = path.replace("\\", "/").lower()
    return "/migrations/versions/" in p and p.endswith(".py")


# ── the markers ───────────────────────────────────────────────────────

def mark_lesson_owed(data, file_path):
    path = marker_path(data.get("session_id"))
    if os.path.exists(path):
        return  # the earliest edit is the one to measure from
    marker = {"line": len(transcript_lines(data.get("transcript_path") or "")),
              "path": file_path, "blocks": 0}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(marker, fh)


# Anything may sit between `git` and `commit` on one command: `-C <path>`,
# `-c key=value`, a global flag. Deliberately loose. A false positive costs
# one nudge the session dismisses in a line; a false negative costs the whole
# point of the hook, and `git -C <path> commit` is the form every worktree
# uses.
COMMIT = re.compile(r"\bgit\b[^\n;|&]*\bcommit\b")
# Reading about commits is not making one, and --amend re-writes work that
# was already counted.
HOUSEKEEPING = re.compile(
    r"--amend|--dry-run|"
    r"\bgit\b[^\n;|&]*\b(log|show|reflog|rev-list|rev-parse|describe|cherry|blame)\b",
    re.I)


# A feature module. Not every file in these directories — one that declares a
# blueprint or registers itself is a FEATURE, and a feature is the thing the
# catalogue has an opinion about. Robinson & Co. called get_feature_guidance
# four times while building thirty-odd of these.
FEATURE_DIR = re.compile(r"/(blueprints|routes|features|apps)/[a-z0-9_]+\.py$")
FEATURE_BODY = re.compile(r"\bBlueprint\(|\bregister\(\s*(bp|blueprint)\b|@app\.route")


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:  # noqa: BLE001
        return ""


def _work_marker(data):
    path = work_marker_path(data.get("session_id"))
    marker = {"commits": 0, "features": [], "blocks": 0,
              "line": len(transcript_lines(data.get("transcript_path") or ""))}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                marker.update(json.load(fh))
        except Exception:  # noqa: BLE001
            pass
    return path, marker


def _save(path, marker):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(marker, fh)


def mark_work_done(data, command):
    if not COMMIT.search(command) or HOUSEKEEPING.search(command):
        return
    path, marker = _work_marker(data)
    marker["commits"] = int(marker.get("commits") or 0) + 1
    _save(path, marker)


def mark_feature_built(data, file_path):
    """A feature module written. Recorded so the Stop hook can ask whether the
    catalogue was consulted before it — which is the whole point of having a
    catalogue, and the thing the Robinson & Co. audit found was skipped."""
    if not FEATURE_DIR.search(file_path.replace("\\", "/")):
        return
    if not FEATURE_BODY.search(_read(file_path)):
        return
    path, marker = _work_marker(data)
    name = os.path.basename(file_path)
    features = list(marker.get("features") or [])
    if name not in features:
        features.append(name)
    marker["features"] = features[:12]
    _save(path, marker)


def main():
    utf8_streams()
    data = read_stdin_json()
    tool_input = data.get("tool_input") or {}
    file_path = str(tool_input.get("file_path") or "")
    command = str(tool_input.get("command") or "")

    if command:
        mark_work_done(data, command)
        return 0

    if not file_path:
        return 0

    if os.path.basename(file_path).lower() == "claude.md":
        mark_lesson_owed(data, file_path)
        return 0

    mark_feature_built(data, file_path)

    if is_migration(file_path):
        problems = lint_migration(file_path)
        if problems:
            name = os.path.basename(file_path)
            sys.stderr.write(
                f"{name} was just written and has {len(problems)} known "
                "migration fault"
                f"{'' if len(problems) == 1 else 's'} in it. Every one of "
                "these is described in the catalogue's \"Migrations beside "
                "create_all\" and every one has still shipped by hand more "
                "than once, because a generated file is not read.\n\n"
                + "".join(f"  - It {p}\n\n" for p in problems)
                + "Fix the file before running it, and prefer the fix that "
                "stops it recurring over the one that patches this file.\n")
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
