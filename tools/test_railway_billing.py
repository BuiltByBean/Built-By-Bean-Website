# -*- coding: utf-8 -*-
"""Railway's bills pull themselves, and EntertainHQ's Railway is EntertainHQ's.

Until 2026-11-01 every Railway month was typed in by hand, because the board
believed Railway's API would not report money. It does, to an account token:
`workspace.customer.invoices` and `usage` grouped by project. Michael that
day: "I have a separate pro account for entertainhq specifically on railway
now", one login with two workspaces, and EntertainHQ LLC pays for its own.
This boots the board on a throwaway SQLite database, fakes Railway's API in
the shapes it really answered with, and proves:

  1. The migration points the existing provider at Built by Bean's workspace,
     adds "Railway (EntertainHQ)" owned by the EntertainHQ business, records
     September and October, and leaves a hand-typed month alone.
  2. A pull records each FINISHED bill under the month its period starts,
     never a period still running, never a bill typed by hand, and corrects
     only rows it wrote itself.
  3. Each month's bill is split across its projects by usage, to the cent,
     with expenses that add up to the bill; a deleted project keeps a name;
     a month already broken down by hand is left alone.
  4. EntertainHQ's account writes cost entries and no expense, and takes the
     mapping its project already had under Built by Bean's account.
  5. A token that cannot read billing says what token to make.
  6. Needs attention gives a pulled account a month's grace, because
     EntertainHQ's bill runs 16th to 16th; a typed-in account is asked as before.
  7. The hosting page's all-time Railway figure is Built by Bean's account only.
  8. The provider form keeps the workspace and pulls the bills on Save.

Run: python tools/test_railway_billing.py
"""
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-railway-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, Business, Client, Expense, Project, ProviderInvoice, ServiceCostEntry,  # noqa: E402
                    ServiceMapping, ServiceProvider, User)
import service_costs_service as scs  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []
BBB_WS, EHQ_WS = "74c67a5d-b5a5-49dc-aa39-36f378ddc9f8", "edde8aea-147d-4851-9b62-f4d068ad2066"
P_SITE, P_KUPER, P_GONE, P_EHQ = "p-site-0001", "p-kuper-0002", "p-gone-00003", "p-ehq-00004"


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def inv(start, end, cents, status="paid"):
    return {"invoiceId": f"in_{start}_{cents}", "periodStart": f"{start}T00:00:00.000Z",
            "periodEnd": f"{end}T00:00:00.000Z", "total": cents, "status": status}


WORKSPACES = {
    BBB_WS: {"name": "builtbybean's Projects",
             "projects": [(P_SITE, "Built By Beans Website"), (P_KUPER, "Kuper Plumbing"), (P_EHQ, "EntertainHQ")],
             "invoices": [inv("2026-08-01", "2026-09-01", 4070), inv("2026-09-01", "2026-10-01", 4371),
                          inv("2026-10-01", "2026-11-01", 5238), inv("2026-11-01", "2099-12-01", 107, "open"),
                          inv("2026-07-01", "2026-08-01", 2145), inv("2026-06-01", "2026-07-01", 999, "void")]},
    EHQ_WS: {"name": "EntertainHQ", "projects": [(P_EHQ, "EntertainHQ")],
             "invoices": [inv("2026-09-16", "2026-10-16", 2132), inv("2026-09-16", "2026-09-17", 1583),
                          inv("2026-09-16", "2026-09-16", 533), inv("2026-10-16", "2099-11-16", 731, "open")]},
}
# vCPU-minutes, GB-minutes and GB, as Railway's usage query reports them.
USAGE = {
    BBB_WS: {P_SITE: {"MEMORY_USAGE_GB": 10021.6, "CPU_USAGE": 13.1, "DISK_USAGE_GB": 37438.9, "NETWORK_TX_GB": 0.96},
             P_KUPER: {"MEMORY_USAGE_GB": 30064.8, "CPU_USAGE": 40.0, "DISK_USAGE_GB": 0, "NETWORK_TX_GB": 2.0},
             P_GONE: {"MEMORY_USAGE_GB": 2723.9, "CPU_USAGE": 0.4, "DISK_USAGE_GB": 34260.3, "NETWORK_TX_GB": 0.02}},
    EHQ_WS: {P_EHQ: {"MEMORY_USAGE_GB": 20000.0, "CPU_USAGE": 30.0, "DISK_USAGE_GB": 5000.0, "NETWORK_TX_GB": 1.0}},
}
calls = []


class Resp:
    def __init__(self, data, status=200):
        self.status_code, self._data = status, data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


def fake_post(url, json=None, headers=None, timeout=None):
    token = (headers or {}).get("Authorization", "")[7:]
    q, v = (json or {}).get("query", ""), (json or {}).get("variables") or {}
    calls.append(q)
    if token == "project-token" and ("workspace(" in q or "usage(" in q):
        return Resp({"errors": [{"message": "Not Authorized"}]})
    if "usage(" in q:
        rows = [{"measurement": m, "value": val, "tags": {"projectId": pid}}
                for pid, ms in USAGE[v["w"]].items() for m, val in ms.items()]
        return Resp({"data": {"usage": rows}})
    if "workspace(" in q:
        w = WORKSPACES[v["w"]]
        return Resp({"data": {"workspace": {
            "name": w["name"],
            "projects": {"edges": [{"node": {"id": i, "name": n}} for i, n in w["projects"]]},
            "customer": {"invoices": w["invoices"]}}}})
    return Resp({"data": {"projects": {"edges": [{"node": {"id": P_SITE, "name": "Built By Beans Website"}}]}}})


scs.requests.post = fake_post

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    kuper = Client(name="Cason Kuper", email="k@example.test")
    me = Client(name="Michael Bean", email="m@example.test")
    db.session.add_all([boss, kuper, me])
    db.session.flush()
    kp = Project(name="Kuper Plumbing", client_id=kuper.id, status="active")
    ehq_project = Project(name="EntertainHQ", client_id=me.id, status="active")
    ehq_biz = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="entertainhq", sales_source="hub")
    bbb_biz = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="built-by-bean", sales_source="board")
    rw = ServiceProvider(name="railway", display_name="Railway", is_active=True,
                         credentials_json=json.dumps({"api_token": "project-token"}))
    db.session.add_all([kp, ehq_project, ehq_biz, bbb_biz, rw])
    db.session.flush()
    db.session.add_all([
        ServiceMapping(provider_id=rw.id, resource_identifier=f"railway:{P_KUPER}", resource_label="Kuper Plumbing",
                       client_id=kuper.id, project_id=kp.id, split_percentage=100.0, is_active=True),
        ServiceMapping(provider_id=rw.id, resource_identifier=f"railway:{P_EHQ}", resource_label="EntertainHQ",
                       client_id=me.id, project_id=ehq_project.id, split_percentage=100.0, is_active=True),
        # August typed off the bill by hand, and July broken down by hand.
        ProviderInvoice(provider_id=rw.id, period_month=date(2026, 8, 1), amount=40.70, note="Invoice dated 2026-09-01"),
    ])
    db.session.flush()
    scs._record_cost_entry(rw, f"railway:{P_SITE}", date(2026, 7, 1), date(2026, 7, 31), 21.45,
                           "Railway - Built By Beans Website", {"source": "manual", "label": "Built By Beans Website"})
    db.session.commit()
    ids = dict(boss=boss.id, rw=rw.id, kuper=kuper.id, me=me.id, ehq_biz=ehq_biz.id)

    print("The migration")
    spec = importlib.util.spec_from_file_location(
        "mig", ROOT / "migrations/versions/d5b1e8f40a63_railway_bills_pull_themselves.py")
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with db.engine.begin() as conn:
        mig.op = Operations(MigrationContext.configure(conn))
        mig.upgrade()
    db.session.expire_all()
    rw = db.session.get(ServiceProvider, ids["rw"])
    ehq = ServiceProvider.query.filter_by(display_name="Railway (EntertainHQ)").first()
    check("the existing provider is Built by Bean's workspace",
          json.loads(rw.credentials_json).get("workspace_id") == BBB_WS
          and json.loads(rw.credentials_json).get("api_token") == "project-token")
    check("Railway (EntertainHQ) exists, owned by EntertainHQ, not ours",
          ehq is not None and ehq.account_business_id == ids["ehq_biz"] and not ehq.is_ours
          and json.loads(ehq.credentials_json).get("workspace_id") == EHQ_WS)
    bills = {(i.provider_id, i.period_month): i.amount for i in ProviderInvoice.query.all()}
    check("September and October are recorded for Built by Bean",
          bills.get((rw.id, date(2026, 9, 1))) == 43.71 and bills.get((rw.id, date(2026, 10, 1))) == 52.38, bills)
    check("and September for EntertainHQ, its three invoices together",
          bills.get((ehq.id, date(2026, 9, 1))) == 42.48, bills)
    check("a month typed by hand is left alone", bills.get((rw.id, date(2026, 8, 1))) == 40.70)
    ids["ehq"] = ehq.id

    print("A token that cannot read billing")
    count, error = scs.sync_provider(ids["rw"])
    check("says to make an account token", error and "account token" in error, error)

    print("Built by Bean's pull")
    rw = db.session.get(ServiceProvider, ids["rw"])
    rw.credentials_json = json.dumps({"api_token": "account-token", "workspace_id": BBB_WS})
    db.session.commit()
    count, error = scs.sync_provider(ids["rw"])
    check("pulls with an account token", error is None and count > 0, (count, error))
    bills = {i.period_month: i for i in ProviderInvoice.query.filter_by(provider_id=ids["rw"]).all()}
    check("July's missing bill is recorded", bills.get(date(2026, 7, 1)) and bills[date(2026, 7, 1)].amount == 21.45)
    check("August, typed by hand, keeps its note", bills[date(2026, 8, 1)].note == "Invoice dated 2026-09-01")
    check("a period still running is not a bill", date(2026, 11, 1) not in bills)
    check("a void invoice is not a bill", date(2026, 6, 1) not in bills)
    for month, want in ((date(2026, 9, 1), 43.71), (date(2026, 10, 1), 52.38)):
        start, end = scs._month_bounds(month)
        entries = ServiceCostEntry.query.filter_by(provider_id=ids["rw"], period_start=start, period_end=end).all()
        expenses = [e.expense for e in entries if e.expense]
        check(f"{month:%B} is split across its projects to the cent",
              round(sum(e.raw_amount for e in entries), 2) == want and len(entries) == 3,
              (round(sum(e.raw_amount for e in entries), 2), len(entries)))
        check(f"{month:%B}'s expenses add up to the bill",
              round(sum(x.amount for x in expenses), 2) == want and len(expenses) == 3,
              round(sum(x.amount for x in expenses), 2))
    sept = scs._month_bounds(date(2026, 9, 1))
    k = ServiceCostEntry.query.filter_by(provider_id=ids["rw"], resource_identifier=f"railway:{P_KUPER}",
                                         period_start=sept[0]).first()
    check("Kuper's share lands on Kuper", k and k.expense and k.expense.client_id == ids["kuper"]
          and "[unallocated]" not in k.description, k and k.description)
    gone = ServiceCostEntry.query.filter_by(provider_id=ids["rw"], resource_identifier=f"railway:{P_GONE}",
                                            period_start=sept[0]).first()
    check("a deleted project keeps a name", gone and "Deleted project" in gone.description, gone and gone.description)
    july = ServiceCostEntry.query.filter_by(provider_id=ids["rw"], period_start=date(2026, 7, 1)).all()
    check("July, broken down by hand, is left as it was",
          len(july) == 1 and json.loads(july[0].raw_data_json)["source"] == "manual", len(july))
    before = (ServiceCostEntry.query.count(), Expense.query.count(), round(sum(e.amount for e in Expense.query.all()), 2))
    scs.sync_provider(ids["rw"])
    after = (ServiceCostEntry.query.count(), Expense.query.count(), round(sum(e.amount for e in Expense.query.all()), 2))
    check("a second pull corrects rather than doubles", before == after, (before, after))

    print("EntertainHQ's pull, on the account token in the service's variables")
    ehq = db.session.get(ServiceProvider, ids["ehq"])
    check("no token anywhere is a plain error", scs.sync_provider(ids["ehq"])[1] == "Railway API token not configured")
    os.environ["PM_RAILWAY_ACCOUNT_TOKEN"] = "account-token"
    check("the variable is read for a provider that names a workspace",
          scs.railway_token(json.loads(ehq.credentials_json)) == "account-token")
    check("and not for one that does not", scs.railway_token({"api_token": "typed"}) == "typed")
    spent = round(sum(e.amount for e in Expense.query.all()), 2)
    count, error = scs.sync_provider(ids["ehq"])
    entries = ServiceCostEntry.query.filter_by(provider_id=ids["ehq"]).all()
    check("its September is recorded against its project", error is None and len(entries) == 1
          and entries[0].raw_amount == 42.48, (error, [(e.resource_identifier, e.raw_amount) for e in entries]))
    check("and books nothing on Built by Bean's ledger",
          all(e.expense_id is None for e in entries) and round(sum(e.amount for e in Expense.query.all()), 2) == spent)
    m = ServiceMapping.query.filter_by(provider_id=ids["ehq"], resource_identifier=f"railway:{P_EHQ}").first()
    check("its project keeps the mapping it had under Built by Bean's account",
          m and m.client_id == ids["me"] and "[unallocated]" not in entries[0].description, entries and entries[0].description)
    check("its October, still running, is not a bill",
          not ProviderInvoice.query.filter_by(provider_id=ids["ehq"], period_month=date(2026, 10, 1)).first())
    check("the workspace names the account", db.session.get(ServiceProvider, ids["ehq"]).account_label == "EntertainHQ")

    print("Needs attention")
    from pm import attention_routes
    this_month = date.today().replace(day=1)
    last = (this_month - timedelta(days=1)).replace(day=1)
    before_last = (last - timedelta(days=1)).replace(day=1)
    typed = ServiceProvider(name="railway", display_name="Railway (typed)", is_active=True,
                            credentials_json=json.dumps({"api_token": "x"}))
    db.session.add(typed)
    db.session.flush()
    for p in (typed, db.session.get(ServiceProvider, ids["ehq"])):
        ProviderInvoice.query.filter(ProviderInvoice.provider_id == p.id,
                                     ProviderInvoice.period_month >= last).delete()
        if not ProviderInvoice.query.filter_by(provider_id=p.id, period_month=before_last).first():
            db.session.add(ProviderInvoice(provider_id=p.id, period_month=before_last, amount=1.0, note="x"))
    db.session.commit()
    asks = {r["provider"].display_name: r["missing"] for r in attention_routes._bills_to_enter(force=True)}
    check("a typed-in account is asked for last month", last in asks.get("Railway (typed)", []), asks)
    check("a pulled account is given a month's grace", last not in asks.get("Railway (EntertainHQ)", []), asks)
    db.session.delete(typed)
    db.session.commit()

    print("The hosting page")
    from pm.hosting_routes import _railway_all_time
    ours = round(sum(i.amount for i in ProviderInvoice.query.filter_by(provider_id=ids["rw"]).all()), 2)
    got = _railway_all_time()
    check("all-time Railway is Built by Bean's account only", round(got["amount"], 2) == ours, (got, ours))

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True

print("The provider form")
html = c.get(f"/admin/service-costs/providers/{ids['ehq']}/edit").get_data(as_text=True)
check("shows the workspace", EHQ_WS in html and 'name="railway_workspace_id"' in html)
calls.clear()
r = c.post(f"/admin/service-costs/providers/{ids['ehq']}/edit", data={
    "railway_api_token": "account-token", "railway_workspace_id": EHQ_WS, "is_active": "1",
    "account_client_id": ""}, follow_redirects=True)
with application.app_context():
    p = db.session.get(ServiceProvider, ids["ehq"])
    check("saving keeps the workspace and the business", json.loads(p.credentials_json).get("workspace_id") == EHQ_WS
          and p.account_business_id == ids["ehq_biz"])
check("and pulls the bills on the press", any("workspace" in q for q in calls) and "Bills pulled from Railway" in r.get_data(as_text=True),
      calls)
os.environ.pop("PM_RAILWAY_ACCOUNT_TOKEN", None)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
sys.exit(1 if FAIL else 0)
