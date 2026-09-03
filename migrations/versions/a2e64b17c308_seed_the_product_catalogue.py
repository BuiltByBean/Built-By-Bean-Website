"""Seed the product catalogue

The five Michael named, at the prices he set, plus the ones a read of the
client builds turned up. Those last carry no price: a figure nobody has
decided is worse than a blank, because a blank asks to be filled and a guess
gets quoted.

Slugs match contract_docs.PRODUCTS where an entry already exists there, so the
add-on contract for texting, signatures, card payments and email keeps using
the wording that was already written for it.

Revision ID: a2e64b17c308
Revises: f8b3c1d09a47
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column


revision = "a2e64b17c308"
down_revision = "f8b3c1d09a47"
branch_labels = None
depends_on = None


# (slug, name, summary, price, playbook_slug, sort_order)
CATALOGUE = [
    ("custom-build", "Custom software build",
     "The system itself, built for how the business actually runs. Priced per "
     "project after a scoping conversation.",
     None, None, 0),

    ("texting", "Text messaging",
     "Texts that go out on their own - reminders, confirmations, day-of "
     "notices - from a number that belongs to the business.",
     1000.0, "twilio", 10),

    ("payments", "Card payments",
     "Customers pay through the software. The money lands in the client's own "
     "account; they stay merchant of record.",
     1000.0, "stripe", 20),

    ("signadoc", "Electronic signatures",
     "Documents sent for signature from inside the system, signed in a "
     "browser, filed back against the record they came from.",
     1000.0, None, 30),

    ("invoicing", "Invoice generation",
     "Invoices built from the work already recorded, as PDFs, without "
     "retyping any of it.",
     1000.0, None, 40),

    ("email", "Email from your own domain",
     "Mail that arrives from the business rather than from a shared address, "
     "with the records that prove it is theirs.",
     None, "resend", 50),

    # ── Turned up by reading the builds. Unpriced until Michael sets one. ──

    ("crm-sync", "Sync with a system you already use",
     "Two-way sync with the platform the business already runs on. Talent "
     "Booker's Tripleseat integration is seven models, a sync log and webhook "
     "handling - bespoke to whichever system it is, every time.",
     None, None, 60),

    ("scheduling", "Scheduling and dispatch",
     "Jobs or events on a calendar, assigned to people, with the day-of "
     "handling that goes with it.",
     None, None, 70),

    ("inventory", "Inventory management",
     "What the business owns, where it is, what it is tagged with, and what is "
     "committed to which job. Talent Booker's costume tracking is this.",
     None, None, 80),

    ("reviews", "Review requests",
     "Asking for the review automatically once the work is finished, and "
     "recording what came back.",
     None, None, 90),

    ("time-mileage", "Time and mileage tracking",
     "Hours and miles captured against the job as they happen, ready for "
     "billing and for the tax return.",
     None, None, 100),

    ("roster", "Staff roster and applications",
     "The people who work for them: availability, rates, check-in, and a form "
     "for new ones to apply through.",
     None, None, 110),

    ("content", "Client-editable site content",
     "The pages, team, FAQs and announcements editable by the client without "
     "coming back to me for wording changes.",
     None, None, 120),
]


def upgrade():
    products = table(
        "products",
        column("slug", sa.String),
        column("name", sa.String),
        column("summary", sa.Text),
        column("price", sa.Float),
        column("playbook_slug", sa.String),
        column("is_active", sa.Boolean),
        column("sort_order", sa.Integer),
        column("prompt_intro", sa.Text),
    )
    # Skip anything already there, for the same reason the table creation is
    # guarded: the app may have been opened against this database before the
    # migration shipped, and a second copy of a product would give the
    # catalogue two rows with the same slug and one unique constraint to fail
    # on.
    bind = op.get_bind()
    have = {row[0] for row in bind.execute(sa.text("SELECT slug FROM products"))}
    rows = [
        {"slug": slug, "name": name, "summary": summary, "price": price,
         "playbook_slug": playbook, "is_active": True, "sort_order": order,
         "prompt_intro": ""}
        for slug, name, summary, price, playbook, order in CATALOGUE
        if slug not in have
    ]
    if rows:
        op.bulk_insert(products, rows)


def downgrade():
    slugs = ", ".join(f"'{row[0]}'" for row in CATALOGUE)
    op.execute(f"DELETE FROM products WHERE slug IN ({slugs})")
