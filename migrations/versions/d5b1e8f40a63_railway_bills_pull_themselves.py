"""Railway's bills pull themselves, and EntertainHQ's are its own

Railway's API does report money, to an account token: every invoice with its
period and total, and each project's usage for any range. The board's Railway
sync now records each finished month's bill and splits it across projects by
what each used (service_costs_service._sync_railway), so nobody types them.

Michael, 2026-11-01: "I have a separate pro account for entertainhq
specifically on railway now", one login with two workspaces, and EntertainHQ
LLC pays for its own. So:

  - service_providers.account_business_id: an account another of Michael's
    businesses pays for. Its costs are recorded and attributed, never booked
    as Built by Bean's expenses.
  - the Railway provider that exists is told which workspace it is (Built by
    Bean's), and a second, "Railway (EntertainHQ)", is EntertainHQ's.
  - September and October, which Needs attention was asking for, are recorded
    from the figures Railway's API gave on 2026-11-01, with the note the sync
    writes, so the sync owns them and corrects them if Railway ever restates.
    The per-project split for those months follows on the first pull with an
    account token.

The workspace ids are Railway's and not secret. No token is written here: the
account token is Michael's to make and paste into each provider.

Revision ID: d5b1e8f40a63
Revises: c3e9f2a61d84
"""
import json
from datetime import date, datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "d5b1e8f40a63"
down_revision = "c3e9f2a61d84"
branch_labels = None
depends_on = None


FK = "fk_service_providers_account_business_id"
BBB_WORKSPACE = ("74c67a5d-b5a5-49dc-aa39-36f378ddc9f8", "builtbybean's Projects")
EHQ_WORKSPACE = ("edde8aea-147d-4851-9b62-f4d068ad2066", "EntertainHQ")
EHQ_NAME = "Railway (EntertainHQ)"

# As Railway's API answered on 2026-11-01, filed under the month each period
# starts, with the sync's own note.
BILLS = {
    "bbb": [
        (date(2026, 9, 1), 43.71, "From Railway: 1 invoice, Sep 01 to Oct 01"),
        (date(2026, 10, 1), 52.38, "From Railway: 1 invoice, Oct 01 to Nov 01"),
    ],
    "ehq": [
        (date(2026, 9, 1), 42.48,
         "From Railway: 3 invoices, Sep 16 to Sep 16, Sep 16 to Sep 17, Sep 16 to Oct 16"),
    ],
}


def _cols():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("service_providers")}


def _fks():
    return {fk.get("name") for fk in sa.inspect(op.get_bind()).get_foreign_keys("service_providers")}


def _record(bind, provider_id, bills, now):
    for month, amount, note in bills:
        have = bind.execute(sa.text(
            "SELECT id, note FROM provider_invoices WHERE provider_id = :p AND period_month = :m"),
            {"p": provider_id, "m": month}).first()
        if have is not None:
            print(f"Railway: {month:%b %Y} already recorded, left as it is")
            continue
        bind.execute(sa.text(
            "INSERT INTO provider_invoices (provider_id, period_month, amount, note, created_at, updated_at) "
            "VALUES (:p, :m, :a, :n, :t, :t)"),
            {"p": provider_id, "m": month, "a": amount, "n": note, "t": now})
        print(f"Railway: {month:%b %Y} recorded, ${amount:,.2f}")


def upgrade():
    # create_all runs on boot and wins the race (CLAUDE.md, migrations).
    if "account_business_id" not in _cols():
        with op.batch_alter_table("service_providers") as batch:
            batch.add_column(sa.Column("account_business_id", sa.Integer(), nullable=True))
            batch.create_index("ix_service_providers_account_business_id", ["account_business_id"])
    if FK not in _fks():
        with op.batch_alter_table("service_providers") as batch:
            batch.create_foreign_key(FK, "businesses", ["account_business_id"], ["id"],
                                     ondelete="SET NULL")

    bind = op.get_bind()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    ours = bind.execute(sa.text(
        "SELECT id, credentials_json FROM service_providers WHERE name = 'railway' "
        "AND account_client_id IS NULL AND account_business_id IS NULL ORDER BY id")).first()
    if ours is None:
        print("Railway: no Railway provider on this board, nothing to set")
    else:
        try:
            creds = json.loads(ours.credentials_json or "{}")
        except ValueError:
            creds = {}
        if not creds.get("workspace_id"):
            creds["workspace_id"] = BBB_WORKSPACE[0]
            bind.execute(sa.text("UPDATE service_providers SET credentials_json = :c, account_label = :l "
                                 "WHERE id = :i"),
                         {"c": json.dumps(creds), "l": BBB_WORKSPACE[1], "i": ours.id})
            print(f"Railway: provider {ours.id} is the {BBB_WORKSPACE[1]} workspace")
        _record(bind, ours.id, BILLS["bbb"], now)

    business = bind.execute(sa.text("SELECT id FROM businesses WHERE slug = 'entertainhq'")).first()
    ehq = bind.execute(sa.text("SELECT id FROM service_providers WHERE display_name = :n"),
                       {"n": EHQ_NAME}).first()
    if ehq is None and ours is not None:
        bind.execute(sa.text(
            "INSERT INTO service_providers (name, display_name, is_active, credentials_json, "
            "account_business_id, account_label, created_at, updated_at) "
            "VALUES ('railway', :n, :a, :c, :b, :l, :t, :t)"),
            {"n": EHQ_NAME, "a": True, "c": json.dumps({"workspace_id": EHQ_WORKSPACE[0]}),
             "b": business.id if business else None, "l": EHQ_WORKSPACE[1], "t": now})
        ehq = bind.execute(sa.text("SELECT id FROM service_providers WHERE display_name = :n"),
                           {"n": EHQ_NAME}).first()
        print(f"Railway: {EHQ_NAME} added" + ("" if business else ", with no EntertainHQ business to own it"))
    if ehq is not None:
        _record(bind, ehq.id, BILLS["ehq"], now)


def downgrade():
    bind = op.get_bind()
    ehq = bind.execute(sa.text("SELECT id FROM service_providers WHERE display_name = :n"),
                       {"n": EHQ_NAME}).first()
    if ehq is not None:
        # Children first (CLAUDE.md, migrations). Its entries never wrote an
        # expense (EntertainHQ's money), so there is none to take with them.
        for table in ("provider_invoices", "service_cost_entries", "service_mappings"):
            bind.execute(sa.text(f"DELETE FROM {table} WHERE provider_id = :i"), {"i": ehq.id})
        bind.execute(sa.text("DELETE FROM service_providers WHERE id = :i"), {"i": ehq.id})
    if FK in _fks():
        with op.batch_alter_table("service_providers") as batch:
            batch.drop_constraint(FK, type_="foreignkey")
    if "account_business_id" in _cols():
        with op.batch_alter_table("service_providers") as batch:
            batch.drop_index("ix_service_providers_account_business_id")
            batch.drop_column("account_business_id")
