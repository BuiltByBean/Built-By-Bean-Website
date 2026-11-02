"""Read every repo's CLAUDE.md and propose what is new in it. Run nightly.

    python sweep_repos.py

The other half of the loop. Sessions are told to file what they learn,
and the hooks now refuse to let one stop with an unfiled lesson - but a
lesson written straight into a repo's CLAUDE.md by hand, or by a session
on a machine without the hooks, would still be trapped in that repo. This
goes and gets it.

The CORE repos are read: every repo on the GitHub account with a push in
the last CORE_DAYS (120), because Best Practices is how Michael builds
NOW, and a repo nobody has touched since spring is not evidence of that.
A CLAUDE.md is split into its headed sections; any section that is new, or
whose body has changed since the last read, is filed through the same door
a session uses as a CANDIDATE for the nightly curator. Repo prose was
written for that repo, so it never rides into a build prompt as it stands:
the curator (curate_practices.py, run straight after this) writes a rule
for any project from it, folds it into one, or discards it. Nobody presses
anything. The first run of a repo only records what is there, so nothing
already mined by hand comes back as a duplicate, and a heading recorded
before bodies were fingerprinted is fingerprinted silently the first time.

Runs after the cost sync in the same nightly service. GITHUB_TOKEN on that
service lets it see private repos; without one it reads the public ones.
"""
import base64
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

GITHUB = "https://api.github.com"
OWNER = os.environ.get("GITHUB_OWNER", "BuiltByBean")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
_SLUG = re.compile(r"[^a-z0-9]+")
MIN_BODY = 120
MAX_BODY = 4000
CORE_DAYS = int(os.environ.get("CORE_DAYS", "120"))


def _get(path):
    headers = {"User-Agent": "pm-repo-sweeper/1.0",
               "Accept": "application/vnd.github+json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(GITHUB + path, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _recent(pushed_at, days=None):
    """Whether a repo was pushed to inside the core window."""
    if not pushed_at:
        return False
    try:
        when = datetime.fromisoformat(str(pushed_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    days = CORE_DAYS if days is None else days
    return when >= datetime.now(timezone.utc) - timedelta(days=days)


def list_repos(core_only=True):
    """The account's repos, full names, the core ones unless asked for all.
    Private ones need the token."""
    names = []
    page = 1
    while True:
        if TOKEN:
            rows = _get(f"/user/repos?per_page=100&affiliation=owner&page={page}")
        else:
            rows = _get(f"/users/{OWNER}/repos?per_page=100&page={page}")
        names.extend(r["full_name"] for r in rows
                     if not r.get("archived")
                     and (not core_only or _recent(r.get("pushed_at"))))
        if len(rows) < 100:
            break
        page += 1
    return names


def fetch_claude_md(full_name):
    """(sha, text) of the repo's CLAUDE.md, or (None, None) when it has none."""
    try:
        row = _get(f"/repos/{full_name}/contents/CLAUDE.md")
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None, None
        raise
    text = base64.b64decode(row.get("content") or "").decode("utf-8", "replace")
    return row.get("sha"), text


def slug(text):
    return _SLUG.sub("-", text.strip().lower()).strip("-")[:80]


def sections(text):
    """[(heading, body)] for every ## and ### heading, body up to the next."""
    out = []
    heading, body = None, []
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            if heading is not None:
                out.append((heading, "\n".join(body).strip()))
            heading, body = m.group(2), []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        out.append((heading, "\n".join(body).strip()))
    return out


def fingerprint(body):
    return hashlib.sha1(" ".join(body.split()).encode("utf-8")).hexdigest()[:16]


def _seen(watch):
    """{heading slug: body fingerprint}. Rows written before fingerprints
    hold a bare list of slugs, read as fingerprints not yet known."""
    raw = json.loads(watch.seen_json or "[]") if watch is not None else {}
    if isinstance(raw, list):
        return {k: None for k in raw}
    return dict(raw)


def _summary(body):
    first = " ".join(body.split())
    cut = first.find(". ")
    return (first[:cut + 1] if 0 < cut < 300 else first[:300]).strip()


def sweep(app, propose, repos=None, fetch=None):
    """Returns {repo: filed_count}. `propose` is the door's own function."""
    from models import db, RepoWatch
    repos = repos if repos is not None else list_repos()
    fetch = fetch or fetch_claude_md
    report = {}
    with app.app_context():
        for full_name in repos:
            try:
                sha, text = fetch(full_name)
            except Exception as err:  # noqa: BLE001 - one repo never stops the rest
                print(f"  {full_name:40} FAILED  {str(err)[:120]}")
                continue
            if text is None:
                continue
            watch = RepoWatch.query.filter_by(repo=full_name).first()
            if watch is not None and watch.last_sha == sha:
                continue
            found = sections(text)
            filed = 0
            baseline = watch is None
            seen = _seen(watch)
            if watch is None:
                watch = RepoWatch(repo=full_name, seen_json="{}")
                db.session.add(watch)
            now = {}
            for heading, body in found:
                key = slug(heading)
                if not key:
                    continue
                mark = fingerprint(body)
                now[key] = mark
                if baseline or len(body) < MIN_BODY:
                    continue
                if key in seen and seen[key] in (None, mark):
                    continue  # unchanged, or fingerprinted for the first time
                verb = "Changed in" if key in seen else "New in"
                result, status = propose(
                    kind="rule", slug="", field="*", mode="create", text="",
                    reason=f"{verb} the CLAUDE.md of {full_name}",
                    project=f"{full_name} (swept)",
                    payload={"name": heading[:160], "summary": _summary(body),
                             "what_went_wrong": body[:MAX_BODY],
                             "category": "platform",
                             "reference_project": full_name,
                             "path": "CLAUDE.md"},
                    hold=True)
                if status == 200 and result.get("action") == "candidate":
                    filed += 1
            # A heading that left the file stays remembered, so a section
            # moved back in later is not read as new.
            watch.seen_json = json.dumps({**seen, **now}, sort_keys=True)
            watch.last_sha = sha
            watch.last_swept_at = datetime.now(timezone.utc)
            watch.filed_count = (watch.filed_count or 0) + filed
            db.session.commit()
            report[full_name] = filed
            print(f"  {full_name:40} {'baseline' if baseline else 'ok':8} "
                  f"{len(found)} sections, {filed} filed")
    return report


def main():
    from app import create_app
    from pm.guidance_routes import _propose
    app = create_app()
    report = sweep(app, _propose)
    total = sum(report.values())
    print(f"{len(report)} core repos read, {total} note{'s' if total != 1 else ''} "
          "filed for the curator")
    return 0


if __name__ == "__main__":
    sys.exit(main())
