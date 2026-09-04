"""Hold every repository against every rule that can check itself. Nightly.

    python audit_repos.py

Cerebro, pointed outward. Data Dungeon's version made each landmine a
scanner over its own codebase; this runs the catalogue's scanners over
every client's codebase instead, so "which of my sites break this rule"
is a query and not a memory. Each rule that carries a check_pattern is
run over each repo's files; the count and the first few hits are kept
per (repo, rule), and the Cerebro page reads them.

The scanners are only as trustworthy as their fixtures. Before scanning
anything, every pattern is run against the line it claims to catch, and
one that does not fire is reported and skipped rather than silently
producing a clean bill of health.

Repos arrive as one tarball each, read in memory, never written to disk.
GITHUB_TOKEN on the service reaches the private ones.
"""
import fnmatch
import io
import json
import os
import re
import sys
import tarfile
import urllib.request
from datetime import datetime, timezone

import sweep_repos

MAX_FILE_BYTES = 400_000
MAX_SAMPLES = 12
ALWAYS_SKIP = ("node_modules/", ".git/", "dist/", "build/", ".venv/", "venv/",
               "__pycache__/", "static/vendor/", ".min.")


# ── Reading a repository ─────────────────────────────────


def fetch_tarball(full_name):
    """{relative path: text} for every text file in the repo, plus the
    short sha the tarball was cut at."""
    headers = {"User-Agent": "pm-rule-audit/1.0",
               "Accept": "application/vnd.github+json"}
    if sweep_repos.TOKEN:
        headers["Authorization"] = f"Bearer {sweep_repos.TOKEN}"
    req = urllib.request.Request(f"{sweep_repos.GITHUB}/repos/{full_name}/tarball",
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    files = {}
    sha = None
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar:
            if not member.isfile() or member.size > MAX_FILE_BYTES:
                continue
            top, _, rel = member.name.partition("/")
            if sha is None and "-" in top:
                sha = top.rsplit("-", 1)[-1]
            if not rel or any(skip in rel for skip in ALWAYS_SKIP):
                continue
            raw = tar.extractfile(member).read()
            try:
                files[rel] = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue  # binary, or not ours to read
    return files, sha


# ── Matching ─────────────────────────────────────────────


def _globs(text):
    return [g.strip() for g in (text or "").split(",") if g.strip()]


def path_matches(path, globs):
    """A small glob dialect: `**/` means any directory depth, and a glob
    with no `**/` is matched against the whole path."""
    for glob in globs:
        if "**/" in glob:
            prefix, tail = glob.split("**/", 1)
            if not path.startswith(prefix):
                continue
            rest = path[len(prefix):]
            if fnmatch.fnmatch(os.path.basename(rest), tail) or fnmatch.fnmatch(rest, tail):
                return True
        elif fnmatch.fnmatch(path, glob):
            return True
    return False


def compile_check(rule):
    """(regex, globs, excludes, unless) or None if the rule has no scanner."""
    if not (rule.check_pattern or "").strip():
        return None
    try:
        pattern = re.compile(rule.check_pattern)
        unless = re.compile(rule.check_unless) if (rule.check_unless or "").strip() else None
    except re.error:
        return None
    return (pattern, _globs(rule.check_globs) or ["**/*"],
            _globs(rule.check_exclude), unless)


def scan(files, rules):
    """{rule.id: (violations, samples)} over an already-read repo."""
    results = {}
    compiled = [(rule, compile_check(rule)) for rule in rules]
    compiled = [(r, c) for r, c in compiled if c]
    for rule, (pattern, globs, excludes, unless) in compiled:
        count = 0
        samples = []
        for path, text in files.items():
            if not path_matches(path, globs):
                continue
            if any(ex in path for ex in excludes):
                continue
            if unless is not None and unless.search(text):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    count += 1
                    if len(samples) < MAX_SAMPLES:
                        samples.append({"path": path, "line": number,
                                        "text": line.strip()[:160]})
        results[rule.id] = (count, samples)
    return results


def health(rules):
    """[(rule, status)] - PASS when the pattern fires on its own fixture,
    FAIL when it does not, NONE when the rule has no fixture to prove it."""
    out = []
    for rule in rules:
        check = compile_check(rule)
        if check is None:
            continue
        fixture = rule.check_fixture or ""
        if not fixture.strip():
            out.append((rule, "NONE"))
            continue
        pattern = check[0]
        out.append((rule, "PASS" if any(pattern.search(l) for l in fixture.splitlines())
                    else "FAIL"))
    return out


# ── The nightly run ──────────────────────────────────────


def audit(app, repos=None, fetch=None):
    """Returns {repo: {rule_slug: violations}}."""
    from models import db, Feature, RuleAudit
    fetch = fetch or fetch_tarball
    report = {}
    with app.app_context():
        rules = (Feature.query.filter_by(kind="rule", is_active=True)
                 .filter(Feature.check_pattern.isnot(None)).all())
        healthy = []
        for rule, status in health(rules):
            if status == "PASS" or status == "NONE":
                healthy.append(rule)
            else:
                print(f"  scanner for {rule.slug} does not fire on its fixture - skipped")
        if not healthy:
            print("  no scanners to run")
            return report
        repos = repos if repos is not None else sweep_repos.list_repos()
        now = datetime.now(timezone.utc)
        for full_name in repos:
            try:
                files, sha = fetch(full_name)
            except Exception as err:  # noqa: BLE001 - one repo never stops the rest
                print(f"  {full_name:40} FAILED  {str(err)[:120]}")
                continue
            results = scan(files, healthy)
            summary = {}
            for rule in healthy:
                count, samples = results.get(rule.id, (0, []))
                row = RuleAudit.query.filter_by(repo=full_name, rule_id=rule.id).first()
                if row is None:
                    row = RuleAudit(repo=full_name, rule_id=rule.id)
                    db.session.add(row)
                row.sha = sha
                row.violations = count
                row.sample_json = json.dumps(samples)
                row.checked_at = now
                summary[rule.slug] = count
            db.session.commit()
            report[full_name] = summary
            breaking = sum(1 for v in summary.values() if v)
            print(f"  {full_name:40} {len(files):5} files, "
                  f"{breaking} rule{'s' if breaking != 1 else ''} broken")
    return report


def main():
    from app import create_app
    app = create_app()
    report = audit(app)
    print(f"{len(report)} repos audited")
    return 0


if __name__ == "__main__":
    sys.exit(main())
