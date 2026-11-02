"""The map is a network: one node table, one edge table, and the whole business

Michael, 2026-11-02, after two maps that were vendor inventories in columns:
"a network of everything that's making this product run ... you don't even
list on here that we have a marketing site, that we have an admin portal,
that we have a status site." And what belongs on it: not how messages move
inside the app, but "how does this product let our customers know there's
an outage? That is connected to a system outside the app itself."

So the four map tables become two. `business_nodes` holds every kind of
thing (audience, surface, service, outcome) and `business_edges` every line
with its why. Every row the old tables held moves across: services and
outcomes as nodes, outcome links and hand-written links as edges. Then the
old tables go.

The seed adds what a vendor list could never show: the SURFACES people
touch (EntertainHQ's marketing site, the app, the staff and talent portals,
the client portal, the iOS and Android apps, the status site at
status.entertainhq.com, which is a Cloudflare Worker outside Railway, the
admin board, the support inbox), the AUDIENCES (tenants, their staff, the
talent, their clients, partners, Michael, the State), the lines between
them, and the outcomes that cross the app's boundary: tenants told about an
outage, proposals sent to clients.

Every insert is skipped when its row is there. Bound parameters throughout.

Revision ID: a2c9e7d14b58
Revises: f1d6b8c3a924
Create Date: 2026-11-02
"""
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "a2c9e7d14b58"
down_revision = "f1d6b8c3a924"
branch_labels = None
depends_on = None

NOW = datetime(2026, 11, 2, 23, 30)
SEEDED = "Seeded from the repo on 2026-11-02; confirm it."

# business slug -> surfaces: (key, name, surface_kind, status, url, role)
SURFACES = {
    "entertainhq": [
        ("site", "Marketing site", "site", "live", "https://entertainhq.com",
         "Where a tenant finds the product, reads the terms and signs up."),
        ("app", "The app", "app", "live", "https://app.entertainhq.com",
         "Where a tenant's office runs its events, talent, clients and money."),
        ("staff", "Staff portal", "portal", "live", "",
         "Where a tenant's staff work their events and messages."),
        ("talent", "Talent portal", "portal", "live", "",
         "Where performers see bookings, sign contracts and keep their profile."),
        ("client", "Client portal", "portal", "live", "",
         "Where a tenant's clients read proposals, sign and pay."),
        ("ios", "iOS app", "phone", "live", "", "The product on the phone, from the App Store."),
        ("android", "Android app", "phone", "planned", "", "The same, from Google Play. Next."),
        ("status", "Status site", "status", "live", "https://status.entertainhq.com",
         "Live health of every service, outside Railway so it stands when the app falls."),
        ("board", "Admin board", "admin", "live", "https://builtbybeans.com/admin",
         "Where the business is run: returns, costs, tickets, this map."),
        ("inbox", "Support inbox", "inbox", "live", "", "Where a tenant writes in."),
    ],
    "built-by-bean": [
        ("site", "builtbybeans.com", "site", "live", "https://builtbybeans.com",
         "The site a client finds, and the contact form behind it."),
        ("board", "Admin board", "admin", "live", "https://builtbybeans.com/admin",
         "The project manager: clients, invoices, contracts, costs, every business."),
        ("portal", "Signing portal", "portal", "live", "", "Where a client signs a contract."),
        ("inbox", "Mailbox", "inbox", "live", "", "Where clients and leads write in."),
    ],
    "data-dungeon": [
        ("site", "datadungeon.io", "site", "live", "https://datadungeon.io", "The web app and its front door."),
        ("ios", "iOS app", "phone", "live", "", "The game on the phone, from the App Store."),
        ("board", "Admin board", "admin", "live", "https://builtbybeans.com/admin",
         "Where the business side is run."),
    ],
}

# business slug -> audiences: (key, name, role)
AUDIENCES = {
    "entertainhq": [
        ("tenants", "Tenants", "The entertainment companies that buy the product."),
        ("staff", "Tenant staff", "The office and the agents inside a tenant."),
        ("talent", "Talent", "The performers a tenant books."),
        ("clients", "Tenants' clients", "The people booking an event from a tenant."),
        ("partners", "Partners", "Who shares in the business and watches it run."),
        ("owner", "Michael", "Owner."),
        ("state", "Texas", "The Comptroller, owed a return each quarter."),
    ],
    "built-by-bean": [
        ("clients", "Clients", "Who commissions and pays for the apps."),
        ("leads", "Leads", "Every business in the trade area that might."),
        ("owner", "Michael", "Owner."),
        ("state", "Texas", "The Comptroller, owed a return each quarter."),
    ],
    "data-dungeon": [
        ("players", "Players", "Who plays, and subscribes."),
        ("owner", "Michael", "Owner."),
    ],
}

# Edges by key. A key is "s:<surface key>", "a:<audience key>", "o:<outcome
# name>", or "v:<need slug>[:<runbook slug or name>]" for a service.
EDGES = {
    "entertainhq": [
        ("a:tenants", "s:site", "Find it, read the terms, sign up."),
        ("a:tenants", "s:app", "Run the office here."),
        ("a:tenants", "s:status", "Check whether it is up."),
        ("a:tenants", "s:inbox", "Write in when something is wrong."),
        ("a:staff", "s:staff", "Work events and messages."),
        ("a:staff", "s:ios", "The same, on the phone."),
        ("a:talent", "s:talent", "Bookings, contracts, profile."),
        ("a:talent", "s:ios", "The same, on the phone."),
        ("a:clients", "s:client", "Read the proposal, sign, pay."),
        ("a:partners", "s:board", "Returns, costs and this map."),
        ("a:owner", "s:board", "Runs the business from here."),
        ("a:state", "v:sales-tax", "Each quarter's return and the tax with it."),
        ("v:hosting", "s:app", "The app runs here."),
        ("v:hosting", "s:staff", "Served by the same app."),
        ("v:hosting", "s:talent", "Served by the same app."),
        ("v:hosting", "s:client", "Served by the same app."),
        ("v:hosting", "s:site", "The marketing site is a Next app on the same platform."),
        ("v:domain", "s:site", "DNS for entertainhq.com."),
        ("v:domain", "s:app", "DNS for app.entertainhq.com."),
        ("v:domain", "s:status", "The status page is a Cloudflare Worker: it lives at the edge, not on Railway."),
        ("v:database", "s:app", "Every tenant's data."),
        ("v:storage", "s:app", "Headshots, costume photos, documents."),
        ("v:code", "s:app", "Push to main and it deploys."),
        ("v:payments", "s:app", "Subscriptions, invoices, Stripe Tax."),
        ("v:payments", "s:client", "A client pays the invoice here."),
        ("v:email", "s:app", "Every mail the app sends."),
        ("v:email", "s:client", "The proposal link and the invoice go by mail."),
        ("v:texting", "s:talent", "Texts to performers, behind the consent gate."),
        ("v:push", "s:ios", "Push notifications on the phone."),
        ("v:contracts", "s:talent", "Performer contracts are signed here."),
        ("v:contracts", "s:client", "Client contracts are signed here."),
        ("v:venue-system", "s:app", "Events and bookings sync both ways."),
        ("v:automations", "s:app", "Feeds from tools with no API arrive here."),
        ("v:mailbox", "s:inbox", "The inbox lives on Google Workspace."),
        ("v:mobile-apps:app-store", "s:ios", "The listing and the review."),
        ("v:mobile-apps:capacitor", "s:ios", "Wraps the web app for the phone."),
        ("v:mobile-apps:google-play", "s:android", "The listing, when it ships."),
        ("v:admin", "s:board", "This board."),
        ("v:legal-entity", "s:board", "Its papers are on file here."),
        ("v:sales-tax", "s:board", "Returns are worked out and recorded here."),
        ("v:bank", "s:board", "The books reconcile against it here."),
    ],
    "built-by-bean": [
        ("a:clients", "s:site", "Find Built by Bean and write in."),
        ("a:clients", "s:portal", "Sign the SOW and the hosting agreement."),
        ("a:leads", "s:site", "The call list leads here."),
        ("a:owner", "s:board", "Runs the business from here."),
        ("a:state", "v:sales-tax", "Each quarter's return and the tax with it."),
        ("v:hosting", "s:site", "Site and board run here."),
        ("v:hosting", "s:board", "Site and board run here."),
        ("v:database", "s:board", "The board's data."),
        ("v:code", "s:board", "Push to main and it deploys."),
        ("v:payments", "s:board", "Invoices are raised here and paid through Stripe."),
        ("v:email", "s:board", "The board sends and reads mail through it."),
        ("v:email", "s:inbox", "Michael's mailbox."),
        ("v:contracts", "s:portal", "The signing portal is Signadoc."),
        ("v:ai", "s:board", "Claude builds the apps and files what it learns here."),
        ("v:legal-entity", "s:board", "Its papers are on file here."),
        ("v:sales-tax", "s:board", "Returns are worked out and recorded here."),
    ],
    "data-dungeon": [
        ("a:players", "s:site", "Play on the web."),
        ("a:players", "s:ios", "Play on the phone."),
        ("a:owner", "s:board", "Runs the business from here."),
        ("v:hosting", "s:site", "The app runs here."),
        ("v:database", "s:site", "The data."),
        ("v:code", "s:site", "Push to main and it deploys."),
        ("v:domain", "s:site", "DNS for datadungeon.io."),
        ("v:monitoring", "s:site", "Exceptions report here."),
        ("v:mobile-apps:app-store", "s:ios", "The listing and the review."),
        ("v:mobile-apps:capacitor", "s:ios", "Wraps the web app for the phone."),
        ("v:subscriptions", "s:ios", "Store subscriptions, reconciled."),
        ("v:payments", "s:site", "Web subscriptions."),
        ("v:email", "s:site", "Mail the app sends."),
        ("v:ai", "s:site", "The models behind the dungeon."),
        ("v:moderation", "s:site", "Uploads are screened before they are shown."),
    ],
}

# New outcomes, the kind that cross the app's boundary, with their lines.
OUTCOMES = {
    "entertainhq": [
        ("Tenants are told about an outage", "in_progress",
         "status.entertainhq.com, a Cloudflare Worker outside Railway, shows every service's health and "
         "the cron's heartbeat. Telling tenants by mail when it goes red is not wired yet.",
         ["s:status", "v:domain", "a:tenants"]),
        ("Tenants send proposals to their clients", "delivered",
         "A proposal goes to the client by link, in a mail through Resend; the contract that follows is "
         "signed through Signadoc and the invoice is paid through Stripe.",
         ["s:client", "v:email", "v:contracts", "v:payments", "a:clients"]),
    ],
}
# Old outcomes get lines to the people and surfaces they are about.
OUTCOME_EDGES = {
    "entertainhq": [
        ("Customers charge their clients", ["s:client", "a:clients"]),
        ("Talent hears about a booking", ["a:talent", "s:talent", "s:ios"]),
        ("Contracts get signed", ["a:talent", "a:clients"]),
        ("Events arrive from the venue", ["s:app"]),
        ("Staff and talent work from their phones", ["s:ios", "s:android", "a:staff", "a:talent"]),
        ("Customers bring their data with them", ["a:tenants", "s:app"]),
        ("Nothing is lost", ["s:app"]),
        ("Customers can get their data out", ["a:tenants", "s:app"]),
    ],
    "built-by-bean": [
        ("Clients pay their invoices", ["a:clients", "s:board"]),
        ("Contracts get signed", ["a:clients", "s:portal"]),
        ("Client apps report what breaks", ["s:board"]),
        ("Every vendor charge is in the books", ["s:board"]),
    ],
    "data-dungeon": [
        ("Subscribers pay", ["a:players", "s:ios", "s:site"]),
        ("Crashes are caught before players notice", ["s:site", "s:ios"]),
        ("Uploads are safe to show", ["s:site"]),
    ],
}


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    have = _tables()
    if "business_nodes" not in have:
        op.create_table(
            "business_nodes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=12), nullable=False, server_default="service"),
            sa.Column("name", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("role", sa.String(length=400), nullable=True),
            sa.Column("status", sa.String(length=12), nullable=True),
            sa.Column("url", sa.String(length=300), nullable=True),
            sa.Column("surface_kind", sa.String(length=12), nullable=True),
            sa.Column("need_id", sa.Integer(), nullable=True),
            sa.Column("playbook_id", sa.Integer(), nullable=True),
            sa.Column("icon_file", sa.String(length=120), nullable=True),
            sa.Column("icon_source", sa.String(length=500), nullable=True),
            sa.Column("icon_fetched_at", sa.DateTime(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                    name="fk_business_nodes_business_id"),
            sa.ForeignKeyConstraint(["need_id"], ["business_needs.id"], ondelete="SET NULL",
                                    name="fk_business_nodes_need_id"),
            sa.ForeignKeyConstraint(["playbook_id"], ["playbooks.id"], ondelete="SET NULL",
                                    name="fk_business_nodes_playbook_id"),
            sa.PrimaryKeyConstraint("id", name="pk_business_nodes"),
        )
        op.create_index("ix_business_nodes_business_id", "business_nodes", ["business_id"])
        op.create_index("ix_business_nodes_kind", "business_nodes", ["kind"])
        op.create_index("ix_business_nodes_need_id", "business_nodes", ["need_id"])
        op.create_index("ix_business_nodes_playbook_id", "business_nodes", ["playbook_id"])
    if "business_edges" not in have:
        op.create_table(
            "business_edges",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("from_node_id", sa.Integer(), nullable=False),
            sa.Column("to_node_id", sa.Integer(), nullable=False),
            sa.Column("why", sa.String(length=300), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                    name="fk_business_edges_business_id"),
            sa.ForeignKeyConstraint(["from_node_id"], ["business_nodes.id"], ondelete="CASCADE",
                                    name="fk_business_edges_from"),
            sa.ForeignKeyConstraint(["to_node_id"], ["business_nodes.id"], ondelete="CASCADE",
                                    name="fk_business_edges_to"),
            sa.PrimaryKeyConstraint("id", name="pk_business_edges"),
            sa.UniqueConstraint("from_node_id", "to_node_id", name="uq_business_edge"),
        )
        op.create_index("ix_business_edges_business_id", "business_edges", ["business_id"])
        op.create_index("ix_business_edges_from_node_id", "business_edges", ["from_node_id"])
        op.create_index("ix_business_edges_to_node_id", "business_edges", ["to_node_id"])

    move()
    seed()

    # The old tables go, children first.
    for table in ("business_capability_links", "business_links", "business_capabilities", "business_services"):
        if table in _tables():
            op.drop_table(table)


def move():
    """Every row the old tables held, carried into nodes and edges."""
    bind = op.get_bind()
    have = _tables()
    if "business_services" not in have:
        return
    service_node = {}
    for r in bind.execute(sa.text(
            "SELECT id, business_id, need_id, playbook_id, name, role, status, url, notes, "
            "icon_file, icon_source, icon_fetched_at, created_at FROM business_services ORDER BY id")):
        bind.execute(sa.text(
            "INSERT INTO business_nodes (business_id, kind, name, role, status, url, surface_kind, "
            "need_id, playbook_id, icon_file, icon_source, icon_fetched_at, sort_order, notes, created_at) "
            "VALUES (:b, 'service', :name, :role, :status, :url, '', :need, :pb, :icon, :src, :fetched, "
            ":sort, :notes, :created)"),
            {"b": r[1], "name": r[4] or "", "role": r[5] or "", "status": r[6] or "running", "url": r[7] or "",
             "need": r[2], "pb": r[3], "icon": r[9], "src": r[10], "fetched": r[11], "sort": r[0] * 10,
             "notes": r[8] or "", "created": r[12] or NOW})
        service_node[r[0]] = bind.execute(sa.text("SELECT MAX(id) FROM business_nodes")).scalar()

    cap_node = {}
    if "business_capabilities" in have:
        for r in bind.execute(sa.text(
                "SELECT id, business_id, name, how, status, sort_order, created_at FROM business_capabilities ORDER BY id")):
            bind.execute(sa.text(
                "INSERT INTO business_nodes (business_id, kind, name, role, status, url, surface_kind, "
                "sort_order, notes, created_at) VALUES (:b, 'outcome', :name, :how, :status, '', '', :sort, '', :created)"),
                {"b": r[1], "name": r[2], "how": r[3] or "", "status": r[4] or "delivered", "sort": r[5] or 0,
                 "created": r[6] or NOW})
            cap_node[r[0]] = bind.execute(sa.text("SELECT MAX(id) FROM business_nodes")).scalar()
    if "business_capability_links" in have:
        for r in bind.execute(sa.text(
                "SELECT l.capability_id, l.service_id, c.business_id, c.how FROM business_capability_links l "
                "JOIN business_capabilities c ON c.id = l.capability_id")):
            a, b = service_node.get(r[1]), cap_node.get(r[0])
            if a and b:
                _edge(bind, r[2], a, b, r[3] or "")
    if "business_links" in have:
        for r in bind.execute(sa.text(
                "SELECT business_id, from_service_id, to_service_id, why FROM business_links")):
            a, b = service_node.get(r[1]), service_node.get(r[2])
            if a and b:
                _edge(bind, r[0], a, b, r[3] or "")


def _edge(bind, business_id, a, b, why):
    if a == b:
        return
    exists = bind.execute(sa.text(
        "SELECT id FROM business_edges WHERE (from_node_id = :a AND to_node_id = :b) "
        "OR (from_node_id = :b AND to_node_id = :a)"), {"a": a, "b": b}).first()
    if exists is None:
        bind.execute(sa.text(
            "INSERT INTO business_edges (business_id, from_node_id, to_node_id, why) VALUES (:bid, :a, :b, :why)"),
            {"bid": business_id, "a": a, "b": b, "why": why})


def seed():
    bind = op.get_bind()
    if not {"businesses", "business_nodes", "business_needs"} <= _tables():
        return
    need_ids = {r[0]: r[1] for r in bind.execute(sa.text("SELECT slug, id FROM business_needs"))}
    playbook_slugs = {r[1]: r[0] for r in bind.execute(sa.text("SELECT slug, id FROM playbooks"))} \
        if "playbooks" in _tables() else {}

    for slug in set(SURFACES) | set(AUDIENCES) | set(OUTCOMES) | set(OUTCOME_EDGES):
        biz = bind.execute(sa.text("SELECT id FROM businesses WHERE slug = :slug"), {"slug": slug}).first()
        if biz is None:
            continue
        bid = biz[0]
        keys = {}

        def node_id(kind, name):
            row = bind.execute(sa.text(
                "SELECT id FROM business_nodes WHERE business_id = :b AND kind = :k AND name = :n"),
                {"b": bid, "k": kind, "n": name}).first()
            return row[0] if row else None

        for i, (key, name, skind, status, url, role) in enumerate(SURFACES.get(slug, [])):
            nid = node_id("surface", name)
            if nid is None:
                bind.execute(sa.text(
                    "INSERT INTO business_nodes (business_id, kind, name, role, status, url, surface_kind, "
                    "sort_order, notes, created_at) VALUES (:b, 'surface', :name, :role, :status, :url, :sk, "
                    ":sort, :notes, :now)"),
                    {"b": bid, "name": name, "role": role, "status": status, "url": url, "sk": skind,
                     "sort": (i + 1) * 10, "notes": SEEDED, "now": NOW})
                nid = node_id("surface", name)
            keys[f"s:{key}"] = nid
        for i, (key, name, role) in enumerate(AUDIENCES.get(slug, [])):
            nid = node_id("audience", name)
            if nid is None:
                bind.execute(sa.text(
                    "INSERT INTO business_nodes (business_id, kind, name, role, status, url, surface_kind, "
                    "sort_order, notes, created_at) VALUES (:b, 'audience', :name, :role, '', '', '', :sort, :notes, :now)"),
                    {"b": bid, "name": name, "role": role, "sort": (i + 1) * 10, "notes": SEEDED, "now": NOW})
                nid = node_id("audience", name)
            keys[f"a:{key}"] = nid

        services = bind.execute(sa.text(
            "SELECT id, need_id, playbook_id, name FROM business_nodes WHERE business_id = :b AND kind = 'service'"),
            {"b": bid}).fetchall()

        def service_ids(picker):
            need_slug, _, rest = picker.partition(":")
            hits = [s for s in services if s[1] == need_ids.get(need_slug)]
            if rest:
                hits = [s for s in hits if playbook_slugs.get(s[2]) == rest or (s[3] or "").lower() == rest.lower()]
            return [s[0] for s in hits]

        def resolve(ref):
            if ref.startswith("v:"):
                return service_ids(ref[2:])
            if ref.startswith("o:"):
                nid = node_id("outcome", ref[2:])
                return [nid] if nid else []
            nid = keys.get(ref)
            return [nid] if nid else []

        for name, status, how, refs in OUTCOMES.get(slug, []):
            nid = node_id("outcome", name)
            if nid is None:
                last = bind.execute(sa.text(
                    "SELECT COALESCE(MAX(sort_order), 0) FROM business_nodes WHERE business_id = :b AND kind = 'outcome'"),
                    {"b": bid}).scalar()
                bind.execute(sa.text(
                    "INSERT INTO business_nodes (business_id, kind, name, role, status, url, surface_kind, "
                    "sort_order, notes, created_at) VALUES (:b, 'outcome', :name, :how, :status, '', '', :sort, :notes, :now)"),
                    {"b": bid, "name": name, "how": how, "status": status, "sort": last + 10, "notes": SEEDED, "now": NOW})
                nid = node_id("outcome", name)
            for ref in refs:
                for other in resolve(ref):
                    _edge(bind, bid, other, nid, how)

        for a_ref, b_ref, why in EDGES.get(slug, []):
            for a in resolve(a_ref):
                for b in resolve(b_ref):
                    _edge(bind, bid, a, b, why)
        for name, refs in OUTCOME_EDGES.get(slug, []):
            nid = node_id("outcome", name)
            if nid is None:
                continue
            how = bind.execute(sa.text("SELECT role FROM business_nodes WHERE id = :id"), {"id": nid}).scalar() or ""
            for ref in refs:
                for other in resolve(ref):
                    _edge(bind, bid, other, nid, how)


def downgrade():
    # The old shape is not put back: nodes and edges hold everything it held.
    have = _tables()
    for table in ("business_edges", "business_nodes"):
        if table in have:
            op.drop_table(table)
