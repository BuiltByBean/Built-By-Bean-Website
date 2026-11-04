"""One record of every nightly run, written as each step finishes.

Until 2026-11-04 nothing recorded that cost-sync had run at all: each step
printed its failure to Railway's log, the job failed only when EVERY vendor
failed, and a broken night was found days later from a number that looked
wrong (docs/automation_gaps.md, item 1). Now each run is a `NightRun` with one
result per step, and Needs attention shows one row when a step failed or no
run has finished in 26 hours.

    night = Night(app)
    night.step("vendor costs", lambda: sync())   # returns a short summary
    night.finish()

A step's return value is its summary (a string or a count). A step that
raises is recorded as failed with the error, and the next step still runs.
The record itself never stops the job: if the database cannot be written, the
step still runs and the failure is printed as before.
"""
import time
import traceback
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc)


class Night:
    def __init__(self, app):
        self.app = app
        self.run_id = None
        self.steps = []
        try:
            from models import db, NightRun
            with app.app_context():
                run = NightRun(status="running", started_at=_now())
                db.session.add(run)
                db.session.commit()
                self.run_id = run.id
        except Exception as err:  # noqa: BLE001 - a missing table never stops the job
            print(f"night log unavailable: {str(err)[:160]}", flush=True)

    def _save(self, status=None):
        if self.run_id is None:
            return
        try:
            from models import db, NightRun
            with self.app.app_context():
                run = db.session.get(NightRun, self.run_id)
                run.steps = self.steps
                if status:
                    run.status = status
                    run.finished_at = _now()
                db.session.commit()
        except Exception as err:  # noqa: BLE001
            print(f"night log not written: {str(err)[:160]}", flush=True)

    def step(self, name, fn):
        """Run one step, record it, and return what it returned (None on
        failure)."""
        print(name, flush=True)
        began = time.monotonic()
        try:
            result = fn()
            ok, note = True, ("" if result is None else str(result))
        except Exception as err:  # noqa: BLE001 - one step never stops the next
            result, ok = None, False
            note = f"{type(err).__name__}: {err}"[:600]
            print(f"{name} failed: {note}", flush=True)
            traceback.print_exc()
        self.steps.append({"name": name, "ok": ok, "note": note[:600],
                           "seconds": round(time.monotonic() - began, 1)})
        self._save()
        return result

    def fail(self, name, note):
        """Record a step that did not raise but failed (e.g. every vendor)."""
        self.steps.append({"name": name, "ok": False, "note": str(note)[:600], "seconds": 0})
        self._save()

    def finish(self):
        failed = [s for s in self.steps if not s["ok"]]
        status = "ok" if not failed else ("failed" if len(failed) == len(self.steps) else "partial")
        self._save(status)
        return status
