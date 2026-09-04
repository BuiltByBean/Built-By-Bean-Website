"""Hold every repository against every signature in the catalogue. Nightly.

    python audit_repos.py

Cerebro, pointed outward. Data Dungeon's version made each landmine a
scanner over its own codebase; this runs the catalogue's scanners over
every client's codebase instead, so "which of my sites break this rule"
is a query and not a memory.

Two kinds of signature, one machine. A RULE's pattern is a violation: a
hit is something to fix. A PRODUCT's or a FEATURE's pattern is presence:
a hit is the thing being there, which is how a site that got texting
before the products catalogue existed still shows as having it. Both are
recorded per (repo, target) with the count and the first few hits.

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


# ── Signatures ───────────────────────────────────────────


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


def compile_signature(pattern, globs, exclude, unless=None):
    """(regex, globs, excludes, unless) or None when there is no pattern."""
    if not (pattern or "").strip():
        return None
    try:
        compiled = re.compile(pattern)
        unless_re = re.compile(unless) if (unless or "").strip() else None
    except re.error:
        return None
    return (compiled, _globs(globs) or ["**/*"], _globs(exclude), unless_re)


def compile_check(rule):
    """A rule's or feature's scanner, from its check_* fields."""
    return compile_signature(rule.check_pattern, rule.check_globs,
                             rule.check_exclude, rule.check_unless)


def compile_presence(product):
    """A product's signature, from its presence_* fields."""
    return compile_signature(product.presence_pattern, product.presence_globs,
                             product.presence_exclude)


def _scan(files, compiled):
    """{target.id: (hits, samples)} for [(target, signature)]."""
    results = {}
    for target, (pattern, globs, excludes, unless) in compiled:
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
        results[target.id] = (count, samples)
    return results


def scan(files, rules):
    """Rules and features, by their check_* fields."""
    return _scan(files, [(r, c) for r in rules if (c := compile_check(r))])


def scan_products(files, products):
    return _scan(files, [(p, c) for p in products if (c := compile_presence(p))])


def _health(items, signature_of, fixture_of):
    out = []
    for item in items:
        sig = signature_of(item)
        if sig is None:
            continue
        fixture = fixture_of(item) or ""
        if not fixture.strip():
            out.append((item, "NONE"))
            continue
        out.append((item, "PASS" if any(sig[0].search(l) for l in fixture.splitlines())
                    else "FAIL"))
    return out


def health(rules):
    """[(rule, status)] - PASS when the pattern fires on its own fixture,
    FAIL when it does not, NONE when there is no fixture to prove it."""
    return _health(rules, compile_check, lambda r: r.check_fixture)


def product_health(products):
    return _health(products, compile_presence, lambda p: p.presence_fixture)


def _proven(pairs, what):
    ok = []
    for item, status in pairs:
        if status in ("PASS", "NONE"):
            ok.append(item)
        else:
            print(f"  {what} for {item.slug} does not fire on its fixture - skipped")
    return ok


# ── The nightly run ──────────────────────────────────────


def audit(app, repos=None, fetch=None):
    """Returns {repo: {slug: hits}} across rules, features and products."""
    from models import db, Feature, Product, RuleAudit, ProductAudit
    fetch = fetch or fetch_tarball
    report = {}
    with app.app_context():
        checks = _proven(health(Feature.query.filter_by(is_active=True)
                                .filter(Feature.check_pattern.isnot(None)).all()), "scanner")
        products = _proven(product_health(Product.query.filter_by(is_active=True)
                                          .filter(Product.presence_pattern.isnot(None)).all()),
                           "signature")
        if not checks and not products:
            print("  nothing to run")
            return report
        repos = repos if repos is not None else sweep_repos.list_repos()
        now = datetime.now(timezone.utc)
        for full_name in repos:
            try:
                files, sha = fetch(full_name)
            except Exception as err:  # noqa: BLE001 - one repo never stops the rest
                print(f"  {full_name:40} FAILED  {str(err)[:120]}")
                continue
            summary = {}
            found = scan(files, checks)
            for rule in checks:
                count, samples = found.get(rule.id, (0, []))
                row = RuleAudit.query.filter_by(repo=full_name, rule_id=rule.id).first()
                if row is None:
                    row = RuleAudit(repo=full_name, rule_id=rule.id)
                    db.session.add(row)
                row.sha, row.violations = sha, count
                row.sample_json, row.checked_at = json.dumps(samples), now
                summary[rule.slug] = count
            seen = scan_products(files, products)
            for product in products:
                count, samples = seen.get(product.id, (0, []))
                row = ProductAudit.query.filter_by(repo=full_name, product_id=product.id).first()
                if row is None:
                    row = ProductAudit(repo=full_name, product_id=product.id)
                    db.session.add(row)
                row.sha, row.hits = sha, count
                row.sample_json, row.checked_at = json.dumps(samples), now
                summary["product:" + product.slug] = count
            db.session.commit()
            report[full_name] = summary
            broken = sum(1 for r in checks if r.kind == "rule" and summary.get(r.slug))
            present = sum(1 for p in products if summary.get("product:" + p.slug))
            print(f"  {full_name:40} {len(files):5} files, "
                  f"{broken} rule{'s' if broken != 1 else ''} broken, "
                  f"{present} product{'s' if present != 1 else ''} seen")
    return report


def main():
    from app import create_app
    app = create_app()
    report = audit(app)
    print(f"{len(report)} repos audited")
    return 0


if __name__ == "__main__":
    sys.exit(main())
