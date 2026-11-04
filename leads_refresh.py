"""The lead list refreshes itself, once a week, inside the nightly job.

docs/automation_gaps.md item 17. `import_leads.py`, then `check_websites.py`,
then `enrich_sites.py` were run by hand, and nothing ran them, so the
"Started in the last 12 months" call list, which is the leads page's reason to
exist, aged without anybody seeing it.

cost-sync runs every day; this step is due when no night in the last
`EVERY_DAYS` days finished it, so a night that failed is retried the next
night rather than a week later. In order:

  1. the import, with no per-site email scrape (enrich_sites does that for
     new rows, better) and without Overture when DuckDB is not installed,
     which it is not on cost-sync (the import then keeps Overture's rows and
     marks and prunes nothing, see import_leads.run);
  2. the website check on rows never checked, which after the first run is
     the new rows, capped so one night cannot run for hours;
  3. the site read on the rows step 2 just checked.

Measured before it was added (2026-11-04): cost-sync peaks at about 0.4 GB and
idles the rest of the day, so a weekly import fits beside it.

    python leads_refresh.py            # run now if due
    LEADS_REFRESH_FORCE=1 python leads_refresh.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone

STEP_NAME = "leads refresh"
EVERY_DAYS = 6.5   # a little under seven, so the cron's own drift never skips a week
NOT_DUE = "not due"
CHECK_CAP = 800    # websites looked for in one night; the rest wait a week
READ_CAP = 400     # sites read in one night


def last_done(now=None):
    """When a night last finished this step, or None."""
    from models import NightRun
    now = now or datetime.now(timezone.utc)
    floor = now - timedelta(days=30)
    for run in (NightRun.query.filter(NightRun.started_at >= floor.replace(tzinfo=None))
                .order_by(NightRun.started_at.desc()).all()):
        for step in run.steps:
            if (step.get("name") == STEP_NAME and step.get("ok")
                    and not str(step.get("note", "")).startswith(NOT_DUE)):
                started = run.started_at
                return started if started.tzinfo else started.replace(tzinfo=timezone.utc)
    return None


def due(now=None):
    if os.environ.get("LEADS_REFRESH_FORCE") == "1":
        return True, None
    now = now or datetime.now(timezone.utc)
    last = last_done(now)
    if last is None:
        return True, None
    return (now - last) >= timedelta(days=EVERY_DAYS), last


def refresh(app):
    """Run the three passes. Returns one line for the night's record."""
    import import_leads
    import check_websites
    import enrich_sites

    began = datetime.now(timezone.utc)
    got = import_leads.run(enrich=False, app=app) or {}
    checked = check_websites.run(app=app, limit=CHECK_CAP) or {}
    read = enrich_sites.run(app=app, since=began, limit=READ_CAP) or {}
    line = (f"{got.get('made', 0)} new, {got.get('updated', 0)} updated, "
            f"{got.get('removed', 0)} removed, {got.get('total', 0)} on the list; "
            f"{checked.get('checked', 0)} sites looked for, {checked.get('found', 0)} found; "
            f"{read.get('read', 0)} read, +{read.get('email', 0)} emails "
            f"+{read.get('phone', 0)} phones +{read.get('people', 0)} people")
    if got.get("unread"):
        line += f"; not read: {', '.join(got['unread'])} (nothing pruned)"
    return line


def main(app=None):
    """The nightly step. Returns a summary string (night_log records it)."""
    if os.environ.get("LEADS_REFRESH_DISABLED") == "1":
        return f"{NOT_DUE}: switched off"
    if app is None:
        from app import create_app
        app = create_app()
    with app.app_context():
        is_due, last = due()
    if not is_due:
        return f"{NOT_DUE}: last ran {last:%Y-%m-%d}"
    return refresh(app)


if __name__ == "__main__":
    print(main())
    sys.exit(0)
