"""The business map notices what the repos, Railway and the books say. Nightly.

docs/automation_gaps.md item 18. Surfaces were typed one by one, their status
was typed, and a vendor added in a repo reached the map only when Tend was
run. Five free checks, no model:

  1. A repo using a vendor its map lacks. Each playbook may carry a presence
     signature (Playbook.presence_*, the Product.presence_* mechanism reused,
     proven against its own fixture by audit_repos before it is trusted). The
     business's repos are its blueprints' source_repos.
  2. A surface from a Railway domain. A production service whose repo is the
     business's, or which already serves one of its surfaces, has its custom
     domains on the map; one that is not becomes a surface node.
  3. A vendor on the books but not on the map: the business's own expenses in
     the last year, named for a playbook, with no service node for it.
  4. A service with no charge in 90 days, from a vendor that has charged this
     business before: still running, or cancelled and still drawn?
  5. Surface status from the nightly site check (live_watch): live when it
     answers, Unreachable after two nights of not. Building and planned are
     Michael's words and are left alone, and outcome status stays Tend's.

Findings 1, 3 and 4 are filed as gaps on the business's blueprint (AppGap,
filed_by NIGHTLY), where Michael closes them as done or not wanted, and a
closed gap is never reopened. An open one whose cause has gone is closed as
done by the next run. A surface added from Railway leaves a closed gap behind
as its memory, so a node he deletes is not put back the next night.
"""
import re
from datetime import date, datetime, timedelta, timezone

NIGHTLY = "nightly map check"
BOOKS_WINDOW = timedelta(days=365)
QUIET_DAYS = 90
# What a vendor is called on a bank line when its runbook is named otherwise.
ALIASES = {
    "llm-apis": ("anthropic", "openai"),
    "app-store": ("apple developer", "apple.com/bill"),
    "google-play": ("google play", "google *play"),
    "aws": ("aws", "amazon web services"),
    "github": ("github",),
    "google-workspace-the-client-s-business-mailbox": ("google workspace", "gsuite"),
    "google-maps-platform-places-api-new": ("google maps", "google cloud"),
}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def vendor_words(playbook):
    words = list(ALIASES.get(playbook.slug, ()))
    name = (playbook.display_name or "").strip().lower()
    if name and playbook.slug not in ALIASES:
        words.append(name)
    return words


def names_vendor(text, playbook):
    text = (text or "").lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text) for w in vendor_words(playbook))


def on_map(business, playbook):
    """A service node for this vendor: by its runbook, or by its name."""
    for n in business.nodes:
        if n.kind != "service":
            continue
        if n.playbook_id == playbook.id or names_vendor(n.name, playbook):
            return True
    return False


def business_repos(business):
    import railway_watch
    from models import AppBlueprint
    repos, seen = [], set()
    for b in AppBlueprint.query.filter_by(business_id=business.id, is_active=True).all():
        for raw in (b.source_repos or "").split(","):
            key = railway_watch.norm_repo(raw)
            if key and key not in seen:
                seen.add(key)
                repos.append(raw.strip().removeprefix("https://github.com/").strip("/").removesuffix(".git"))
    return repos


def blueprint_of(business):
    from models import AppBlueprint
    return (AppBlueprint.query.filter_by(business_id=business.id, is_active=True)
            .order_by(AppBlueprint.sort_order, AppBlueprint.id).first())


def file_gap(blueprint, key, title, detail, status="open"):
    """Upsert a nightly gap. A closed row stays closed. Returns the row."""
    from models import db, AppGap
    row = AppGap.query.filter_by(blueprint_id=blueprint.id, key=key).first()
    if row is not None and row.status != "open":
        return row
    if row is None:
        row = AppGap(blueprint_id=blueprint.id, key=key, kind="gap")
        db.session.add(row)
    row.title, row.detail_md, row.filed_by = title[:200], detail[:8000], NIGHTLY
    if status != "open":
        row.status, row.decided_at = status, _now()
    return row


def close_gone(blueprint, live_keys):
    """Close as done every open nightly gap whose cause has gone."""
    from models import AppGap
    closed = 0
    for g in AppGap.query.filter_by(blueprint_id=blueprint.id, status="open", filed_by=NIGHTLY).all():
        if g.key not in live_keys:
            g.status, g.decided_at = "done", _now()
            closed += 1
    return closed


def vendors_in_repos(repos, fetch=None):
    """{playbook: [(repo, sample)]} for every proven signature that fires."""
    import audit_repos
    from models import Playbook
    fetch = fetch or audit_repos.fetch_tarball
    playbooks = audit_repos._proven(audit_repos.product_health(
        Playbook.query.filter_by(is_active=True).filter(Playbook.presence_pattern.isnot(None)).all()),
        "playbook signature")
    sigs = [(p, c) for p in playbooks if (c := audit_repos.compile_presence(p))]
    found = {}
    for repo in repos:
        try:
            files, _ = fetch(repo)
        except Exception as err:  # noqa: BLE001 - one repo never stops the rest
            print(f"map checks: {repo}: {str(err)[:120]}", flush=True)
            continue
        for pid, (count, samples) in audit_repos._scan(files, sigs).items():
            if count:
                p = next(p for p, _ in sigs if p.id == pid)
                found.setdefault(p, []).append((repo, samples[0] if samples else None))
    return found


def books_by_vendor(business, today):
    """{playbook: [expense dates]} for the business's own expenses in the
    last year that name a playbook's vendor."""
    from models import Expense, Playbook
    since = today - BOOKS_WINDOW
    expenses = Expense.query.filter(Expense.business_id == business.id, Expense.date >= since).all()
    out = {}
    for p in Playbook.query.filter_by(is_active=True).all():
        dates = [e.date for e in expenses if e.amount and names_vendor(e.description, p)]
        if dates:
            out[p] = dates
    return out


def railway_surfaces(business, repos, services):
    """Custom domains of the business's production services that no surface
    on its map has. [(domain, service)]."""
    import railway_watch
    hosts = {railway_watch.host_of(n.url) for n in business.nodes if n.url}
    hosts.discard("")
    out, seen = [], set()
    for s in services:
        if s.environment != "production" or s.is_database or s.ignored:
            continue
        mine = (railway_watch.norm_repo(s.repo) in {railway_watch.norm_repo(r) for r in repos}
                or any(d in hosts for d in s.domains))
        if not mine:
            continue
        for d in s.custom_domains:
            h = d[4:] if d.startswith("www.") else d
            if h not in hosts and h not in seen:
                seen.add(h)
                out.append((h, s))
    return out


def surface_status(business):
    """Set each surface's status from its site check. Returns how many moved."""
    import railway_watch
    from models import SiteCheck
    by_url = {c.url.rstrip("/").lower(): c for c in SiteCheck.query.all()}
    by_host = {}
    for c in by_url.values():
        by_host.setdefault(c.host, c)
    moved = 0
    for n in business.nodes:
        if n.kind != "surface" or not n.url or n.status not in ("", None, "live", "down"):
            continue
        c = by_url.get(n.url.rstrip("/").lower()) or by_host.get(railway_watch.host_of(n.url))
        if c is None or c.ok is None:
            continue
        want = "live" if c.ok else ("down" if c.fail_nights >= 2 else n.status)
        if want and want != n.status:
            n.status = want
            moved += 1
    return moved


def check_business(business, services, today, fetch=None):
    """All five checks for one business. Returns a dict of counts."""
    from models import db, BusinessNode
    counts = {"gaps": 0, "surfaces": 0, "status": 0, "closed": 0}
    counts["status"] = surface_status(business)
    blueprint = blueprint_of(business)
    if blueprint is None:
        db.session.commit()
        counts["no_blueprint"] = 1
        return counts
    repos = business_repos(business)
    live = set()

    import vendor_discovery
    for p, hits in vendors_in_repos(repos, fetch).items():
        # The Vendors page lists what the code uses (Michael, 2026-11-05).
        vendor_discovery.note_code(p, business, [repo for repo, _ in hits])
        if on_map(business, p):
            continue
        key = f"map-repo-{p.slug}"[:120]
        where = "; ".join(f"{repo}" + (f" ({s['path']}:{s['line']})" if s else "") for repo, s in hits[:3])
        file_gap(blueprint, key, f"{p.display_name} is in the code but not on the map",
                 f"The code uses {p.display_name}: {where}. Add it to the map as a service, "
                 f"or close this as not wanted.")
        live.add(key)

    books = books_by_vendor(business, today)
    for p, dates in books.items():
        if on_map(business, p):
            continue
        key = f"map-books-{p.slug}"[:120]
        file_gap(blueprint, key, f"{p.display_name} is on the books but not on the map",
                 f"{len(dates)} charge{'s' if len(dates) != 1 else ''} from {p.display_name} in the "
                 f"last year, the latest on {max(dates):%b} {max(dates).day}, {max(dates).year}.")
        live.add(key)

    from models import Expense, Playbook
    for n in business.nodes:
        if n.kind != "service" or n.playbook_id is None:
            continue
        p = db.session.get(Playbook, n.playbook_id)
        if p is None:
            continue
        ever = [e.date for e in Expense.query.filter(Expense.business_id == business.id).all()
                if e.amount and names_vendor(e.description, p)]
        if ever and max(ever) < today - timedelta(days=QUIET_DAYS):
            key = f"map-quiet-{p.slug}"[:120]
            file_gap(blueprint, key, f"No charge from {p.display_name} in {QUIET_DAYS} days",
                     f"The last was on {max(ever):%b} {max(ever).day}, {max(ever).year}. Still running, "
                     f"or cancelled and still on the map?")
            live.add(key)

    for domain, s in railway_surfaces(business, repos, services):
        key = f"map-surface-{domain}"[:120]
        from models import AppGap
        if AppGap.query.filter_by(blueprint_id=blueprint.id, key=key).first():
            continue  # added once already; a deleted node stays deleted
        db.session.add(BusinessNode(
            business_id=business.id, kind="surface", name=domain, url=f"https://{domain}",
            surface_kind="site", status="live",
            notes=f"Added from Railway ({s.project_name} / {s.service_name}) on {today.isoformat()}"))
        file_gap(blueprint, key, f"{domain} added to the map from Railway",
                 f"Served by {s.project_name} / {s.service_name}.", status="done")
        counts["surfaces"] += 1

    counts["gaps"] = len(live)
    counts["closed"] = close_gone(blueprint, live)
    db.session.commit()
    return counts


def run(fetch=None, today=None):
    from models import Business, RailwayService
    today = today or date.today()
    services = RailwayService.query.all()
    total = {"gaps": 0, "surfaces": 0, "status": 0, "closed": 0, "no_blueprint": 0}
    maps = 0
    for b in Business.query.order_by(Business.id).all():
        if not b.nodes:
            continue
        maps += 1
        for k, v in check_business(b, services, today, fetch).items():
            total[k] = total.get(k, 0) + v
    note = (f"{maps} maps: {total['gaps']} open gaps, {total['surfaces']} surfaces added, "
            f"{total['status']} statuses set, {total['closed']} gaps closed")
    if total["no_blueprint"]:
        note += f", {total['no_blueprint']} with no blueprint to file against"
    return note
