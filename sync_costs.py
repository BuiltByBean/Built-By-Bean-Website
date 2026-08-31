"""Pull each vendor's spend into the expense ledger. Run on a schedule.

    python sync_costs.py

Meant for a Railway cron service pointed at this repo, running daily. It is
safe to run as often as you like: every write is an upsert keyed on
(provider, resource, calendar month, mapping), so a second run in the same
month corrects the row the first one wrote instead of booking the cost twice.
That property is the whole reason this can be automated at all, and it is the
thing to protect if the sync is ever changed.

The schedule lives in `railway.cron.json`, which the cron service reads instead
of the default `railway.json` so the web service is unaffected by it. It is set
to `0 13 * * *`, and **Railway cron is UTC**: that is 8am Central, not 1pm. A
schedule written in local time here would drift by an hour twice a year and
nobody would notice, because a sync running at the wrong hour still produces
correct numbers.

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
        return 0

    failed = 0
    for name, count, error in results:
        if error:
            failed += 1
            print(f"  {name:12} FAILED  {error[:160]}")
        else:
            print(f"  {name:12} ok      {count} cost entr{'y' if count == 1 else 'ies'}")

    print(f"{len(results) - failed}/{len(results)} providers synced")
    return 1 if failed == len(results) else 0


if __name__ == "__main__":
    sys.exit(main())
