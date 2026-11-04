"""The corrections Michael approved one by one, reviewing receipts on 2026-11-03

Looking for a receipt for each expense found rows with no receipt to find:

  - Built by Bean: $261.27 of charges entered by hand on top of the vendor sync
    that already had them (Railway, Claude, Cloudflare), or on top of the real
    charge (the $20 domain row beside its $14 charge, Twilio items paid out of a
    balance already booked, a second row for February's ChatGPT).
  - $107.69 "Cambridge membership" was a RuneScape subscription from Jagex, paid
    on the company's debit card. Personal, so it is money the owner took out.
  - EntertainHQ's $213.20 row was the same charge as Built by Bean's own Claude
    plan, while its real plan ($105.40, $113.69) and Railway ($5.33, $15.83,
    $21.32) sat on the card marked as booked by a sync that never saw them.
  - One receipt on the wrong vendor's row.

Every row is matched on its id AND its amount AND its words, because the ids are
production's: on any other database nothing matches and nothing happens. What is
removed is kept whole in expense_corrections, and downgrade puts it all back.

Revision ID: c3e7a1f90b42
Revises: a1f6c3e8d204
Create Date: 2026-11-03
"""
import json
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "c3e7a1f90b42"
down_revision = "a1f6c3e8d204"
branch_labels = None
depends_on = None

DOUBLE_RAILWAY = "Railway's bill is already on the books from its vendor sync, which matches the card."
REMOVE = [
    (1, 21.32, "claude code", "Same charge as the Claude vendor sync row of Mar 26. One Anthropic invoice."),
    (2, 86.75, "claude code", "Same charge as the Claude vendor sync row of Mar 28. One Anthropic invoice."),
    (3, 9.75, "railway - hosting", DOUBLE_RAILWAY),
    (4, 5.00, "railway - hosting", DOUBLE_RAILWAY),
    (12, 20.00, "railway - hosting", DOUBLE_RAILWAY),
    (13, 20.00, "railway - hosting", DOUBLE_RAILWAY),
    (14, 20.00, "railway - hosting", DOUBLE_RAILWAY),
    (46, 20.00, "railway - hosting", DOUBLE_RAILWAY),
    (170, 11.17, "masterbytrade.com", "Same order as the Cloudflare vendor sync row, which now carries the Piped tag."),
    (6, 1.50, "twilio phone number", "Paid out of the $20 Twilio balance already booked on Apr 4. No card charge."),
    (7, 4.50, "twilio, phone number", "Paid out of the $20 Twilio balance already booked on Apr 4. No card charge."),
    (8, 20.00, "builtbybeans.com", "The card was charged $14.00, already booked. $20.00 is the renewal price."),
    (110, 21.28, "chatgpt plus", "Same charge as the Coding Agent row of Feb 17. OpenAI shows one charge that month."),
    (173, 213.20, "claude, product", "Same charge as Built by Bean's Claude plan. EntertainHQ's own plan is booked instead."),
]
CAMBRIDGE = (199, 107.69, "cambridge", "RuneScape subscription from Jagex on the company's card. Personal: a draw.")
WRONG_RECEIPT = (5, "Invoice-SKQBNJUH-0002", "A Railway invoice was on this Twilio row.")
TAG_FROM, TAG_TO = 170, 171
ADD = [
    ("anthropic", -105.40, "2026-10-17", "Claude, EntertainHQ Max plan", "ai_services"),
    ("anthropic", -113.69, "2026-10-20", "Claude, EntertainHQ Max plan", "ai_services"),
    ("railway", -5.33, "2026-09-16", "Railway, EntertainHQ workspace", "hosting"),
    ("railway", -15.83, "2026-09-17", "Railway, EntertainHQ workspace", "hosting"),
    ("railway", -21.32, "2026-10-16", "Railway, EntertainHQ workspace", "hosting"),
]
ADD_REASON = "On the card, marked as booked by a vendor sync that only reads Built by Bean's account."


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _record(bind, action, expense_id, amount, reason, snapshot):
    bind.execute(sa.text(
        "INSERT INTO expense_corrections (action, expense_id, amount, reason, snapshot_json, corrected_at) "
        "VALUES (:a, :e, :m, :r, :s, :t)"),
        {"a": action, "e": expense_id, "m": amount, "r": reason, "s": json.dumps(snapshot, default=str), "t": _now()})


def _row(bind, expense_id, amount, words):
    row = bind.execute(sa.text("SELECT * FROM expenses WHERE id = :e"), {"e": expense_id}).mappings().first()
    if row is None or abs((row["amount"] or 0.0) - amount) >= 0.005 or words not in (row["description"] or "").lower():
        return None
    return dict(row)


def _take_off(bind, row, reason, extra=None):
    expense_id = row["id"]
    receipts = [r[0] for r in bind.execute(sa.text("SELECT id FROM receipts WHERE expense_id = :e"),
                                           {"e": expense_id}).fetchall()]
    # Let the hunt use these on the row that stays.
    bind.execute(sa.text("UPDATE receipts SET expense_id = NULL, status = 'unmatched' WHERE expense_id = :e"),
                 {"e": expense_id})
    bind.execute(sa.text("DELETE FROM expenses WHERE id = :e"), {"e": expense_id})
    _record(bind, "removed", expense_id, row["amount"], reason, {"row": row, "receipts": receipts, **(extra or {})})
    print(f"corrections: removed expense {expense_id}, {row['amount']:.2f}")


def upgrade():
    bind = op.get_bind()
    if "expense_corrections" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "expense_corrections",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("action", sa.String(12), nullable=False),
            sa.Column("expense_id", sa.Integer(), nullable=False),
            sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
            sa.Column("reason", sa.String(300), nullable=False, server_default=""),
            sa.Column("snapshot_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("corrected_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_expense_corrections_expense_id", "expense_corrections", ["expense_id"])

    # The domain's tag first, while the row that carries it is still there. A
    # sync rewrites its row's client and project from a mapping every night, so
    # the tag has to live on a mapping or it is gone by morning.
    source = bind.execute(sa.text("SELECT client_id, project_id FROM expenses WHERE id = :e AND amount = 11.17 "
                                  "AND lower(description) LIKE '%masterbytrade%'"), {"e": TAG_FROM}).mappings().first()
    entry = bind.execute(sa.text("SELECT id, provider_id, resource_identifier, mapping_id, description "
                                 "FROM service_cost_entries WHERE expense_id = :e"), {"e": TAG_TO}).mappings().first()
    if source is not None and entry is not None and entry["mapping_id"] is None:
        mapping = bind.execute(sa.text(
            "INSERT INTO service_mappings (provider_id, resource_identifier, resource_label, client_id, project_id, "
            "split_percentage, is_active, created_at) VALUES (:p, :r, :l, :c, :j, 100.0, :y, :t) RETURNING id"),
            {"p": entry["provider_id"], "r": entry["resource_identifier"], "l": "masterbytrade.com",
             "c": source["client_id"], "j": source["project_id"], "y": True, "t": _now()}).scalar()
        clean = (entry["description"] or "").replace(" [unallocated]", "")
        bind.execute(sa.text("UPDATE service_cost_entries SET mapping_id = :m, description = :d WHERE id = :i"),
                     {"m": mapping, "d": clean, "i": entry["id"]})
        bind.execute(sa.text("UPDATE expenses SET client_id = :c, project_id = :j, description = :d WHERE id = :e"),
                     {"c": source["client_id"], "j": source["project_id"], "d": clean, "e": TAG_TO})
        _record(bind, "changed", TAG_TO, 11.17, "Took the Piped tag from the row it duplicated.",
                {"mapping_id": mapping, "entry_id": entry["id"], "description": entry["description"]})

    for expense_id, amount, words, reason in REMOVE:
        row = _row(bind, expense_id, amount, words)
        if row is None:
            continue
        lines = bind.execute(sa.text("SELECT count(*) FROM bank_transactions WHERE expense_id = :e"),
                             {"e": expense_id}).scalar()
        if lines:
            # A bank line stands for it, so it is a real charge after all.
            print(f"corrections: left expense {expense_id}, a bank line stands for it")
            continue
        _take_off(bind, row, reason)

    expense_id, amount, words, reason = CAMBRIDGE
    row = _row(bind, expense_id, amount, words)
    if row is not None:
        line = bind.execute(sa.text("SELECT id, disposition, rule_id, decided_at FROM bank_transactions "
                                    "WHERE expense_id = :e"), {"e": expense_id}).mappings().first()
        if line is not None:
            bind.execute(sa.text("UPDATE bank_transactions SET disposition = 'draw', owner_name = 'Michael Bean', "
                                 "expense_id = NULL, rule_id = NULL, decided_at = :t WHERE id = :i"),
                         {"t": _now(), "i": line["id"]})
            _take_off(bind, row, reason, {"line": dict(line)})

    expense_id, name, reason = WRONG_RECEIPT
    row = bind.execute(sa.text("SELECT id, amount, receipt_filename, receipt_original_name FROM expenses WHERE id = :e"),
                       {"e": expense_id}).mappings().first()
    if row is not None and (row["receipt_original_name"] or "").startswith(name):
        bind.execute(sa.text("UPDATE expenses SET receipt_filename = NULL, receipt_original_name = NULL WHERE id = :e"),
                     {"e": expense_id})
        bind.execute(sa.text("UPDATE receipts SET expense_id = NULL, status = 'unmatched' WHERE expense_id = :e"),
                     {"e": expense_id})
        _record(bind, "changed", expense_id, row["amount"], reason, dict(row))
        print(f"corrections: took the wrong receipt off expense {expense_id}")

    ehq = bind.execute(sa.text("SELECT id FROM businesses WHERE lower(name) LIKE 'entertainhq%' AND parent_id IS NULL "
                               "ORDER BY id")).scalar()
    if ehq is not None:
        for word, amount, day, description, category in ADD:
            for line in bind.execute(sa.text(
                    "SELECT t.id, t.counterparty, t.occurred_on, t.rule_id, t.decided_at, c.owner_name "
                    "FROM bank_transactions t LEFT JOIN bank_connections c ON c.id = t.connection_id "
                    "WHERE t.disposition = 'covered' AND t.expense_id IS NULL AND t.amount = :a"),
                    {"a": amount}).mappings().all():
                if word not in (line["counterparty"] or "").lower() or str(line["occurred_on"])[:10] != day:
                    continue
                new_id = bind.execute(sa.text(
                    "INSERT INTO expenses (amount, description, category, date, business_id, paid_by, created_at, "
                    "is_recurring, sales_tax_remitted) VALUES (:m, :d, :c, :w, :b, :p, :t, :r, 0) RETURNING id"),
                    {"m": round(-amount, 2), "d": description, "c": category, "w": day, "b": ehq,
                     "p": line["owner_name"] or None, "t": _now(), "r": False}).scalar()
                bind.execute(sa.text("UPDATE bank_transactions SET disposition = 'expense', expense_id = :e, "
                                     "rule_id = NULL, decided_at = :t WHERE id = :i"),
                             {"e": new_id, "t": _now(), "i": line["id"]})
                _record(bind, "added", new_id, round(-amount, 2), ADD_REASON,
                        {"line": line["id"], "rule_id": line["rule_id"], "decided_at": line["decided_at"]})
                print(f"corrections: added {-amount:.2f} to EntertainHQ's books")
                break


def downgrade():
    bind = op.get_bind()
    if "expense_corrections" not in sa.inspect(bind).get_table_names():
        return
    for row in bind.execute(sa.text("SELECT * FROM expense_corrections ORDER BY id DESC")).mappings().all():
        snap = json.loads(row["snapshot_json"] or "{}")
        if row["action"] == "added":
            bind.execute(sa.text("UPDATE bank_transactions SET disposition = 'covered', expense_id = NULL, "
                                 "rule_id = :r, decided_at = :d WHERE id = :i"),
                         {"r": snap.get("rule_id"), "d": snap.get("decided_at"), "i": snap.get("line")})
            bind.execute(sa.text("UPDATE receipts SET expense_id = NULL, status = 'unmatched' WHERE expense_id = :e"),
                         {"e": row["expense_id"]})
            bind.execute(sa.text("DELETE FROM expenses WHERE id = :e"), {"e": row["expense_id"]})
        elif row["action"] == "removed":
            values = snap["row"]
            names = list(values)
            bind.execute(sa.text(f"INSERT INTO expenses ({', '.join(names)}) "
                                 f"VALUES ({', '.join(':' + n for n in names)})"), values)
            for rid in snap.get("receipts") or []:
                bind.execute(sa.text("UPDATE receipts SET expense_id = :e, status = 'matched' WHERE id = :r"),
                             {"e": row["expense_id"], "r": rid})
            line = snap.get("line")
            if line:
                bind.execute(sa.text("UPDATE bank_transactions SET disposition = :s, owner_name = '', expense_id = :e, "
                                     "rule_id = :r, decided_at = :d WHERE id = :i"),
                             {"s": line["disposition"], "e": row["expense_id"], "r": line["rule_id"],
                              "d": line["decided_at"], "i": line["id"]})
        elif "mapping_id" in snap:
            bind.execute(sa.text("UPDATE service_cost_entries SET mapping_id = NULL, description = :d WHERE id = :i"),
                         {"d": snap["description"], "i": snap["entry_id"]})
            bind.execute(sa.text("UPDATE expenses SET client_id = NULL, project_id = NULL, description = :d WHERE id = :e"),
                         {"d": snap["description"], "e": row["expense_id"]})
            bind.execute(sa.text("DELETE FROM service_mappings WHERE id = :m"), {"m": snap["mapping_id"]})
        else:
            bind.execute(sa.text("UPDATE expenses SET receipt_filename = :f, receipt_original_name = :n WHERE id = :e"),
                         {"f": snap.get("receipt_filename"), "n": snap.get("receipt_original_name"),
                          "e": row["expense_id"]})
    op.drop_index("ix_expense_corrections_expense_id", table_name="expense_corrections")
    op.drop_table("expense_corrections")
