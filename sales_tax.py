"""Texas sales tax on what has been sold, and what each client owes for it.

The accountant's reading, which is the whole basis of this file: software sold
as a service is a data processing service in Texas, 20% of that charge is
exempt, and the rest is taxed at the local rate. 8.25% on 80% is 6.6% of every
dollar billed, so that is the one number applied to every invoice. No line by
line classification: everything this business sells is the same kind of thing,
and an invoice that is not (the accountant says so) is marked not taxable.

The tax was owed when the sale was made, whether or not it was on the bill. So
for each invoice that went out:

    due      = 6.6% of what was billed before tax
    charged  = the tax Stripe put on the invoice
    short    = due - charged, the part the client was never asked for

and a client's balance is the sum of their shorts, less what has already been
billed back to them on a catch-up invoice. Paying the catch-up clears it.

Pure: takes rows, returns dicts, touches neither the database nor Stripe, so
the whole calculation can be tested with plain objects.
"""
from datetime import date

# An invoice that is out: paid, or sent and still owed. Both are sales and the
# tax on both is due. A draft has not been sold yet, a void never was, and an
# uncollectible one is a bad debt, which is not something to bill tax on.
SOLD = ("open", "paid")

# Stripe works the tax out per line and rounds each one, so an invoice that
# carries the right rate can still come out a cent or two under a figure
# worked on the total. That is rounding, not a missed charge, and a client
# shown as owing four cents is a row nobody will ever act on.
ROUNDING_CENTS = 5


def _cents(amount):
    return int(round((amount or 0) * 100))


def _quarter_key(day):
    return (day.year, (day.month - 1) // 3 + 1)


def invoice_row(inv, settings, client, project, *, client_exempt):
    """One invoice, with what was due on it and what was charged."""
    total = _cents(inv.total)
    charged = _cents(inv.tax)
    base = total - charged
    due = int(round(base * settings.effective_percent / 100.0))

    excluded = None
    if inv.sales_tax_catchup:
        excluded = "catch-up"
    elif client_exempt:
        excluded = "client exempt"
    elif inv.sales_tax_exempt:
        excluded = "not taxable"
    elif settings.count_from and inv.issued_on and inv.issued_on < settings.count_from:
        excluded = "before " + settings.count_from.strftime("%b %d, %Y").replace(" 0", " ")

    short = max(0, due - charged)
    if charged and short <= ROUNDING_CENTS:
        short = 0

    sold = (inv.status or "") in SOLD
    return {
        "invoice": inv,
        "project": project,
        "sold": sold,
        "counted": sold and excluded is None,
        "excluded": excluded,
        "base": base / 100.0,
        "due": due / 100.0,
        "charged": charged / 100.0,
        "short": short / 100.0,
        # A draft about to go out with no tax on it: the hole, still open.
        "draft_missing_tax": ((inv.status or "") == "draft" and excluded is None
                              and charged == 0 and base > 0),
    }


def _money_totals():
    return {"sales": 0.0, "due": 0.0, "charged": 0.0, "short": 0.0, "count": 0}


def _add(bucket, row):
    bucket["sales"] += row["base"]
    bucket["due"] += row["due"]
    bucket["charged"] += row["charged"]
    bucket["short"] += row["short"]
    bucket["count"] += 1


def _round_all(bucket):
    for k, v in bucket.items():
        if isinstance(v, float):
            bucket[k] = round(v, 2)
    return bucket


def build(settings, clients, invoices, projects, subscriptions=(), rate_id=None):
    """The whole ledger.

    clients        Client rows (only those with invoices or subscriptions
                   are reported)
    invoices       Invoice rows, any status
    projects       Project rows, for attributing invoices
    subscriptions  dicts from stripe_service.get_subscriptions_for_tax
    rate_id        the board's current Stripe tax rate, if made yet
    """
    projects_by_client = {}
    for p in projects:
        projects_by_client.setdefault(p.client_id, []).append(p)
    project_by_id = {p.id: p for p in projects}

    subs_by_customer = {}
    for sub in subscriptions or ():
        if sub.get("customer_id"):
            subs_by_customer.setdefault(sub["customer_id"], []).append(sub)

    by_client = {}
    for inv in invoices:
        by_client.setdefault(inv.client_id, []).append(inv)

    report = []
    totals = dict(_money_totals(), drafted=0.0, billed=0.0, collected=0.0, to_bill=0.0)
    quarters = {}

    for client in clients:
        mine = by_client.get(client.id, [])
        subs = subs_by_customer.get(client.stripe_customer_id, []) if client.stripe_customer_id else []
        if not mine and not subs:
            continue
        exempt = bool(client.sales_tax_exempt)
        own_projects = sorted(projects_by_client.get(client.id, []), key=lambda p: p.name.lower())
        only = own_projects[0] if len(own_projects) == 1 else None

        rows, catchups = [], []
        groups = {}
        money = _money_totals()
        for inv in mine:
            # An invoice with no project belongs to the only project when
            # there is exactly one; with two or more, guessing would put one
            # project's tax on another, so it is left for a person to say.
            project = project_by_id.get(inv.project_id) or only
            row = invoice_row(inv, settings, client, project, client_exempt=exempt)
            if inv.sales_tax_catchup:
                if (inv.status or "") != "void":
                    catchups.append(inv)
                continue
            rows.append(row)
            if not row["counted"]:
                continue
            _add(money, row)
            key = project.id if project else None
            group = groups.setdefault(key, dict(_money_totals(), project=project))
            _add(group, row)
            if inv.issued_on:
                q = quarters.setdefault(_quarter_key(inv.issued_on), _money_totals())
                _add(q, row)

        drafted = sum(_cents(c.total) for c in catchups if c.status == "draft") / 100.0
        # The whole of an open one, not what is still due on it: a part paid
        # catch-up has billed all of it, and counting only the remainder would
        # offer to bill the paid part a second time.
        billed = sum(_cents(c.total) for c in catchups if c.status == "open") / 100.0
        collected = sum(_cents(c.amount_paid) for c in catchups if c.status == "paid") / 100.0
        _round_all(money)
        to_bill = 0.0 if exempt else round(max(0.0, money["short"] - drafted - billed - collected), 2)

        missing_subs = []
        if not exempt:
            for sub in subs:
                ids = sub.get("rate_ids") or []
                if (rate_id not in ids) if rate_id else not ids:
                    missing_subs.append(sub)

        epoch = date.min
        rows.sort(key=lambda r: (r["invoice"].issued_on or epoch, r["invoice"].id), reverse=True)
        entry = {
            "client": client,
            "exempt": exempt,
            "projects": own_projects,
            "groups": [_round_all(g) for _, g in sorted(
                groups.items(), key=lambda kv: (kv[0] is None, (kv[1]["project"].name.lower()
                                                                if kv[1]["project"] else "")))],
            "invoices": rows,
            "catchups": sorted(catchups, key=lambda c: c.id, reverse=True),
            "drafts_missing_tax": [r["invoice"] for r in rows if r["draft_missing_tax"]],
            "subs_missing_tax": missing_subs,
            "drafted": drafted,
            "billed": billed,
            "collected": collected,
            "to_bill": to_bill,
            **money,
        }
        report.append(entry)
        if not exempt:
            for k in ("sales", "due", "charged", "short", "count"):
                totals[k] += money[k]
            totals["drafted"] += drafted
            totals["billed"] += billed
            totals["collected"] += collected
            totals["to_bill"] += to_bill

    # What needs doing first, first: money to bill, then holes still open,
    # then everybody square, then the exempt.
    report.sort(key=lambda e: (e["exempt"], -e["to_bill"],
                               -(len(e["drafts_missing_tax"]) + len(e["subs_missing_tax"])),
                               e["client"].name.lower()))

    share = (settings.taxable_share or 0) / 100.0
    quarter_rows = []
    for (year, q), bucket in sorted(quarters.items(), reverse=True):
        _round_all(bucket)
        quarter_rows.append(dict(bucket, label=f"{year} Q{q}", year=year, quarter=q,
                                 taxable=round(bucket["sales"] * share, 2)))

    return {"clients": report, "totals": _round_all(totals), "quarters": quarter_rows}


def client_balance(settings, client, invoices):
    """One client's figure for their own page, from the same arithmetic."""
    ledger = build(settings, [client], invoices, list(client.projects))
    return ledger["clients"][0] if ledger["clients"] else None


def catchup_lines(entry):
    """The lines of a catch-up invoice for `entry`'s unbilled balance.

    One line per project when nothing has been billed back yet, so the client
    can see which build each amount is for. Once something has, the split
    across projects of what is left is not knowable, so it is one line.
    """
    amount = entry["to_bill"]
    if amount <= 0:
        return []
    already = entry["drafted"] + entry["billed"] + entry["collected"]
    if not already:
        lines = []
        for g in entry["groups"]:
            if g["short"] <= 0:
                continue
            what = g["project"].name if g["project"] else "earlier invoices"
            lines.append({"description": f"Texas sales tax not charged on {what}",
                          "quantity": 1, "unit_amount": g["short"]})
        if lines and abs(sum(l["unit_amount"] for l in lines) - amount) < 0.005:
            return lines
    return [{"description": "Texas sales tax not charged on earlier invoices",
             "quantity": 1, "unit_amount": amount}]


# ── Returns ──────────────────────────────────────────────
#
# What goes on the state's return for one business and one period, location
# by location, in the whole dollars WebFile asks for. The ledger above is
# about what each CLIENT was charged; this is about what the BUSINESS reports,
# and the two share only the rule for which invoices are sales.
#
# Checked against the first two returns Built by Bean filed (2026-10-30):
#   Apr-Jun 2026  Fort Worth  5,150 / 4,120  -> $339.90 (257.50 + 82.40)
#   Jul-Sep 2026  Paris       2,500 / 2,000  -> $165.00
#                 Fort Worth  7,450 / 5,960  -> $491.70
# WebFile worked out every tax figure itself from the two numbers typed per
# location, so those two numbers are the whole of the job.

from datetime import timedelta  # noqa: E402
from decimal import Decimal, ROUND_HALF_UP  # noqa: E402

STATE_RATE = 6.25

# Late is 5% of the tax for the first thirty days and 10% after, plus $50 for
# the report, and interest from the 61st day. On time and paid, the filer
# keeps 0.5% of the tax as a timely filing discount. (Texas Tax Code 151.423
# and 111.061; the Comptroller's "Penalties and interest" page.)
PENALTY_FIRST_MONTH = 5
PENALTY_AFTER = 10
LATE_REPORT_FEE = 50.0
INTEREST_AFTER_DAYS = 60
TIMELY_DISCOUNT = 0.5

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _half_up(value, places="0.01"):
    return float(Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP))


def _whole(cents):
    """Cents to the whole dollars WebFile takes, half up as people round."""
    return int(Decimal(cents).scaleb(-2).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quarter_of(day):
    return day.year, (day.month - 1) // 3 + 1


def period_code(year, quarter):
    """WebFile's name for a quarter: the year's last two digits, then the
    quarter. 262 is April to June 2026, and it is the number on the radio
    button that has to be picked."""
    return f"{year % 100:02d}{quarter}"


def period_label(year, quarter):
    first = 3 * quarter - 3
    return f"{_MONTHS[first]}–{_MONTHS[first + 2]} {year}"


def quarter_bounds(year, quarter):
    start = date(year, 3 * quarter - 2, 1)
    nxt = date(year + 1, 1, 1) if quarter == 4 else date(year, 3 * quarter + 1, 1)
    return start, nxt - timedelta(days=1)


def _nth_weekday(year, month, weekday, n):
    """The nth (1-based) `weekday` (Monday 0) of a month; n = -1 is the last."""
    if n < 0:
        day = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
        return day - timedelta(days=(day.weekday() - weekday) % 7)
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _observed(day):
    """A holiday on a Saturday is kept the Friday before, on a Sunday the
    Monday after."""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def federal_holidays(year):
    """The federal legal holidays of a year, as observed.

    The same list EntertainHQ's filing calendar works from
    (site/functions/_admin/tax_filings.js), so the two never name different
    due dates for the same return. New Year's Day on a Saturday is kept on
    December 31 of the year before, which is why next year's is asked too.
    """
    days = set()
    for y in (year, year + 1):
        days.update({
            _observed(date(y, 1, 1)), _nth_weekday(y, 1, 0, 3), _nth_weekday(y, 2, 0, 3),
            _nth_weekday(y, 5, 0, -1), _observed(date(y, 6, 19)), _observed(date(y, 7, 4)),
            _nth_weekday(y, 9, 0, 1), _nth_weekday(y, 10, 0, 2), _observed(date(y, 11, 11)),
            _nth_weekday(y, 11, 3, 4), _observed(date(y, 12, 25)),
        })
    return {d for d in days if d.year == year}


def due_date(year, quarter):
    """The 20th of the month after the quarter, moved to a working day.

    A due date on a Saturday, a Sunday or a federal legal holiday moves to
    the next working day, as many days on as it takes: Q4 2029 is due on
    Sunday 2030-01-20, then MLK Day, so Tuesday the 22nd.
    """
    _start, end = quarter_bounds(year, quarter)
    day = date(end.year + (1 if end.month == 12 else 0), end.month % 12 + 1, 20)
    while day.weekday() >= 5 or day in federal_holidays(day.year):
        day += timedelta(days=1)
    return day


def periods_owed(first_sale, today):
    """Every quarter from the first taxable sale through today's.

    Today's quarter is included while it is still running, so the page can
    show what is building up before it is due.
    """
    if not first_sale:
        return []
    year, q = quarter_of(first_sale)
    end = quarter_of(today)
    out = []
    while (year, q) <= end:
        out.append((year, q))
        year, q = (year + 1, 1) if q == 4 else (year, q + 1)
    return out


def charges_if_paid_on(tax, due, on):
    """What WebFile will add, or take off, if the return is paid on `on`.

    An estimate: WebFile's own penalty rounds state and local separately (on
    the first return it said $34.00 where 10% of $339.90 is $33.99), and the
    interest rate is set each year. The return's own Review page is the
    figure to pay.
    """
    days = (on - due).days
    if days <= 0:
        return {"late": False, "days": 0, "penalty_rate": 0, "penalty": 0.0,
                "late_fee": 0.0, "interest_from": None,
                "discount": _half_up(tax * TIMELY_DISCOUNT / 100.0)}
    rate = PENALTY_FIRST_MONTH if days <= 30 else PENALTY_AFTER
    return {"late": True, "days": days, "penalty_rate": rate,
            "penalty": _half_up(tax * rate / 100.0), "late_fee": LATE_REPORT_FEE,
            "interest_from": due + timedelta(days=INTEREST_AFTER_DAYS + 1),
            "discount": 0.0}


def status_of(year, quarter, filing, today):
    """One word for where a period stands: filed, late, due or open."""
    if filing is not None:
        return "filed"
    _start, end = quarter_bounds(year, quarter)
    if today <= end:
        return "open"
    return "late" if today > due_date(year, quarter) else "due"


def board_sales(rows, start, end):
    """The ledger's counted invoices in a period, as sales to place.

    `rows` are invoice_row dicts. The base before tax is the sale: tax a
    client was charged is the state's money passing through, not a sale.
    """
    out = []
    for r in rows:
        inv = r["invoice"]
        if not r["counted"] or not inv.issued_on or not (start <= inv.issued_on <= end):
            continue
        out.append({"date": inv.issued_on, "total": r["base"], "taxable": None,
                    "ref": inv.invoice_number or f"#{inv.id}", "invoice_id": inv.id,
                    "who": getattr(getattr(inv, "client", None), "name", "") or ""})
    return out


def build_return(locations_for, sales, share, *, year, quarter):
    """The return for one period: a line per location, in whole dollars.

    locations_for  a function from a date to the location trading that day
                   (Business.location_on), or None when nothing was
    sales          dicts with "date", "total" and "taxable" (None to work it
                   out from `share`, the business's taxable percentage)

    A sale on a day no location covers is kept in `unplaced` rather than
    dropped or guessed onto a line: it means a location's dates are wrong,
    and filing without it would leave a sale off the return.
    """
    start, end = quarter_bounds(year, quarter)
    lines, unplaced = {}, []
    for s in sales:
        loc = locations_for(s["date"])
        if loc is None:
            unplaced.append(s)
            continue
        line = lines.setdefault(loc.id, {"location": loc, "sales": [],
                                         "total_cents": 0, "taxable_cents": 0})
        total = _cents(s["total"])
        taxable = (_cents(s["taxable"]) if s.get("taxable") is not None
                   else int((Decimal(total) * Decimal(str(share)) / 100)
                            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
        line["total_cents"] += total
        line["taxable_cents"] += taxable
        line["sales"].append(s)

    out = []
    for line in sorted(lines.values(), key=lambda l: (l["location"].webfile_number or "",
                                                      l["location"].label)):
        loc = line["location"]
        total_sales = _whole(line["total_cents"])
        taxable_sales = _whole(line["taxable_cents"])
        state_tax = _half_up(taxable_sales * STATE_RATE / 100.0)
        local_tax = _half_up(taxable_sales * (loc.local_rate or 0) / 100.0)
        line["sales"].sort(key=lambda s: (s["date"], s.get("ref") or ""))
        out.append({"location": loc, "number": loc.webfile_number or "", "label": loc.label,
                    "total_sales": total_sales, "taxable_sales": taxable_sales,
                    "state_tax": state_tax, "local_tax": local_tax,
                    "tax": _half_up(state_tax + local_tax), "sales": line["sales"]})

    tax = _half_up(sum(l["tax"] for l in out))
    return {
        "year": year, "quarter": quarter, "start": start, "end": end,
        "code": period_code(year, quarter), "label": period_label(year, quarter),
        "due": due_date(year, quarter),
        "lines": out, "unplaced": unplaced,
        "total_sales": sum(l["total_sales"] for l in out),
        "taxable_sales": sum(l["taxable_sales"] for l in out),
        "state_tax": _half_up(sum(l["state_tax"] for l in out)),
        "local_tax": _half_up(sum(l["local_tax"] for l in out)),
        "tax": tax,
    }
