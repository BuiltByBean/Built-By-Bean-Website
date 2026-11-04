"""The live apps half of the nightly job, each its own recorded step.

Called once from sync_costs._sweep, after the receipts, so the Railway read
comes before everything that leans on it and the mail-read Railway bills see
tonight's receipts. Every step goes through night.step (night_log.py), so a
failure is one row on Needs attention and the next step still runs.
"""


def steps(night):
    app = night.app

    def ctx(fn):
        def go():
            with app.app_context():
                return fn()
        return go

    import railway_watch
    import live_watch
    import store_versions_service
    import tile_upkeep
    import map_checks
    import step_checks
    import railway_mail

    def sites():
        up, down = live_watch.check_sites()
        domains = live_watch.check_domains()
        return f"{up} up, {down} down, {domains} domains"

    # Railway first: the tiles, the map and the step checks read what it saw.
    night.step("Railway services", ctx(railway_watch.run))
    night.step("site checks", ctx(sites))
    night.step("store versions", ctx(store_versions_service.refresh_all))
    night.step("tile text and icons", ctx(tile_upkeep.run))
    night.step("map checks", ctx(map_checks.run))
    night.step("playbook step checks", ctx(step_checks.run))
    night.step("Railway bills from mail", ctx(railway_mail.run))
