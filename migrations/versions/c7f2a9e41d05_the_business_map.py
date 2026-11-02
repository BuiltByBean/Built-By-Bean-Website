"""The business map: the needs every business has, and what each one uses

Michael, 2026-11-02: a map of everything that makes a business run, with the
holes showing, and under it a business playbook, "start to finish every
little thing that I need to set up".

Four tables (business_needs, business_need_links, business_services,
business_links), then the seed:

  * The needs, in the layer a business is built in, essential or optional,
    with the runbooks that fill each one. The universal playbook.
  * The connections that follow between needs, each with its why.
  * Each business's services, read off its own repo: EntertainHQ's config and
    docs name Railway, Postgres, GitHub, Cloudflare, S3, Resend, Twilio,
    Stripe, Tripleseat, Signadoc, Google Workspace and Zapier, and Michael
    named Mercury and LegalZoom; Data Dungeon's names Railway, Postgres,
    GitHub, Sentry, RevenueCat, Stripe, Capacitor, the App Store, Cloudflare
    and the LLM APIs; this board's own names Railway, Postgres, GitHub,
    Stripe, Gmail SMTP, Signadoc, the LLM APIs and AWS. A runbook the board
    has not got leaves playbook_id null and the name stands on its own.

Every insert is skipped when its row is there. Bound parameters throughout.

Revision ID: c7f2a9e41d05
Revises: a8e4c1d9f2b7
Create Date: 2026-11-02
"""
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "c7f2a9e41d05"
down_revision = "a8e4c1d9f2b7"
branch_labels = None
depends_on = None

NOW = datetime(2026, 11, 2, 20, 0)

# slug, name, layer, essential, description, fills_with
NEEDS = [
    ("legal-entity", "Legal entity", "legal", True,
     "The LLC the business trades as, with its EIN and its registered agent.", "legalzoom"),
    ("sales-tax", "Sales tax", "legal", True,
     "The state permit, and the return filed each period on what was sold.", "texas-sales-tax"),
    ("assumed-name", "Assumed name", "legal", False,
     "The certificate that lets the LLC trade under another name.", "legalzoom"),
    ("insurance", "Insurance", "legal", False,
     "General liability, and whatever a venue or a client's contract asks for.", ""),

    ("bank", "Bank account", "money", True,
     "Where the money lands and the bills get paid, in the LLC's name.", "mercury"),
    ("payments", "Payments", "money", True,
     "How customers pay: cards, invoices, subscriptions, and the tax on each charge.", "stripe"),
    ("accounting", "Accounting", "money", True,
     "The books: every charge, fee and expense, reconciled against the bank.",
     "quickbooks-online"),
    ("payouts", "Paying people", "money", False,
     "How contractors and performers get paid out.", "venmo-zelle-cash-app"),
    ("subscriptions", "App subscriptions", "money", False,
     "Store subscriptions on a phone app, reconciled across both stores.", "revenuecat"),

    ("domain", "Domain and DNS", "infrastructure", True,
     "The name the business is found by, and where its records live.", "cloudflare,godaddy"),
    ("hosting", "Hosting", "infrastructure", True,
     "Where the app runs and deploys from.", "railway"),
    ("database", "Database", "infrastructure", True,
     "Where the data lives, and its backups.", "postgres"),
    ("code", "Code", "infrastructure", True,
     "Where the code lives and what deploys from it.", "github"),
    ("storage", "File storage", "infrastructure", False,
     "Uploads and media, off the container.", "aws"),
    ("monitoring", "Error monitoring", "infrastructure", False,
     "Finds out the app is broken before a customer rings.", "sentry"),

    ("web-app", "The app", "product", True,
     "The product itself: what customers and staff sign in to.", ""),
    ("mobile-apps", "Phone apps", "product", False,
     "The same product in the stores: builds, listings and review.",
     "capacitor,app-store,google-play,apns"),
    ("website", "Website", "product", False,
     "The public site that sells it.", "squarespace"),

    ("admin", "Admin and books of record", "operations", False,
     "Where the owner runs it: projects, tickets, invoices, time.", ""),
    ("contracts", "Contracts and signing", "operations", False,
     "Agreements signed and sealed, with an audit trail.", "signadoc"),
    ("automations", "Automations", "operations", False,
     "The glue between tools that have no API to each other.", ""),
    ("venue-system", "Venue and event system", "operations", False,
     "The system a venue or client already runs, synced both ways.", "tripleseat"),

    ("mailbox", "Business mailbox", "comms", True,
     "People's inboxes on the business's own domain.",
     "google-workspace-the-client-s-business-mailbox"),
    ("email", "Transactional email", "comms", True,
     "Mail the app sends: receipts, invites, resets.", "resend,postmark,gmail-smtp"),
    ("texting", "Texting", "comms", False,
     "SMS to customers and staff, registered in the business's name.", "twilio"),
    ("support", "Support channel", "comms", False,
     "Where customers write in, and who answers.", ""),

    ("business-profile", "Google Business Profile", "growth", False,
     "The listing people find before the website.", "google-business-profile"),
    ("social", "Social", "growth", False,
     "The accounts the business posts from.", ""),
    ("analytics", "Analytics", "growth", False,
     "Who visits, what they do, where they drop.", ""),

    ("ai", "AI", "intelligence", False,
     "Language models behind a feature, on a usage bill.", "llm-apis"),
    ("maps", "Maps and places", "intelligence", False,
     "Geocoding and place data.", "google-maps-platform-places-api-new,openstreetmap"),
    ("moderation", "Content moderation", "intelligence", False,
     "Screening what users upload before anyone else sees it.", ""),
]

# The business's own, not a vendor's: no runbook can be missing on them.
IN_HOUSE = {"web-app", "admin"}

# from, to, why
NEED_LINKS = [
    ("legal-entity", "bank", "The account is opened in the LLC's name, on its EIN."),
    ("legal-entity", "sales-tax", "The permit sits on the LLC's taxpayer number."),
    ("legal-entity", "payments", "The payments account is verified against the LLC and its EIN."),
    ("legal-entity", "texting", "A2P 10DLC registration is in the company's name."),
    ("legal-entity", "assumed-name", "The certificate is the LLC's, filed under the name it trades as."),
    ("payments", "bank", "Payouts land here, a day or two after each charge."),
    ("payments", "accounting", "Every charge, refund and fee is booked here."),
    ("payments", "sales-tax", "The tax collected on each charge is what the return reports."),
    ("bank", "accounting", "Statements reconcile against the books."),
    ("accounting", "sales-tax", "The return's figures come from the books."),
    ("subscriptions", "mobile-apps", "Store subscriptions on both platforms are reconciled here."),
    ("payouts", "bank", "Payouts to people leave from this account."),
    ("domain", "hosting", "DNS points the domain at the app."),
    ("domain", "email", "SPF, DKIM and DMARC on the domain are what let its mail deliver."),
    ("domain", "mailbox", "MX records route the domain's inboxes."),
    ("domain", "website", "The public site answers on the apex."),
    ("code", "hosting", "Push to main and it deploys."),
    ("hosting", "database", "The app's data lives beside it, on the same platform."),
    ("hosting", "monitoring", "Exceptions in the running app report here."),
    ("hosting", "storage", "Uploads go to the bucket, never the container."),
    ("hosting", "web-app", "This is where the app runs."),
    ("web-app", "email", "The app sends its mail through this."),
    ("web-app", "texting", "The app sends its texts through this."),
    ("web-app", "payments", "The app takes payment through this."),
    ("web-app", "mobile-apps", "The phone apps are the same product, wrapped for the stores."),
    ("web-app", "admin", "Tickets, sales and costs flow here."),
    ("web-app", "venue-system", "Events and bookings sync both ways."),
    ("web-app", "automations", "Feeds from tools with no API arrive here."),
    ("web-app", "contracts", "Agreements go out for signature from the app."),
    ("web-app", "ai", "Features in the app call the models."),
    ("web-app", "maps", "Addresses and places resolve through this."),
    ("web-app", "moderation", "Uploads are screened before they are shown."),
    ("web-app", "analytics", "Visits and events are measured here."),
    ("admin", "payments", "Invoices are raised here and paid through this."),
    ("mailbox", "support", "Customers write to an inbox on the domain."),
]

# business slug -> [(need slug, playbook slug or None, name if no playbook, role, status, url)]
SERVICES = {
    "entertainhq": [
        ("legal-entity", "legalzoom", "LegalZoom", "Filed EntertainHQ LLC with the Texas Secretary of State, Oct 2026.", "running", "https://www.legalzoom.com"),
        ("sales-tax", "texas-sales-tax", "", "Registered Oct 28, 2026; first return Q4 2026. Stripe Tax collects it.", "running", ""),
        ("bank", None, "Mercury", "The business bank account, in the LLC's name.", "running", "https://mercury.com"),
        ("payments", "stripe", "", "Subscriptions and invoices, with Stripe Tax working out and collecting the sales tax.", "running", ""),
        ("domain", "cloudflare", "", "DNS for entertainhq.com, in front of the app.", "running", ""),
        ("hosting", "railway", "", "The Flask app and its workers; push to main deploys.", "running", ""),
        ("database", "postgres", "", "Every tenant's data, with Railway's daily backups.", "running", ""),
        ("code", "github", "", "The repo, and what deploys from it.", "running", ""),
        ("storage", "aws", "", "S3 for media: headshots, costume photos, documents.", "running", ""),
        ("web-app", None, "EntertainHQ", "The product: staff, talent and client portals.", "running", "https://entertainhq.com"),
        ("email", "resend", "", "Every mail the app sends, from the product's own domain.", "running", ""),
        ("mailbox", "google-workspace-the-client-s-business-mailbox", "Google Workspace", "People's inboxes on entertainhq.com, live since Sep 27, 2026.", "running", ""),
        ("texting", "twilio", "", "SMS to talent and staff, behind the consent gate.", "running", ""),
        ("contracts", "signadoc", "", "Talent contracts and client agreements, signed and sealed.", "running", ""),
        ("venue-system", "tripleseat", "", "Events and bookings synced from the venue's system.", "running", ""),
        ("automations", None, "Zapier", "The inbound catch endpoint for feeds from tools with no API.", "setting_up", "https://zapier.com"),
        ("admin", None, "Built by Bean board", "Tickets, sales tax returns and costs, over the hub.", "running", "https://builtbybeans.com/admin"),
    ],
    "data-dungeon": [
        ("hosting", "railway", "", "Where the app runs.", "running", ""),
        ("database", "postgres", "", "The data, with Railway's backups.", "running", ""),
        ("code", "github", "", "The repo, and what deploys from it.", "running", ""),
        ("domain", "cloudflare", "", "DNS for datadungeon.io.", "running", ""),
        ("monitoring", "sentry", "", "Exceptions from the app and the phone builds.", "running", ""),
        ("web-app", None, "Data Dungeon", "The product.", "running", "https://datadungeon.io"),
        ("mobile-apps", "capacitor", "", "The iOS build, wrapped from the web app.", "running", ""),
        ("mobile-apps", "app-store", "", "The listing, review and TestFlight.", "running", ""),
        ("subscriptions", "revenuecat", "", "Store subscriptions, reconciled across platforms.", "running", ""),
        ("payments", "stripe", "", "Web subscriptions.", "running", ""),
        ("email", "resend", "", "Mail the app sends.", "running", ""),
        ("ai", "llm-apis", "", "The models behind the dungeon.", "running", ""),
        ("moderation", None, "Google Vision", "Screens uploaded images before they are shown.", "running", ""),
    ],
    "built-by-bean": [
        ("legal-entity", "legalzoom", "LegalZoom", "Filed Built by Bean LLC, Jan 2024.", "running", "https://www.legalzoom.com"),
        ("sales-tax", "texas-sales-tax", "", "Registered Oct 28, 2026; quarterly returns from Q2 2026.", "running", ""),
        ("payments", "stripe", "", "Client invoices and hosting subscriptions, with the 6.6% sales tax rate.", "running", ""),
        ("hosting", "railway", "", "This board and every client app it hosts.", "running", ""),
        ("database", "postgres", "", "The board's data.", "running", ""),
        ("code", "github", "", "Every repo, public and private.", "running", ""),
        ("storage", "aws", "", "Cost Explorer for the AWS bill; uploads live on the volume.", "running", ""),
        ("web-app", None, "builtbybeans.com", "The site, and the project manager under /admin.", "running", "https://builtbybeans.com"),
        ("email", "gmail-smtp", "", "Mail the board sends and reads, through the Gmail app password.", "running", ""),
        ("contracts", "signadoc", "", "SOWs, hosting agreements and revenue shares, signed through the portal.", "running", ""),
        ("ai", "llm-apis", "", "Claude, building the apps.", "running", ""),
    ],
}


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    have = _tables()
    if "business_needs" not in have:
        op.create_table(
            "business_needs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("slug", sa.String(length=40), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("layer", sa.String(length=20), nullable=False, server_default="operations"),
            sa.Column("essential", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("in_house", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("description", sa.String(length=400), nullable=True),
            sa.Column("fills_with", sa.String(length=300), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.PrimaryKeyConstraint("id", name="pk_business_needs"),
            sa.UniqueConstraint("slug", name="uq_business_needs_slug"),
        )
        op.create_index("ix_business_needs_layer", "business_needs", ["layer"])
    if "business_need_links" not in have:
        op.create_table(
            "business_need_links",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("from_need_id", sa.Integer(), nullable=False),
            sa.Column("to_need_id", sa.Integer(), nullable=False),
            sa.Column("why", sa.String(length=300), nullable=True),
            sa.ForeignKeyConstraint(["from_need_id"], ["business_needs.id"], ondelete="CASCADE",
                                    name="fk_business_need_links_from"),
            sa.ForeignKeyConstraint(["to_need_id"], ["business_needs.id"], ondelete="CASCADE",
                                    name="fk_business_need_links_to"),
            sa.PrimaryKeyConstraint("id", name="pk_business_need_links"),
            sa.UniqueConstraint("from_need_id", "to_need_id", name="uq_business_need_link"),
        )
        op.create_index("ix_business_need_links_from_need_id", "business_need_links", ["from_need_id"])
        op.create_index("ix_business_need_links_to_need_id", "business_need_links", ["to_need_id"])
    if "business_services" not in have:
        op.create_table(
            "business_services",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("need_id", sa.Integer(), nullable=True),
            sa.Column("playbook_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=100), nullable=True),
            sa.Column("layer", sa.String(length=20), nullable=True),
            sa.Column("role", sa.String(length=400), nullable=True),
            sa.Column("status", sa.String(length=12), nullable=False, server_default="running"),
            sa.Column("url", sa.String(length=300), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                    name="fk_business_services_business_id"),
            sa.ForeignKeyConstraint(["need_id"], ["business_needs.id"], ondelete="SET NULL",
                                    name="fk_business_services_need_id"),
            sa.ForeignKeyConstraint(["playbook_id"], ["playbooks.id"], ondelete="SET NULL",
                                    name="fk_business_services_playbook_id"),
            sa.PrimaryKeyConstraint("id", name="pk_business_services"),
        )
        op.create_index("ix_business_services_business_id", "business_services", ["business_id"])
        op.create_index("ix_business_services_need_id", "business_services", ["need_id"])
        op.create_index("ix_business_services_playbook_id", "business_services", ["playbook_id"])
    if "business_links" not in have:
        op.create_table(
            "business_links",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("from_service_id", sa.Integer(), nullable=False),
            sa.Column("to_service_id", sa.Integer(), nullable=False),
            sa.Column("why", sa.String(length=300), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                    name="fk_business_links_business_id"),
            sa.ForeignKeyConstraint(["from_service_id"], ["business_services.id"], ondelete="CASCADE",
                                    name="fk_business_links_from"),
            sa.ForeignKeyConstraint(["to_service_id"], ["business_services.id"], ondelete="CASCADE",
                                    name="fk_business_links_to"),
            sa.PrimaryKeyConstraint("id", name="pk_business_links"),
        )
        op.create_index("ix_business_links_business_id", "business_links", ["business_id"])
        op.create_index("ix_business_links_from_service_id", "business_links", ["from_service_id"])
        op.create_index("ix_business_links_to_service_id", "business_links", ["to_service_id"])

    seed()


def seed():
    bind = op.get_bind()
    need_ids = {}
    for i, (slug, name, layer, essential, description, fills) in enumerate(NEEDS):
        row = bind.execute(sa.text("SELECT id FROM business_needs WHERE slug = :slug"),
                           {"slug": slug}).first()
        if row is None:
            bind.execute(sa.text(
                "INSERT INTO business_needs (slug, name, layer, essential, in_house, description, "
                "fills_with, sort_order) VALUES (:slug, :name, :layer, :essential, :in_house, "
                ":description, :fills, :sort)"),
                {"slug": slug, "name": name, "layer": layer, "essential": essential,
                 "in_house": slug in IN_HOUSE, "description": description, "fills": fills,
                 "sort": (i + 1) * 10})
            row = bind.execute(sa.text("SELECT id FROM business_needs WHERE slug = :slug"),
                               {"slug": slug}).first()
        need_ids[slug] = row[0]

    for a, b, why in NEED_LINKS:
        exists = bind.execute(sa.text(
            "SELECT id FROM business_need_links WHERE from_need_id = :a AND to_need_id = :b"),
            {"a": need_ids[a], "b": need_ids[b]}).first()
        if exists is None:
            bind.execute(sa.text(
                "INSERT INTO business_need_links (from_need_id, to_need_id, why) "
                "VALUES (:a, :b, :why)"), {"a": need_ids[a], "b": need_ids[b], "why": why})

    if "playbooks" not in _tables() or "businesses" not in _tables():
        return
    playbook_ids = {r[0]: r[1] for r in bind.execute(sa.text("SELECT slug, id FROM playbooks"))}
    for business_slug, services in SERVICES.items():
        biz = bind.execute(sa.text("SELECT id FROM businesses WHERE slug = :slug"),
                           {"slug": business_slug}).first()
        if biz is None:
            continue
        # A business with a map already is somebody's work: leave it alone.
        if bind.execute(sa.text("SELECT 1 FROM business_services WHERE business_id = :b"),
                        {"b": biz[0]}).first() is not None:
            continue
        for need_slug, pb_slug, name, role, status, url in services:
            pb_id = playbook_ids.get(pb_slug) if pb_slug else None
            if pb_id is None and not name:
                name = (pb_slug or need_slug).replace("-", " ").title()
            bind.execute(sa.text(
                "INSERT INTO business_services (business_id, need_id, playbook_id, name, layer, "
                "role, status, url, notes, created_at) VALUES (:b, :need, :pb, :name, '', :role, "
                ":status, :url, :notes, :now)"),
                {"b": biz[0], "need": need_ids.get(need_slug), "pb": pb_id, "name": name,
                 "role": role, "status": status, "url": url,
                 "notes": "Seeded from the repo on 2026-11-02; confirm it.", "now": NOW})


def downgrade():
    have = _tables()
    for table in ("business_links", "business_services", "business_need_links", "business_needs"):
        if table in have:
            op.drop_table(table)
