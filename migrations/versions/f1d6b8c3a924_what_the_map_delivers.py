"""What the map delivers: outcomes, the phone apps, and a service's own mark

Michael, 2026-11-02: the map "needs to be able to answer very quickly" how
customers charge their clients, how talent hears about a booking, whether
there is a process for X; it was missing the iOS app and Google Play; and a
service with no runbook showed two letters where its logo should be.

  * business_capabilities and business_capability_links: an outcome in plain
    words, its status, and the services that deliver it.
  * business_services.icon_file / icon_source / icon_fetched_at: a mark
    fetched off the service's URL, as My Apps does, for one with no runbook.
  * A need for push notifications, and EntertainHQ's phone apps: the App
    Store, Capacitor and APNs running, Google Play planned.
  * A first set of outcomes for each business, read off its docs, wired to
    the services already on its map by the need they fill.

Every insert is skipped when its row is there. Bound parameters throughout.

Revision ID: f1d6b8c3a924
Revises: e5a3c7b19d42
Create Date: 2026-11-02
"""
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "f1d6b8c3a924"
down_revision = "e5a3c7b19d42"
branch_labels = None
depends_on = None

NOW = datetime(2026, 11, 2, 22, 0)
SEEDED = "Seeded from the repo on 2026-11-02; confirm it."

NEEDS = [
    ("push", "Push notifications", "comms", False,
     "A notification on the phone, through the platform's own service.", "apns", 265),
]
NEED_LINKS = [
    ("mobile-apps", "push", "The phone apps are what the notifications land on."),
]

# business slug -> [(need slug, playbook slug or None, name, role, status, url)]
SERVICES = {
    "entertainhq": [
        ("mobile-apps", "app-store", "", "The iOS app, in the App Store.", "running", ""),
        ("mobile-apps", "google-play", "", "The Android app, next.", "planned", ""),
        ("mobile-apps", "capacitor", "", "Wraps the web app for the stores.", "running", ""),
        ("push", "apns", "", "Push notifications on the iOS app.", "running", ""),
    ],
}

# business slug -> [(name, how, status, [service pickers])]. A picker is a
# need slug, optionally with a runbook slug or a name after a colon.
CAPABILITIES = {
    "entertainhq": [
        ("Customers charge their clients",
         "Invoices and card payments go through Stripe, with the sales tax worked out and collected on each one.",
         "delivered", ["payments"]),
        ("Talent hears about a booking",
         "A text through Twilio, an email through Resend, and a push on the iOS app through APNs, all behind the consent gate.",
         "delivered", ["texting", "email", "push"]),
        ("Contracts get signed",
         "Talent contracts and client agreements go out through Signadoc and come back sealed, with an audit trail.",
         "delivered", ["contracts"]),
        ("Events arrive from the venue",
         "Bookings sync both ways with Tripleseat, so the office never types an event twice.",
         "delivered", ["venue-system"]),
        ("Staff and talent work from their phones",
         "The iOS app is in the App Store, wrapped with Capacitor; Android is next, through Google Play.",
         "in_progress", ["mobile-apps:app-store", "mobile-apps:capacitor", "mobile-apps:google-play"]),
        ("Customers bring their data with them",
         "An import wizard takes performers, clients and events from the tools they used before; Zapier catches the feeds from tools with no API.",
         "in_progress", ["web-app", "automations"]),
        ("Nothing is lost",
         "Railway takes a daily backup of the database, and media sits in the Railway bucket.",
         "delivered", ["database", "storage"]),
        ("Customers can get their data out",
         "Export and deletion on request, from the app.",
         "delivered", ["web-app"]),
    ],
    "built-by-bean": [
        ("Clients pay their invoices",
         "Invoices are raised on the board and paid through Stripe, with the 6.6% sales tax on each.",
         "delivered", ["payments", "admin"]),
        ("Contracts get signed",
         "SOWs, hosting agreements and revenue shares go out through Signadoc and come back sealed.",
         "delivered", ["contracts"]),
        ("Client apps report what breaks",
         "Tickets travel both ways over the hub: each app pushes, and the board asks daily.",
         "delivered", ["web-app"]),
        ("Every vendor charge is in the books",
         "The nightly cost sync books each vendor's usage as an expense, per project.",
         "delivered", ["web-app", "hosting"]),
    ],
    "data-dungeon": [
        ("Subscribers pay",
         "Store subscriptions through RevenueCat and the App Store; web subscriptions through Stripe.",
         "delivered", ["subscriptions", "payments", "mobile-apps:app-store"]),
        ("Crashes are caught before players notice",
         "Exceptions from the app and the phone builds report to Sentry.",
         "delivered", ["monitoring"]),
        ("Uploads are safe to show",
         "Google Vision screens every uploaded image before anyone else sees it.",
         "delivered", ["moderation"]),
    ],
}


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    if table not in _tables():
        return None
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    have = _tables()
    if "business_capabilities" not in have:
        op.create_table(
            "business_capabilities",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("how", sa.String(length=400), nullable=True),
            sa.Column("status", sa.String(length=12), nullable=False, server_default="delivered"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                    name="fk_business_capabilities_business_id"),
            sa.PrimaryKeyConstraint("id", name="pk_business_capabilities"),
        )
        op.create_index("ix_business_capabilities_business_id", "business_capabilities", ["business_id"])
    if "business_capability_links" not in have:
        op.create_table(
            "business_capability_links",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("capability_id", sa.Integer(), nullable=False),
            sa.Column("service_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["capability_id"], ["business_capabilities.id"], ondelete="CASCADE",
                                    name="fk_business_capability_links_capability_id"),
            sa.ForeignKeyConstraint(["service_id"], ["business_services.id"], ondelete="CASCADE",
                                    name="fk_business_capability_links_service_id"),
            sa.PrimaryKeyConstraint("id", name="pk_business_capability_links"),
            sa.UniqueConstraint("capability_id", "service_id", name="uq_business_capability_link"),
        )
        op.create_index("ix_business_capability_links_capability_id", "business_capability_links", ["capability_id"])
        op.create_index("ix_business_capability_links_service_id", "business_capability_links", ["service_id"])

    cols = _columns("business_services")
    if cols is not None:
        missing = [c for c in ("icon_file", "icon_source", "icon_fetched_at") if c not in cols]
        if missing:
            with op.batch_alter_table("business_services", schema=None) as batch_op:
                if "icon_file" in missing:
                    batch_op.add_column(sa.Column("icon_file", sa.String(length=120), nullable=True))
                if "icon_source" in missing:
                    batch_op.add_column(sa.Column("icon_source", sa.String(length=500), nullable=True))
                if "icon_fetched_at" in missing:
                    batch_op.add_column(sa.Column("icon_fetched_at", sa.DateTime(), nullable=True))

    seed()


def seed():
    if not {"business_needs", "business_services", "businesses", "playbooks"} <= _tables():
        return
    bind = op.get_bind()

    for slug, name, layer, essential, description, fills, sort in NEEDS:
        if bind.execute(sa.text("SELECT id FROM business_needs WHERE slug = :slug"),
                        {"slug": slug}).first() is None:
            bind.execute(sa.text(
                "INSERT INTO business_needs (slug, name, layer, essential, in_house, description, "
                "fills_with, sort_order) VALUES (:slug, :name, :layer, :essential, :in_house, "
                ":description, :fills, :sort)"),
                {"slug": slug, "name": name, "layer": layer, "essential": essential, "in_house": False,
                 "description": description, "fills": fills, "sort": sort})
    need_ids = {r[0]: r[1] for r in bind.execute(sa.text("SELECT slug, id FROM business_needs"))}
    for a, b, why in NEED_LINKS:
        if a in need_ids and b in need_ids and bind.execute(sa.text(
                "SELECT id FROM business_need_links WHERE from_need_id = :a AND to_need_id = :b"),
                {"a": need_ids[a], "b": need_ids[b]}).first() is None:
            bind.execute(sa.text("INSERT INTO business_need_links (from_need_id, to_need_id, why) "
                                 "VALUES (:a, :b, :why)"), {"a": need_ids[a], "b": need_ids[b], "why": why})

    playbook_ids = {r[0]: r[1] for r in bind.execute(sa.text("SELECT slug, id FROM playbooks"))}
    for business_slug, rows in SERVICES.items():
        biz = bind.execute(sa.text("SELECT id FROM businesses WHERE slug = :slug"), {"slug": business_slug}).first()
        if biz is None:
            continue
        for need_slug, pb_slug, name, role, status, url in rows:
            pb_id = playbook_ids.get(pb_slug) if pb_slug else None
            if pb_id is None and not name:
                name = (pb_slug or need_slug).replace("-", " ").title()
            exists = bind.execute(sa.text(
                "SELECT id FROM business_services WHERE business_id = :b AND need_id = :need AND "
                "((:pb IS NOT NULL AND playbook_id = :pb) OR (name = :name AND name != ''))"),
                {"b": biz[0], "need": need_ids.get(need_slug), "pb": pb_id, "name": name}).first()
            if exists is None:
                bind.execute(sa.text(
                    "INSERT INTO business_services (business_id, need_id, playbook_id, name, layer, "
                    "role, status, url, notes, created_at) VALUES (:b, :need, :pb, :name, '', :role, "
                    ":status, :url, :notes, :now)"),
                    {"b": biz[0], "need": need_ids.get(need_slug), "pb": pb_id, "name": name,
                     "role": role, "status": status, "url": url, "notes": SEEDED, "now": NOW})

    if "business_capabilities" not in _tables():
        return
    playbook_slug_by_id = {v: k for k, v in playbook_ids.items()}
    for business_slug, caps in CAPABILITIES.items():
        biz = bind.execute(sa.text("SELECT id FROM businesses WHERE slug = :slug"), {"slug": business_slug}).first()
        if biz is None:
            continue
        # A business with outcomes already is somebody's work: leave it alone.
        if bind.execute(sa.text("SELECT 1 FROM business_capabilities WHERE business_id = :b"),
                        {"b": biz[0]}).first() is not None:
            continue
        services = bind.execute(sa.text(
            "SELECT id, need_id, playbook_id, name FROM business_services WHERE business_id = :b"),
            {"b": biz[0]}).fetchall()

        def find(picker):
            need_slug, _, rest = picker.partition(":")
            need_id = need_ids.get(need_slug)
            hits = [s for s in services if s[1] == need_id]
            if rest:
                hits = [s for s in hits if playbook_slug_by_id.get(s[2]) == rest
                        or (s[3] or "").lower() == rest.lower()]
            return [s[0] for s in hits]

        for i, (name, how, status, pickers) in enumerate(caps):
            bind.execute(sa.text(
                "INSERT INTO business_capabilities (business_id, name, how, status, sort_order, created_at) "
                "VALUES (:b, :name, :how, :status, :sort, :now)"),
                {"b": biz[0], "name": name, "how": how, "status": status, "sort": (i + 1) * 10, "now": NOW})
            cap = bind.execute(sa.text(
                "SELECT id FROM business_capabilities WHERE business_id = :b AND name = :name"),
                {"b": biz[0], "name": name}).first()
            seen = set()
            for picker in pickers:
                for sid in find(picker):
                    if sid in seen:
                        continue
                    seen.add(sid)
                    bind.execute(sa.text(
                        "INSERT INTO business_capability_links (capability_id, service_id) VALUES (:c, :s)"),
                        {"c": cap[0], "s": sid})


def downgrade():
    have = _tables()
    for table in ("business_capability_links", "business_capabilities"):
        if table in have:
            op.drop_table(table)
    cols = _columns("business_services")
    if cols is not None:
        present = [c for c in ("icon_fetched_at", "icon_source", "icon_file") if c in cols]
        if present:
            with op.batch_alter_table("business_services", schema=None) as batch_op:
                for c in present:
                    batch_op.drop_column(c)
