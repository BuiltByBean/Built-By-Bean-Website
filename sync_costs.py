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
    app = create_app()
    with app.app_context():
        results = sync_all_providers()

    if not results:
        print("no active providers, nothing to sync")
        _sweep()
        return 0

    failed = 0
    for name, count, error in results:
        if error:
            failed += 1
            print(f"  {name:12} FAILED  {error[:160]}")
        else:
            print(f"  {name:12} ok      {count} cost entr{'y' if count == 1 else 'ies'}")

    print(f"{len(results) - failed}/{len(results)} providers synced")
    _sweep()
    return 1 if failed == len(results) else 0


def _sweep():
    """The other nightly job, on the same schedule, after the money. Its
    failure is reported and never turns a good cost sync into a bad exit."""
    try:
        import sweep_repos
        print("sweeping repos for new lessons", flush=True)
        sweep_repos.main()
        import audit_repos
        print("auditing repos against the rules", flush=True)
        audit_repos.main()
    except Exception as err:  # noqa: BLE001
        print(f"repo sweep failed: {str(err)[:200]}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
