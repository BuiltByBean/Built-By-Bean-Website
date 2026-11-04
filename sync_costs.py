"""Pull each vendor's spend into the expense ledger. Run on a schedule.

    python sync_costs.py

Meant for a Railway cron service pointed at this repo, running daily. It is
safe to run as often as you like: every write is an upsert keyed on
(provider, resource, calendar month, mapping), so a second run in the same
month corrects the row the first one wrote instead of booking the cost twice.
That property is the whole reason this can be automated at all, and it is the
thing to protect if the sync is ever changed.

Run by the `cost-sync` service in the Built By Beans Website Railway project,
which points at this repo with a start command of `python sync_costs.py` and a
cron schedule of `0 13 * * *`.

Both live in that service's Deploy settings rather than in a file here. Railway
deprecated Config as Code on 2026-08-28 and refuses to let a service created
after that date opt in, so `railway.cron.json` was tried and removed. If the
schedule needs changing, it is in the dashboard, not in this repo.

**Railway cron is UTC.** `0 13 * * *` is 8am Central, not 1pm. A schedule
written in local time drifts an hour twice a year and nobody notices, because a
sync running at the wrong hour still produces correct numbers.

Railway forces the restart policy to Never for a cron service, which is what
you want: a finished run is a success, not a crash to retry.

Exits non-zero only when every active provider failed, which is the shape of a
real outage or a bad deploy. One provider failing is recorded against that
provider and reported here, but does not fail the run: a Twilio outage should
not throw away a month of Cloudflare charges.
"""
import sys

from app import create_app
from service_costs_service import sync_all_providers


def main():
    """The night, step by step, each recorded (night_log.Night). A step that
    fails is recorded and the next one still runs; the exit is non-zero only
    when every vendor sync failed, the shape of a real outage."""
    import night_log
    app = create_app()
    night = night_log.Night(app)
    outcome = {"failed_all": False}

    def vendors():
        with app.app_context():
            results = sync_all_providers()
        if not results:
            return "no active providers"
        failed = [name for name, _, error in results if error]
        for name, count, error in results:
            print(f"  {name:12} {'FAILED  ' + error[:160] if error else f'ok      {count} entries'}", flush=True)
        if failed and len(failed) == len(results):
            outcome["failed_all"] = True
        if failed:
            raise RuntimeError(f"{len(failed)}/{len(results)} vendors failed: {', '.join(failed)}")
        return f"{len(results)} vendors synced"

    night.step("vendor costs", vendors)
    # Not skipped when no vendor is active: the invoice import and everything
    # after it used to return early with the vendors (audit fault 7).
    night.step("Stripe invoices", lambda: _invoices(app))
    _sweep(night)
    night.finish()
    return 1 if outcome["failed_all"] else 0


def _invoices(app):
    """Pull Stripe's invoices into local rows, on the same nightly run.

    Client.total_revenue sums local rows, and a local row used to exist only
    for an invoice the board itself raised: the webhook dropped anything else
    on the floor. So a subscription invoice Stripe wrote on its own, or one
    raised in the dashboard, showed on the invoices page (which reads Stripe
    live) and nowhere else. Cason Kuper read Total Revenue $0.00 against
    $3,500 collected."""
    from stripe_service import import_invoices_from_stripe
    with app.app_context():
        made, updated, orphans = import_invoices_from_stripe()
    note = f"{made} new, {updated} updated"
    if orphans:
        note += f"; {len(orphans)} with no client here: {', '.join(orphans[:6])}"
    return note


def _sweep(night):
    """Everything after the money, in order. Each is its own step."""
    def run(module_name, label):
        def go():
            module = __import__(module_name)
            result = module.main()
            return None if result in (0, None) else result
        night.step(label, go)

    run("sweep_repos", "repo sweep")
    run("audit_repos", "rule audit")
    # A phone app's store ids are written in its repo; a tile missing one never
    # asks that store, so My Apps would say nothing about Play. No model.
    run("store_ids_service", "store ids")
    # Each company's own Stripe: its sales and its fees.
    run("stripe_books", "company Stripe books")
    # Each business's bank, after the vendor syncs so a line a vendor's sync
    # covers finds that vendor's expense already written.
    run("bank_feed", "bank feed")
    # Receipts after the bank, so tonight's settled charges can take theirs.
    run("receipts_service", "receipts")
    # Weekly, though asked every night: the lead list from the public record,
    # then websites and site reads for the new rows only. No model.
    run("leads_refresh", "leads refresh")
    # What the state says: franchise standing and report year, the permit
    # list, the quarterly local rates, and a return drafted from each
    # Comptroller charge. After the bank, so tonight's charges are in.
    run("comptroller", "Comptroller")
    # Last, because it reads what the sweep filed and what the audit found.
    # Off unless CURATOR_ENABLED (it is the paid step).
    run("curate_practices", "curator")


if __name__ == "__main__":
    sys.exit(main())
