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
