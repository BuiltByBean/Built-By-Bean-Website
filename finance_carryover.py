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
    expenses become the line's parts (`expenses.bank_line_id`). Nothing is
    added, removed or re-dated, so no total moves.
  - A bank line booked as a plain expense for a charge the vendor sync had
    ALSO booked: the same money twice. The line takes the vendor's expenses as
    its parts and its own expense goes, kept whole in `expense_corrections`.
    That is the only thing allowed to move a total, and each one is listed.
  - A "covered" line nothing stands for (the sync wrote no expense for it):
    reported as a hole and left alone. Booking it would raise a total, which is
    Michael's call, not a migration's.

`plan(conn)` changes nothing and returns the whole report, totals before and
after per company and year included. `apply(conn)` does it and returns the
same report.
"""
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

_NONWORD = re.compile(r"[^A-Z0-9]+")


def _norm(value):
    return " ".join(_NONWORD.sub(" ", (value or "").upper()).split())


def _d(value):
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _rows(conn, sql, **params):
    return [dict(r._mapping) for r in conn.execute(text(sql), params)]


def _has_column(conn, table, column):
    try:
        conn.execute(text(f"SELECT {column} FROM {table} WHERE 1=0"))
        return True
    except Exception:
        return False


def _families(conn):
    """business id -> (root id, root name), a DBA folded into its company."""
    biz = {r["id"]: r for r in _rows(conn, "SELECT id, name, parent_id, sales_source FROM businesses")}
    out = {}
    for bid, row in biz.items():
        root = row["parent_id"] or bid
        out[bid] = (root, (biz.get(root) or row)["name"])
    roots = sorted((r for r in biz.values() if r["parent_id"] is None), key=lambda r: r["id"])
    home = next((r["id"] for r in roots if r["sales_source"] == "board"), roots[0]["id"] if roots else None)
    return out, home


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

    candidates = [[e] for e in window if abs(round(e["allocated_amount"] or 0.0, 2) - target) < 0.005]
    periods = defaultdict(list)
    for e in window:
        periods[(e["period_start"], e["period_end"])].append(e)
    candidates += [g for g in periods.values()
                   if len(g) > 1 and abs(round(sum(round(e["allocated_amount"] or 0.0, 2) for e in g), 2) - target) < 0.005]
    candidates = [g for g in candidates if free(g)]
    if not candidates:
        return None, True
    return min(candidates, key=lambda g: (distance(g), min(e["id"] for e in g))), True


def _line_view(line, families):
    return {"line_id": line["id"], "date": str(_d(line["occurred_on"])),
            "amount": round(-line["amount"], 2), "counterparty": line["counterparty"] or "",
            "company": families.get(line["business_id"], (None, "?"))[1]}


def plan(conn):
    families, home = _families(conn)
    home_family = {bid for bid, (root, _) in families.items() if root == home}
    providers = {p["id"]: p for p in _rows(conn, "SELECT id, name, display_name, is_active, "
                                                 "account_client_id, account_business_id FROM service_providers")}
    rules = _rows(conn, "SELECT id, pattern, disposition, provider_id, business_id FROM vendor_rules")
    split_word = "covered"
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
        WHERE t.disposition = :d AND t.status = 'sent' AND t.amount < 0
        ORDER BY t.occurred_on, t.id""", d=split_word)
    for line in covered:
        group, any_rows = _match(line, entries_by_provider.get(line["provider_id"], []), claimed)
        view = _line_view(line, families)
        view["vendor"] = (providers.get(line["provider_id"]) or {}).get("display_name") or ""
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

    # A plain expense line for a charge a vendor sync booked as well. Only for
    # a vendor whose rows wrote expenses in the home company's books, and only
    # where the line names that vendor the way its split rule does.
    patterns = defaultdict(set)
    for r in rules:
        if r["disposition"] == split_word and r["provider_id"] and ours(r["provider_id"]):
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
    unexplained = [m for m in moves if abs(round(explained[(m["company"], m["year"])], 2) - m["change"]) >= 0.005]
    return {"links": links, "doubles": doubles, "holes": holes, "mismatches": mismatches,
            "totals_before": before, "totals_after": after, "moves": moves,
            "unexplained_moves": unexplained,
            "vendor_expenses_kept": len(vendor_expenses)}


def apply(conn):
    """Do what plan() says. Raises before writing anything if a total would
    move for any reason but a listed double count."""
    report = plan(conn)
    if report["unexplained_moves"]:
        raise RuntimeError("A company's totals would move for a reason that is not a double "
                           f"count: {json.dumps(report['unexplained_moves'])}")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for link in report["links"]:
        for eid in link["parts"]:
            conn.execute(text("UPDATE expenses SET bank_line_id = :l WHERE id = :e"), {"l": link["line_id"], "e": eid})
        main = _largest(conn, link["parts"])
        conn.execute(text("UPDATE bank_transactions SET disposition = 'split', expense_id = :e WHERE id = :l"),
                     {"e": main, "l": link["line_id"]})
    for d in report["doubles"]:
        gone = _rows(conn, "SELECT * FROM expenses WHERE id = :e", e=d["removed_expense"])
        for eid in d["parts"]:
            conn.execute(text("UPDATE expenses SET bank_line_id = :l WHERE id = :e"), {"l": d["line_id"], "e": eid})
        conn.execute(text("UPDATE bank_transactions SET disposition = 'split', expense_id = :e WHERE id = :l"),
                     {"e": _largest(conn, d["parts"]), "l": d["line_id"]})
        # A receipt the bank's own row carried goes to the vendor's row it
        # duplicated, so the charge keeps its proof.
        if gone and gone[0].get("receipt_filename"):
            conn.execute(text("UPDATE expenses SET receipt_filename = :f, receipt_original_name = :n "
                              "WHERE id = :e AND receipt_filename IS NULL"),
                         {"f": gone[0]["receipt_filename"], "n": gone[0].get("receipt_original_name"),
                          "e": d["parts"][0]})
        conn.execute(text("UPDATE receipts SET expense_id = :p WHERE expense_id = :e"),
                     {"p": d["parts"][0], "e": d["removed_expense"]})
        snapshot = json.dumps({k: (str(v) if isinstance(v, (date, datetime)) else v)
                               for k, v in (gone[0] if gone else {}).items()})
        conn.execute(text("INSERT INTO expense_corrections (action, expense_id, amount, reason, snapshot_json, corrected_at) "
                          "VALUES ('removed', :e, :a, :r, :s, :t)"),
                     {"e": d["removed_expense"], "a": d["amount"], "s": snapshot, "t": now,
                      "r": f"Booked twice: bank line {d['line_id']} and the {d['vendor']} sync both booked "
                           f"${d['amount']:,.2f} on {d['date']}. The bank line keeps the vendor's split."})
        conn.execute(text("DELETE FROM expenses WHERE id = :e"), {"e": d["removed_expense"]})
    conn.execute(text("UPDATE bank_transactions SET disposition = 'split' WHERE disposition = 'covered'"))
    conn.execute(text("UPDATE vendor_rules SET disposition = 'split' WHERE disposition = 'covered'"))
    return report


def _largest(conn, ids):
    rows = _rows(conn, "SELECT id, amount FROM expenses WHERE id IN (%s)" % ",".join(str(int(i)) for i in ids))
    return max(rows, key=lambda r: (r["amount"] or 0.0, -r["id"]))["id"] if rows else None


def summary(report):
    """The report in a few lines, for the deploy log and the door."""
    out = [f"{len(report['links'])} covered bank lines take the vendor's expenses as their parts; "
           f"{report['vendor_expenses_kept']} vendor-written expenses carried over unchanged."]
    for d in report["doubles"]:
        out.append(f"Double count removed: {d['company']} {d['date']} {d['vendor']} ${d['amount']:,.2f} "
                   f"(bank line {d['line_id']}, expense {d['removed_expense']})")
    for h in report["holes"]:
        out.append(f"Covered but in nobody's books: {h['company']} {h['date']} {h['vendor']} ${h['amount']:,.2f} "
                   f"(bank line {h['line_id']})")
    for m in report["mismatches"]:
        out.append(f"Covered, vendor rows do not add up to it: {m['company']} {m['date']} {m['vendor']} "
                   f"${m['amount']:,.2f} (bank line {m['line_id']})")
    for m in report["moves"]:
        out.append(f"{m['company']} {m['year']}: ${m['before']:,.2f} -> ${m['after']:,.2f} ({m['change']:+,.2f})")
    return out
