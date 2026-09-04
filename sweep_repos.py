"""Read every repo's CLAUDE.md and propose what is new in it. Run nightly.

    python sweep_repos.py

The other half of the loop. Sessions are told to file what they learn,
and the hooks now refuse to let one stop with an unfiled lesson - but a
lesson written straight into a repo's CLAUDE.md by hand, or by a session
on a machine without the hooks, would still be trapped in that repo. This
goes and gets it.

Every repo on the GitHub account is read. A CLAUDE.md is split into its
headed sections; any heading the board has not seen for that repo before,
with enough body to be a lesson, is filed through the same door a session
uses - as a rule create, attributed to the repo, HELD as pending, because
repo prose was written for that repo and a create would otherwise ride
into every build prompt verbatim. One press on Needs attention accepts
it. The first run of a repo only records what is there, so nothing already
mined by hand comes back as a duplicate.

Runs after the cost sync in the same nightly service. GITHUB_TOKEN on that
service lets it see private repos; without one it reads the public ones.
"""
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

GITHUB = "https://api.github.com"
OWNER = os.environ.get("GITHUB_OWNER", "BuiltByBean")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
_SLUG = re.compile(r"[^a-z0-9]+")
MIN_BODY = 120
MAX_BODY = 4000


def _get(path):
    headers = {"User-Agent": "pm-repo-sweeper/1.0",
               "Accept": "application/vnd.github+json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(GITHUB + path, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_repos():
    """Every repo on the account, full names. Private ones need the token."""
    names = []
    page = 1
    while True:
        if TOKEN:
            rows = _get(f"/user/repos?per_page=100&affiliation=owner&page={page}")
        else:
            rows = _get(f"/users/{OWNER}/repos?per_page=100&page={page}")
        names.extend(r["full_name"] for r in rows if not r.get("archived"))
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
            slugs = {slug(h) for h, _ in found if slug(h)}
            filed = 0
            if watch is None:
                watch = RepoWatch(repo=full_name, seen_json="[]")
                db.session.add(watch)
                seen = set()
                baseline = True
            else:
                seen = set(json.loads(watch.seen_json or "[]"))
                baseline = False
            if not baseline:
                for heading, body in found:
                    key = slug(heading)
                    if not key or key in seen or len(body) < MIN_BODY:
                        continue
                    result, status = propose(
                        kind="rule", slug="", field="*", mode="create", text="",
                        reason=f"Found in the CLAUDE.md of {full_name}",
                        project=f"{full_name} (swept)",
                        payload={"name": heading[:160], "summary": _summary(body),
                                 "what_went_wrong": body[:MAX_BODY],
                                 "category": "platform",
                                 "reference_project": full_name,
                                 "path": "CLAUDE.md"},
                        hold=True)
                    if status == 200 and result.get("action") == "pending":
                        filed += 1
            watch.seen_json = json.dumps(sorted(seen | slugs))
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
    print(f"{len(report)} repos read, {total} lesson{'s' if total != 1 else ''} filed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
