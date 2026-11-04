"""Only the bank line makes an expense: carrying the vendor-written ones over.

docs/finances_plan.md item 5 (Michael, 2026-11-04). Until now a vendor sync
(Railway, Cloudflare, Claude, AWS) wrote an Expense per cost entry, and the bank
line for the same charge was marked "covered" and booked nothing. From now on
the bank line is the expense and the vendor's report only splits it across
projects and clients (bank_feed.split).

This works out what that means for the rows already written, and does it. It
reads and writes with plain SQL on a connection, so the migration that applies
it (`migrations/versions/f2a7c9d41e63_only_the_bank_makes_an_expense.py`) and
the read-only dry run behind the door (`/api/guidance/books/carryover`) are the
same code and cannot disagree. The migration imports this module: do not
remove or rename it.

What it does, line by line:

  - A "covered" bank line whose vendor rows hold the charge: those rows'
    expenses become the line's shares (`expenses.bank_line_id`). Nothing is
    added, removed or re-dated, so no total moves.
  - Several "covered" lines that pay one vendor period between them (Railway
    billed March 2026 as $9.75 and $5.00 a day apart): each line takes its
    share of every row of that period, and the shares add up to what the
    old rows held, on the same dates, so nothing moves.
  - A bank line booked as a plain expense for a charge the vendor sync had
    ALSO booked: the same money twice. The line takes the vendor's expenses as
    its shares and its own expense goes, kept whole in `expense_corrections`.
    That and DECISIONS are the only things allowed to move a total, and each
    one is listed.
  - A "covered" line nothing stands for (the sync wrote no expense for it):
    reported and left alone unless DECISIONS names it. Booking it would raise
    a total, which is Michael's call, not a migration's.

DECISIONS are his answers, each matched by line id AND amount AND date, so on
any database but production's they match nothing and do nothing.

`plan(conn)` changes nothing and returns the whole report, totals before and
after per company and year included. `apply(conn)` does it and returns the
same report; it raises before writing if a total would move for any other
reason. `undo(conn)` puts it back for the migration's downgrade.
"""
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

_NONWORD = re.compile(r"[^A-Z0-9]+")
TAG = "finances item 5"

# Michael, 2026-11-04, asked about the one covered charge nothing booked: the
# $10.66 Claude charge of 2026-10-17 on Built by Bean's bank is EntertainHQ's.
DECISIONS = [
    {"line_id": 45, "amount": 10.66, "date": "2026-10-17", "company": "EntertainHQ",
     "why": "Michael, 2026-11-04: EntertainHQ's own Claude plan, paid from Built by Bean's bank"},
]


def _norm(value):
    return " ".join(_NONWORD.sub(" ", (value or "").upper()).split())


def _d(value):
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _rows(conn, sql, **params):
    return [dict(r._mapping) for r in conn.execute(text(sql), params)]


def _families(conn):
    """business id -> (root id, root name), a DBA folded into its company."""
    biz = {r["id"]: r for r in _rows(conn, "SELECT id, name, short_name, parent_id, sales_source FROM businesses")}
    out = {}
    for bid, row in biz.items():
        root = row["parent_id"] or bid
        out[bid] = (root, (biz.get(root) or row)["name"])
    roots = sorted((r for r in biz.values() if r["parent_id"] is None), key=lambda r: r["id"])
    home = next((r["id"] for r in roots if r["sales_source"] == "board"), roots[0]["id"] if roots else None)
    return out, home, biz


def _totals(conn, families, removed=()):
    """Each company's expenses by year, as the Books read them."""
    removed = set(removed)
    totals = defaultdict(lambda: defaultdict(float))
    for row in _rows(conn, "SELECT id, amount, date, business_id FROM expenses"):
        if row["id"] in removed:
            continue
        _, name = families.get(row["business_id"], (None, "No company"))
        totals[name][_d(row["date"]).year] += row["amount"] or 0.0
    return {name: {year: round(v, 2) for year, v in sorted(years.items())}
            for name, years in sorted(totals.items())}


def _amount(entry):
    return round(entry["allocated_amount"] or 0.0, 2)


def _match(line, entries, claimed):
    """The vendor rows that hold this charge, as bank_feed.booked_by_sync
    reads them (one row for the amount, or one period's rows adding up to
    it), nearest period first, using only expenses no other line has taken.
    Returns (entries, had_any_rows)."""
    target = round(-line["amount"], 2)
    when = _d(line["occurred_on"])
    window = [e for e in entries
              if _d(e["period_start"]) <= when + timedelta(days=5)
              and _d(e["period_end"]) >= when - timedelta(days=45)]
    if not window:
        return None, False

    def free(group):
        return all(e["expense_id"] is None or e["expense_id"] not in claimed for e in group)

    def distance(group):
        return min(abs((_d(e["period_end"]) - when).days) for e in group)

    candidates = [[e] for e in window if abs(_amount(e) - target) < 0.005]
    periods = defaultdict(list)
    for e in window:
        periods[(e["period_start"], e["period_end"])].append(e)
    candidates += [g for g in periods.values()
                   if len(g) > 1 and abs(round(sum(_amount(e) for e in g), 2) - target) < 0.005]
    candidates = [g for g in candidates if free(g)]
    if not candidates:
        return None, True
    return min(candidates, key=lambda g: (distance(g), min(e["id"] for e in g))), True


def _line_view(line, families):
    return {"line_id": line["id"], "date": str(_d(line["occurred_on"])),
            "amount": round(-line["amount"], 2), "counterparty": line["counterparty"] or "",
            "company": families.get(line["business_id"], (None, "?"))[1]}


def plan(conn):
    families, home, businesses = _families(conn)
    home_family = {bid for bid, (root, _) in families.items() if root == home}
    providers = {p["id"]: p for p in _rows(conn, "SELECT id, name, display_name, is_active, "
                                                 "account_client_id, account_business_id FROM service_providers")}
    rules = _rows(conn, "SELECT id, pattern, disposition, provider_id, business_id FROM vendor_rules")
    entries_by_provider = defaultdict(list)
    for e in _rows(conn, "SELECT id, provider_id, expense_id, period_start, period_end, allocated_amount "
                         "FROM service_cost_entries ORDER BY id"):
        entries_by_provider[e["provider_id"]].append(e)
    vendor_expenses = {e["expense_id"] for es in entries_by_provider.values() for e in es if e["expense_id"]}
    expenses = {r["id"]: r for r in _rows(conn, "SELECT id, amount, date, business_id, description FROM expenses")}

    def ours(pid):
        p = providers.get(pid)
        return bool(p and p["is_active"] and p["account_client_id"] is None and p["account_business_id"] is None)

    claimed = set()
    links, holes, mismatches, doubles = [], [], [], []

    covered = _rows(conn, """
        SELECT t.id, t.amount, t.occurred_on, t.counterparty, t.description, t.business_id,
               t.expense_id, t.disposition, r.provider_id, r.business_id AS rule_business_id
        FROM bank_transactions t JOIN vendor_rules r ON r.id = t.rule_id
        WHERE t.disposition = 'covered' AND t.status = 'sent' AND t.amount < 0
        ORDER BY t.occurred_on, t.id""")
    for line in covered:
        group, any_rows = _match(line, entries_by_provider.get(line["provider_id"], []), claimed)
        view = _line_view(line, families)
        view["vendor"] = (providers.get(line["provider_id"]) or {}).get("display_name") or ""
        view["provider_id"] = line["provider_id"]
        if group is None:
            (mismatches if any_rows else holes).append(view)
            continue
        parts = [e["expense_id"] for e in group if e["expense_id"]]
        if len(parts) != len(group):
            view["entries_without_expense"] = [e["id"] for e in group if not e["expense_id"]]
            holes.append(view)
            continue
        claimed.update(parts)
        view["parts"] = parts
        links.append(view)

    # Several lines paying one period between them.
    shared, left = [], []
    by_provider = defaultdict(list)
    for m in mismatches:
        by_provider[m["provider_id"]].append(m)
    for pid, lines in by_provider.items():
        periods = defaultdict(list)
        for e in entries_by_provider.get(pid, []):
            periods[(_d(e["period_start"]), _d(e["period_end"]))].append(e)
        done = set()
        for (start, end), group in sorted(periods.items()):
            if any(not e["expense_id"] or e["expense_id"] in claimed for e in group):
                continue
            near = [m for m in lines if m["line_id"] not in done
                    and start - timedelta(days=5) <= _d(m["date"]) <= end + timedelta(days=45)]
            total = round(sum(_amount(e) for e in group), 2)
            if len(near) > 1 and abs(round(sum(m["amount"] for m in near), 2) - total) < 0.005:
                shared.append({"lines": near, "parts": [e["expense_id"] for e in group], "total": total,
                               "period": f"{start} to {end}", "vendor": near[0]["vendor"]})
                claimed.update(e["expense_id"] for e in group)
                done.update(m["line_id"] for m in near)
        left += [m for m in lines if m["line_id"] not in done]
    mismatches = left

    decided = []
    for d in DECISIONS:
        hit = [m for m in mismatches + holes if m["line_id"] == d["line_id"]
               and abs(m["amount"] - d["amount"]) < 0.005 and m["date"] == d["date"]]
        company = next((b for b in sorted(businesses.values(), key=lambda b: b["id"])
                        if b["parent_id"] is None and
                        ((b["short_name"] or "").lower().startswith(d["company"].lower())
                         or (b["name"] or "").lower().startswith(d["company"].lower()))), None)
        if hit and company:
            decided.append(dict(hit[0], business_id=company["id"], company=company["name"], why=d["why"]))
            mismatches = [m for m in mismatches if m["line_id"] != d["line_id"]]
            holes = [h for h in holes if h["line_id"] != d["line_id"]]

    # A plain expense line for a charge a vendor sync booked as well. Only for
    # a vendor whose rows wrote expenses in the home company's books, and only
    # where the line names that vendor the way its covered rule does.
    patterns = defaultdict(set)
    for r in rules:
        if r["disposition"] == "covered" and r["provider_id"] and ours(r["provider_id"]):
            pat = _norm(r["pattern"])
            if pat:
                patterns[r["provider_id"]].add(pat)
    plain = _rows(conn, """
        SELECT id, amount, occurred_on, counterparty, description, business_id, expense_id
        FROM bank_transactions
        WHERE disposition = 'expense' AND status = 'sent' AND amount < 0 AND expense_id IS NOT NULL
        ORDER BY occurred_on, id""")
    for line in plain:
        if line["expense_id"] in vendor_expenses:
            continue
        own = expenses.get(line["expense_id"])
        if own is None or own["business_id"] not in home_family:
            continue
        hay = f" {_norm(line['counterparty'])} | {_norm(line['description'])} "
        for pid, pats in patterns.items():
            if not any(f" {p} " in hay or (len(p) >= 6 and p in hay) for p in pats):
                continue
            group, _ = _match(line, entries_by_provider.get(pid, []), claimed)
            if group is None or not all(e["expense_id"] for e in group):
                continue
            parts = [e["expense_id"] for e in group]
            claimed.update(parts)
            view = _line_view(line, families)
            view.update({"vendor": providers[pid]["display_name"], "parts": parts,
                         "removed_expense": line["expense_id"], "provider_id": pid})
            doubles.append(view)
            break

    before = _totals(conn, families)
    after = _totals(conn, families, removed=[d["removed_expense"] for d in doubles])
    for d in decided:
        year = int(d["date"][:4])
        after.setdefault(d["company"], {})
        after[d["company"]][year] = round(after[d["company"]].get(year, 0.0) + d["amount"], 2)
    moves = []
    for name in sorted(set(before) | set(after)):
        for year in sorted(set(before.get(name, {})) | set(after.get(name, {}))):
            b, a = before.get(name, {}).get(year, 0.0), after.get(name, {}).get(year, 0.0)
            if abs(a - b) >= 0.005:
                moves.append({"company": name, "year": year, "before": b, "after": a,
                              "change": round(a - b, 2)})
    explained = defaultdict(float)
    for d in doubles:
        explained[(d["company"], int(d["date"][:4]))] -= d["amount"]
    for d in decided:
        explained[(d["company"], int(d["date"][:4]))] += d["amount"]
    unexplained = [m for m in moves
                   if abs(round(explained[(m["company"], m["year"])], 2) - m["change"]) >= 0.005]
    return {"links": links, "shared": shared, "decided": decided, "doubles": doubles,
            "holes": holes, "mismatches": mismatches,
            "totals_before": before, "totals_after": after, "moves": moves,
            "unexplained_moves": unexplained,
            "vendor_expenses_kept": len(vendor_expenses)}


def _note(conn, action, expense_id, amount, when, reason, snapshot):
    conn.execute(text("INSERT INTO expense_corrections (action, expense_id, amount, reason, snapshot_json, corrected_at) "
                      "VALUES (:a, :e, :m, :r, :s, :t)"),
                 {"a": action, "e": expense_id, "m": amount or 0.0, "r": reason[:300],
                  "s": json.dumps(snapshot), "t": when})


def _insert_like(conn, old, amount, line_id, entry_id):
    """A new expense row in the shape of `old`, for a bank line's share."""
    params = {"a": amount, "d": _d(old["date"]), "b": old.get("business_id"),
              "c": old.get("client_id"), "p": old.get("project_id"), "cat": old.get("category") or "misc",
              "w": old.get("description") or "", "pb": old.get("paid_by"), "l": line_id, "ce": entry_id,
              "t": datetime.now(timezone.utc).replace(tzinfo=None), "f": False}
    sql = ("INSERT INTO expenses (amount, date, business_id, client_id, project_id, category, description, "
           "paid_by, bank_line_id, cost_entry_id, created_at, is_recurring, sales_tax_remitted) "
           "VALUES (:a, :d, :b, :c, :p, :cat, :w, :pb, :l, :ce, :t, :f, 0)")
    if conn.dialect.name == "postgresql":
        return conn.execute(text(sql + " RETURNING id"), params).scalar()
    conn.execute(text(sql), params)
    return conn.execute(text("SELECT max(id) FROM expenses")).scalar()


def _largest(conn, ids):
    rows = _rows(conn, "SELECT id, amount FROM expenses WHERE id IN (%s)" % ",".join(str(int(i)) for i in ids))
    return max(rows, key=lambda r: (r["amount"] or 0.0, -r["id"]))["id"] if rows else None


def apply(conn):
    """Do what plan() says. Raises before writing anything if a total would
    move for any reason but a listed double count or one of DECISIONS."""
    report = plan(conn)
    if report["unexplained_moves"]:
        raise RuntimeError("A company's totals would move for a reason that is not a double "
                           f"count: {json.dumps(report['unexplained_moves'])}")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    owners = {r["id"]: r for r in _rows(conn, "SELECT t.id, c.kind, c.owner_name FROM bank_transactions t "
                                              "JOIN bank_connections c ON c.id = t.connection_id")}
    entry_of = {r["expense_id"]: r["id"] for r in _rows(conn, "SELECT id, expense_id FROM service_cost_entries "
                                                            "WHERE expense_id IS NOT NULL")}

    def take(line_id, eid):
        conn.execute(text("UPDATE expenses SET bank_line_id = :l, cost_entry_id = :c WHERE id = :e"),
                     {"l": line_id, "c": entry_of.get(eid), "e": eid})
        who = owners.get(line_id) or {}
        if who.get("kind") == "personal":
            # The owner's card paid it, so the owner put that money in
            # (books_service.owner_money_between reads paid_by).
            conn.execute(text("UPDATE expenses SET paid_by = :w WHERE id = :e AND (paid_by IS NULL OR paid_by = '')"),
                         {"w": who.get("owner_name") or "Owner not named", "e": eid})

    def point(line_id, ids, disposition="split"):
        conn.execute(text("UPDATE bank_transactions SET disposition = :d, expense_id = :e WHERE id = :l"),
                     {"d": disposition, "e": _largest(conn, ids), "l": line_id})

    for link in report["links"]:
        for eid in link["parts"]:
            take(link["line_id"], eid)
        point(link["line_id"], link["parts"])

    for group in report["shared"]:
        legacy = {r["id"]: r for r in _rows(conn, "SELECT * FROM expenses WHERE id IN (%s)"
                                            % ",".join(str(int(i)) for i in group["parts"]))}
        for n, m in enumerate(sorted(group["lines"], key=lambda m: -m["amount"])):
            share = m["amount"] / group["total"]
            amounts = {eid: round((legacy[eid]["amount"] or 0.0) * share, 2) for eid in group["parts"]}
            gap = round(m["amount"] - sum(amounts.values()), 2)
            if gap:
                top = max(amounts, key=lambda k: amounts[k])
                amounts[top] = round(amounts[top] + gap, 2)
            mine = []
            for eid in group["parts"]:
                old = legacy[eid]
                if n == 0:
                    conn.execute(text("UPDATE expenses SET amount = :a WHERE id = :e"), {"a": amounts[eid], "e": eid})
                    _note(conn, "changed", eid, old["amount"], now,
                          f"{TAG}: ${old['amount']:.2f} became bank line {m['line_id']}'s share",
                          {"amount": old["amount"]})
                    take(m["line_id"], eid)
                    mine.append(eid)
                else:
                    new_id = _insert_like(conn, old, amounts[eid], m["line_id"], entry_of.get(eid))
                    _note(conn, "added", new_id, amounts[eid], now,
                          f"{TAG}: bank line {m['line_id']}'s share of {group['vendor']} {group['period']}", {})
                    take(m["line_id"], new_id)
                    mine.append(new_id)
            point(m["line_id"], mine)

    for d in report["decided"]:
        rule = _rows(conn, "SELECT r.category, r.vendor FROM bank_transactions t LEFT JOIN vendor_rules r "
                           "ON r.id = t.rule_id WHERE t.id = :l", l=d["line_id"])
        category = (rule[0]["category"] if rule and rule[0]["category"] else "misc")
        vendor = (rule[0]["vendor"] if rule and rule[0]["vendor"] else "") or d["vendor"] or d["counterparty"]
        new_id = _insert_like(conn, {"business_id": d["business_id"], "category": category,
                                     "description": vendor, "date": d["date"]}, d["amount"], d["line_id"], None)
        _note(conn, "added", new_id, d["amount"], now, f"{TAG}: {d['why']}", {})
        conn.execute(text("UPDATE bank_transactions SET disposition = 'expense', expense_id = :e, rule_id = NULL, "
                          "decided_at = :t WHERE id = :l"), {"e": new_id, "t": now, "l": d["line_id"]})

    for d in report["doubles"]:
        gone = _rows(conn, "SELECT * FROM expenses WHERE id = :e", e=d["removed_expense"])
        for eid in d["parts"]:
            take(d["line_id"], eid)
        point(d["line_id"], d["parts"])
        # A receipt the bank's own row carried goes to the vendor's row it
        # duplicated, so the charge keeps its proof.
        if gone and gone[0].get("receipt_filename"):
            conn.execute(text("UPDATE expenses SET receipt_filename = :f, receipt_original_name = :n "
                              "WHERE id = :e AND receipt_filename IS NULL"),
                         {"f": gone[0]["receipt_filename"], "n": gone[0].get("receipt_original_name"),
                          "e": d["parts"][0]})
        conn.execute(text("UPDATE receipts SET expense_id = :p WHERE expense_id = :e"),
                     {"p": d["parts"][0], "e": d["removed_expense"]})
        snapshot = {k: (str(v) if isinstance(v, (date, datetime)) else v)
                    for k, v in (gone[0] if gone else {}).items()}
        _note(conn, "removed", d["removed_expense"], d["amount"], now,
              f"{TAG}: booked twice, by bank line {d['line_id']} and the {d['vendor']} sync, "
              f"${d['amount']:,.2f} on {d['date']}. The line keeps the vendor's split.", snapshot)
        conn.execute(text("DELETE FROM expenses WHERE id = :e"), {"e": d["removed_expense"]})

    # A covered line nothing stood for waits on review rather than booking
    # itself the next night: a total that rises is Michael's call.
    for left in report["holes"] + report["mismatches"]:
        conn.execute(text("UPDATE bank_transactions SET disposition = 'review' WHERE id = :l"), {"l": left["line_id"]})
    conn.execute(text("UPDATE bank_transactions SET disposition = 'split' WHERE disposition = 'covered'"))
    conn.execute(text("UPDATE vendor_rules SET disposition = 'split' WHERE disposition = 'covered'"))
    return report


def undo(conn):
    """Put back what apply() changed: the shares it added go, the amounts it
    changed return, the double counts it removed come back whole, and every
    split line reads covered again with its expense links as they were."""
    for row in _rows(conn, "SELECT * FROM expense_corrections WHERE reason LIKE :t ORDER BY id DESC", t=TAG + "%"):
        snap = json.loads(row["snapshot_json"] or "{}")
        if row["action"] == "added":
            conn.execute(text("UPDATE bank_transactions SET expense_id = NULL WHERE expense_id = :e"),
                         {"e": row["expense_id"]})
            conn.execute(text("DELETE FROM expenses WHERE id = :e"), {"e": row["expense_id"]})
        elif row["action"] == "changed":
            conn.execute(text("UPDATE expenses SET amount = :a WHERE id = :e"),
                         {"a": snap.get("amount"), "e": row["expense_id"]})
        elif row["action"] == "removed" and snap:
            cols = [k for k in snap if k not in ("id", "bank_line_id", "cost_entry_id")]
            conn.execute(text("INSERT INTO expenses (id, %s) VALUES (:id, %s)" % (
                ", ".join(cols), ", ".join(":" + c for c in cols))), snap)
        conn.execute(text("DELETE FROM expense_corrections WHERE id = :i"), {"i": row["id"]})
    for d in DECISIONS:
        conn.execute(text("UPDATE bank_transactions SET disposition = 'review', decided_at = NULL "
                          "WHERE id = :l AND expense_id IS NULL AND disposition = 'expense'"), {"l": d["line_id"]})
    conn.execute(text("UPDATE bank_transactions SET disposition = 'covered', expense_id = NULL "
                      "WHERE disposition = 'split'"))
    conn.execute(text("UPDATE vendor_rules SET disposition = 'covered' WHERE disposition = 'split'"))


def summary(report):
    """The report in a few lines, for the deploy log and the door."""
    out = [f"{len(report['links'])} covered bank lines take the vendor's expenses as their shares; "
           f"{report['vendor_expenses_kept']} vendor-written expenses carried over."]
    for g in report.get("shared", []):
        out.append(f"{len(g['lines'])} charges share {g['vendor']} {g['period']} (${g['total']:,.2f}): "
                   + ", ".join(f"line {m['line_id']} ${m['amount']:,.2f}" for m in g["lines"]))
    for d in report.get("decided", []):
        out.append(f"Booked as Michael decided: {d['company']} {d['date']} {d['vendor']} ${d['amount']:,.2f} "
                   f"(bank line {d['line_id']})")
    for d in report["doubles"]:
        out.append(f"Double count removed: {d['company']} {d['date']} {d['vendor']} ${d['amount']:,.2f} "
                   f"(bank line {d['line_id']}, expense {d['removed_expense']})")
    for h in report["holes"]:
        out.append(f"Covered but in nobody's books, left alone: {h['company']} {h['date']} {h['vendor']} "
                   f"${h['amount']:,.2f} (bank line {h['line_id']})")
    for m in report["mismatches"]:
        out.append(f"Covered, vendor rows do not add up to it, left alone: {m['company']} {m['date']} "
                   f"{m['vendor']} ${m['amount']:,.2f} (bank line {m['line_id']})")
    for m in report["moves"]:
        out.append(f"{m['company']} {m['year']}: ${m['before']:,.2f} -> ${m['after']:,.2f} ({m['change']:+,.2f})")
    return out
