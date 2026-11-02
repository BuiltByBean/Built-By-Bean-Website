"""More of the questions a partner asks, answered on EntertainHQ's map

Michael, 2026-11-02: "you can go ahead and draft more." Each one is a thing
the product does that leans on a system outside the app, with the lines to
those systems and an honest status: a question with no process is marked
missing, because that is the answer to "do we have one".

Read off the repo's docs: the launch plan (self-serve signup, the commission
ledger), the security plan (tenant isolation), the J&D migration notes
(alerts that reach a phone, after launch), the text-updates page and the
A2P registration, the help page and the support inbox, and the tax return
routine on this board.

Every insert is skipped when its row is there. Bound parameters throughout.

Revision ID: b6d1f3a8c729
Revises: a2c9e7d14b58
Create Date: 2026-11-02
"""
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "b6d1f3a8c729"
down_revision = "a2c9e7d14b58"
branch_labels = None
depends_on = None

NOW = datetime(2026, 11, 3, 0, 30)
SEEDED = "Seeded from the repo on 2026-11-02; confirm it."

# (name, status, how, [refs]); a ref is s:<surface name>, a:<audience name>,
# or v:<need slug>[:<runbook slug or name>].
OUTCOMES = [
    ("Tenants sign up on their own", "in_progress",
     "Sign up on the marketing site, pay through Stripe, and land in a working tenant with nobody "
     "touching anything. Built for launch; confirm it is on for real cards.",
     ["s:Marketing site", "s:The app", "v:payments", "a:Tenants"]),
    ("Tenants pay for the product", "delivered",
     "A subscription on Stripe, invoiced monthly, with Stripe Tax collecting the sales tax.",
     ["v:payments", "a:Tenants", "s:Admin board"]),
    ("Each tenant's data is walled off", "delivered",
     "Every query runs inside the tenant, enforced in PostgreSQL, so one company never sees another's.",
     ["v:database", "s:The app", "a:Tenants"]),
    ("Tenants get help", "delivered",
     "The help page on the marketing site, and a support inbox on Google Workspace that a person answers.",
     ["s:Marketing site", "s:Support inbox", "v:mailbox", "a:Tenants"]),
    ("Texts go out registered and consented", "delivered",
     "The number is A2P 10DLC registered in the LLC's name on Twilio, consent is collected on the "
     "text-updates page, and every send runs through the consent gate.",
     ["v:texting", "v:legal-entity", "s:Marketing site", "a:Talent"]),
    ("Someone's phone rings when the app breaks", "in_progress",
     "The status site watches every service and the cron's heartbeat; an alert that reaches a phone "
     "by text is on the list for after launch.",
     ["s:Status site", "v:texting", "a:Michael"]),
    ("Talent gets paid", "missing",
     "Nothing in the product moves money to a performer yet; tenants pay talent outside it.",
     ["a:Talent"]),
    ("The company files its taxes", "delivered",
     "Each quarter's sales tax return is worked out on the admin board from Stripe's invoices and "
     "filed with the Comptroller; the LLC's papers are on file there too.",
     ["v:sales-tax", "v:legal-entity", "s:Admin board", "a:Texas"]),
]


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    if not {"businesses", "business_nodes", "business_edges", "business_needs"} <= _tables():
        return
    bind = op.get_bind()
    biz = bind.execute(sa.text("SELECT id FROM businesses WHERE slug = 'entertainhq'")).first()
    if biz is None:
        return
    bid = biz[0]
    need_ids = {r[0]: r[1] for r in bind.execute(sa.text("SELECT slug, id FROM business_needs"))}
    playbook_slugs = {r[1]: r[0] for r in bind.execute(sa.text("SELECT slug, id FROM playbooks"))} \
        if "playbooks" in _tables() else {}
    nodes = bind.execute(sa.text(
        "SELECT id, kind, name, need_id, playbook_id FROM business_nodes WHERE business_id = :b"),
        {"b": bid}).fetchall()

    def resolve(ref):
        kind, _, rest = ref.partition(":")
        if kind == "v":
            need_slug, _, pick = rest.partition(":")
            hits = [n for n in nodes if n[1] == "service" and n[3] == need_ids.get(need_slug)]
            if pick:
                hits = [n for n in hits if playbook_slugs.get(n[4]) == pick or (n[2] or "").lower() == pick.lower()]
            return [n[0] for n in hits]
        want = {"s": "surface", "a": "audience"}[kind]
        return [n[0] for n in nodes if n[1] == want and n[2] == rest]

    for name, status, how, refs in OUTCOMES:
        row = bind.execute(sa.text(
            "SELECT id FROM business_nodes WHERE business_id = :b AND kind = 'outcome' AND name = :n"),
            {"b": bid, "n": name}).first()
        if row is None:
            last = bind.execute(sa.text(
                "SELECT COALESCE(MAX(sort_order), 0) FROM business_nodes WHERE business_id = :b AND kind = 'outcome'"),
                {"b": bid}).scalar()
            bind.execute(sa.text(
                "INSERT INTO business_nodes (business_id, kind, name, role, status, url, surface_kind, "
                "sort_order, notes, created_at) VALUES (:b, 'outcome', :name, :how, :status, '', '', :sort, :notes, :now)"),
                {"b": bid, "name": name, "how": how, "status": status, "sort": last + 10, "notes": SEEDED, "now": NOW})
            row = bind.execute(sa.text(
                "SELECT id FROM business_nodes WHERE business_id = :b AND kind = 'outcome' AND name = :n"),
                {"b": bid, "n": name}).first()
        nid = row[0]
        for ref in refs:
            for other in resolve(ref):
                exists = bind.execute(sa.text(
                    "SELECT id FROM business_edges WHERE (from_node_id = :a AND to_node_id = :b) "
                    "OR (from_node_id = :b AND to_node_id = :a)"), {"a": other, "b": nid}).first()
                if exists is None:
                    bind.execute(sa.text(
                        "INSERT INTO business_edges (business_id, from_node_id, to_node_id, why) "
                        "VALUES (:bid, :a, :b, :why)"), {"bid": bid, "a": other, "b": nid, "why": how})


def downgrade():
    # Drafted outcomes are Michael's to keep or remove; nothing is pulled back.
    pass
