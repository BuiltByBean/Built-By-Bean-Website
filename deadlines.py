"""One list of every date the state or the IRS holds Michael to.

Audit item 8 (docs/automation_gaps.md). Before this the board knew the sales
tax returns and nothing else: no May 15 franchise report, no 1065 for
EntertainHQ's three members, no 1040, the estimate dates on the Taxes page did
not roll off weekends, and a DBA's assumed name certificate had no date at all.

Each deadline is a dict:

    key      stable, for DeadlineDone ("franchise:3:2027")
    kind     sales_tax, franchise, partnership, personal, estimate, dba
    business the Business, or None for Michael's own
    title    what it is, in words
    due      the day, rolled past weekends and federal holidays
    done     how it is known to be done, in words, or ""
    proof    "record" when a record proves it, "press" when only Michael can

A deadline shows on Needs attention from ten days out (LEAD_DAYS) and stays
once late, until something proves it done. What proves it:

  sales tax    its SalesTaxFiling (a drafted one has its own row, asking for
               the reference number, because the money has gone)
  franchise    the Comptroller's reportYear reaching the year (comptroller.py)
  estimate     an IRS line on any bank or statement near the date
  the rest     Michael's Done press (DeadlineDone)

Federal and estimate dates start at LIST_STARTED: the board knew none of them
before 2026-11-04, and listing every past one as late would be a wall of rows
for returns that were filed. The state's dates need no such line, because the
state's own records say which are done.
"""
import re
import time
from datetime import date, timedelta

import sales_tax

LEAD_DAYS = 10
LIST_STARTED = date(2026, 11, 1)
# How far ahead the deadlines page looks.
HORIZON_DAYS = 400
# A Texas assumed name certificate runs up to ten years from filing.
ASSUMED_NAME_YEARS = 10
# What an IRS payment reads as on a bank line: Direct Pay and EFTPS both
# arrive as "IRS USATAXPYMT"; a mailed check clears as "US TREASURY".
IRS_PAYMENT = re.compile(r"\bIRS\b|USATAXPYMT|US\s*TREAS|EFTPS", re.I)
ESTIMATE_WINDOW = (30, 30)  # days before and after the due date
# US estimated payments: Q1 Apr 15, Q2 Jun 15, Q3 Sep 15, Q4 Jan 15 next year.
ESTIMATE_DUE = {1: (0, 4, 15), 2: (0, 6, 15), 3: (0, 9, 15), 4: (1, 1, 15)}


def estimate_due(year, quarter):
    """The day a quarter's estimated payment is due, moved to a working day
    the way sales_tax.due_date moves a return."""
    plus, month, day = ESTIMATE_DUE[quarter]
    return sales_tax.working_day(date(year + plus, month, day))


def franchise_due(report_year):
    """May 15 of the report year, moved to a working day: 2027's is Monday
    May 17, because the 15th is a Saturday."""
    return sales_tax.working_day(date(report_year, 5, 15))


def _status(due, done, today):
    if done:
        return "done"
    if today > due:
        return "late"
    if (due - today).days <= LEAD_DAYS:
        return "soon"
    return "upcoming"


def _row(key, kind, business, title, due, today, done="", proof="press", url=None, note=""):
    return {"key": key, "kind": kind, "business": business, "title": title, "due": due,
            "done": done, "proof": proof, "url": url, "note": note,
            "status": _status(due, done, today)}


def irs_payments():
    """IRS payments off every bank and statement: [(date, amount, id)]."""
    from models import BankTransaction
    rows = (BankTransaction.query.filter(BankTransaction.amount < 0,
                                         BankTransaction.disposition != "void")
            .order_by(BankTransaction.occurred_on, BankTransaction.id).all())
    return [(t.occurred_on, round(-t.amount, 2), t.id) for t in rows
            if IRS_PAYMENT.search(f"{t.counterparty} {t.description}")]


def match_estimates(dues, payments):
    """{(year, quarter): (date, amount)} pairing each estimate with the first
    IRS payment near its date that no earlier estimate took. Pure."""
    before, after = ESTIMATE_WINDOW
    used, out = set(), {}
    for (year, quarter), due in sorted(dues.items(), key=lambda kv: kv[1]):
        for day, amount, pid in payments:
            if pid in used or not (due - timedelta(days=before) <= day <= due + timedelta(days=after)):
                continue
            used.add(pid)
            out[(year, quarter)] = (day, amount)
            break
    return out


def build(today=None, businesses=None, done_keys=None, payments=None):
    """Every deadline from LIST_STARTED (or the state's first) to the horizon,
    soonest first. The arguments are for tests; the board reads its own."""
    from models import Business, DeadlineDone
    from flask import url_for
    from pm import business_routes as br
    today = today or date.today()
    horizon = today + timedelta(days=HORIZON_DAYS)
    if businesses is None:
        businesses = Business.query.filter_by(is_active=True).order_by(Business.name, Business.id).all()
    if done_keys is None:
        done_keys = {d.key: d for d in DeadlineDone.query.all()}
    out = []

    def pressed(key):
        d = done_keys.get(key)
        if not d:
            return ""
        when = getattr(d, "done_at", None)
        return "Marked done" + (f" {when:%b %d, %Y}".replace(" 0", " ") if when else "")

    companies = [b for b in businesses if not b.parent_id]
    for b in companies:
        # Sales tax: every period owed and not filed, and the next one.
        for year, n in br.owed_periods(b, today):
            filing = b.filing_for(year, n)
            due = sales_tax.due_date(year, n)
            status = sales_tax.status_of(year, n, filing, today)
            if status == "filed" or due > horizon:
                continue
            url = url_for("businesses.return_page", slug=b.slug, year=year, quarter=n)
            label = sales_tax.period_label(year, n)
            if status == "drafted":
                row = _row(f"sales_tax_ref:{b.id}:{year}:{n}", "sales_tax_ref", b,
                           f"{label} sales tax return: type its reference number", due, today,
                           proof="record", url=url,
                           note="Paid on " + filing.filed_at.strftime("%b %d").replace(" 0", " "))
                row["status"] = "now"
                out.append(row)
                continue
            out.append(_row(f"sales_tax:{b.id}:{year}:{n}", "sales_tax", b,
                            f"{label} sales tax return", due, today, proof="record", url=url))

        # The franchise report and Public Information Report, every May 15
        # from the year after the company was formed.
        if b.formed_on or b.texas_taxpayer_number:
            first = (b.formed_on.year + 1) if b.formed_on else today.year
            for year in range(first, horizon.year + 1):
                due = franchise_due(year)
                if due > horizon:
                    continue
                key = f"franchise:{b.id}:{year}"
                done = ("On the Comptroller's record" if (b.franchise_report_year or 0) >= year
                        else pressed(key))
                if done and due < today - timedelta(days=365):
                    continue
                out.append(_row(key, "franchise", b, f"{year} franchise tax report and PIR",
                                due, today, done, proof="record",
                                url=url_for("businesses.detail", id=b.id)))

        # A partnership return and a K-1 for each member, March 15.
        owners = list(getattr(b, "owners", []) or [])
        if len(owners) > 1:
            start = max((b.formed_on or LIST_STARTED).year, LIST_STARTED.year - 1)
            for tax_year in range(start, horizon.year):
                due = sales_tax.working_day(date(tax_year + 1, 3, 15))
                if due < LIST_STARTED or due > horizon:
                    continue
                key = f"partnership:{b.id}:{tax_year}"
                out.append(_row(key, "partnership", b,
                                f"{tax_year} Form 1065 and {len(owners)} K-1s", due, today,
                                pressed(key), url=url_for("businesses.detail", id=b.id)))

    # Michael's own: the 1040 with a Schedule C for each company he owns alone,
    # and the four estimated payments.
    alone = [b for b in companies if len(list(getattr(b, "owners", []) or [])) <= 1]
    if alone:
        names = ", ".join(b.label for b in alone)
        for tax_year in range(LIST_STARTED.year - 1, horizon.year):
            due = sales_tax.working_day(date(tax_year + 1, 4, 15))
            if due < LIST_STARTED or due > horizon:
                continue
            key = f"personal:{tax_year}"
            out.append(_row(key, "personal", None, f"{tax_year} Form 1040 and Schedule C",
                            due, today, pressed(key), note=names))
        dues = {}
        for year in range(LIST_STARTED.year - 1, horizon.year + 1):
            for q in (1, 2, 3, 4):
                due = estimate_due(year, q)
                if LIST_STARTED <= due <= horizon:
                    dues[(year, q)] = due
        paid = match_estimates(dues, irs_payments() if payments is None else payments)
        for (year, q), due in sorted(dues.items(), key=lambda kv: kv[1]):
            key = f"estimate:{year}:{q}"
            done = pressed(key)
            if (year, q) in paid:
                day, amount = paid[(year, q)]
                done = f"${amount:,.2f} to the IRS on " + day.strftime("%b %d").replace(" 0", " ")
            out.append(_row(key, "estimate", None, f"{year} Q{q} estimated tax payment", due,
                            today, done, proof="record" if (year, q) in paid else "press"))

    # A DBA's assumed name certificate.
    for b in businesses:
        if not b.parent_id:
            continue
        if not b.assumed_name_filed_on:
            row = _row(f"dba:{b.id}:unknown", "dba", b, "Assumed name certificate: filing date not on file",
                       today, today, url=url_for("businesses.edit", id=b.id))
            row["status"] = "no_date"
            out.append(row)
            continue
        filed = b.assumed_name_filed_on
        try:
            expires = filed.replace(year=filed.year + ASSUMED_NAME_YEARS)
        except ValueError:  # February 29
            expires = filed.replace(year=filed.year + ASSUMED_NAME_YEARS, day=28)
        # The last day it is good for, never rolled forward: a renewal moved
        # past a weekend would be a day after it lapsed.
        due = expires - timedelta(days=1)
        key = f"dba:{b.id}:{expires.year}"
        if due <= horizon or today > due:
            out.append(_row(key, "dba", b, "Renew the assumed name certificate", due, today,
                            pressed(key), url=url_for("businesses.detail", id=b.id)))

    order = {"now": 0, "late": 1, "soon": 2, "upcoming": 3, "no_date": 4, "done": 5}
    out.sort(key=lambda r: (order[r["status"]], r["due"], r["title"]))
    return out


def standing_problems(businesses=None):
    """Companies whose right to transact in Texas is not ACTIVE."""
    from models import Business
    if businesses is None:
        businesses = Business.query.filter_by(is_active=True, parent_id=None).all()
    return [b for b in businesses if (b.franchise_status or "").strip()
            and b.franchise_status.strip().upper() != "ACTIVE"]


def open_flags():
    from models import ComptrollerFlag
    return (ComptrollerFlag.query.filter(ComptrollerFlag.seen_at.is_(None))
            .order_by(ComptrollerFlag.created_at.desc(), ComptrollerFlag.id.desc()).all())


def attention_rows(today=None):
    """What Needs attention shows: {standing, flags, deadlines}."""
    rows = [r for r in build(today) if r["status"] in ("now", "late", "soon")]
    return {"standing": standing_problems(), "flags": open_flags(), "deadlines": rows}


# The sidebar badge is built on every page; the list reads every business,
# its filings and the bank's IRS lines, so it is cached like the bills.
_CACHE = {"at": 0.0, "value": None}
_TTL = 600


def attention_count(force=False):
    from models import db
    now = time.time()
    if not force and _CACHE["value"] is not None and now - _CACHE["at"] < _TTL:
        return _CACHE["value"]
    try:
        got = attention_rows()
        value = len(got["standing"]) + len(got["flags"]) + len(got["deadlines"])
    except Exception:  # noqa: BLE001 - a table that does not exist yet must not take the board down
        db.session.rollback()
        value = 0
    _CACHE.update(at=now, value=value)
    return value


def forget():
    _CACHE.update(at=0.0, value=None)
