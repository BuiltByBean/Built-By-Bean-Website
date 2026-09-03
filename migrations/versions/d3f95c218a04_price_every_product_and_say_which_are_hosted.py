"""Price every product, and say which ones I end up hosting

Two things were missing from the catalogue. Eight products had no number, and
nothing recorded which of them leave me running something afterwards.

The second matters more than it looks. Most of these put something on my
infrastructure and bring the monthly hosting and storage fee with them -
that is the recurring half of the business. Routing somebody's mail through
their own domain does not: it is DNS records on a domain they own, nothing of
mine runs anywhere afterwards, and billing rent for it would be billing for
nothing. Email is the only one seeded false.

The prices are judgement, anchored on the two Michael set himself - $1,000 for
texting and $2,500 for invoicing and payments - and on what each one actually
took to build in Kuper Plumbing and Talent Booker. Read as: cheaper than an
agency, not cheap.

Revision ID: d3f95c218a04
Revises: c7e2f04b8163
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa


revision = "d3f95c218a04"
down_revision = "c7e2f04b8163"
branch_labels = None
depends_on = None


# slug -> (price, includes_hosting, icon)
#
# A price of None stays quoted. The custom build is the only one: it is the
# largest thing here and the only one with no standard shape to price.
PRICING = {
    # Michael's own numbers, left alone.
    "custom-build":  (None,   True,  "code"),
    "texting":       (1000.0, True,  "chat"),
    "billing":       (2500.0, True,  "receipt"),
    "signadoc":      (1000.0, True,  "signature"),

    # Mine. Reasoning in the commit; the short version is below.
    #
    # The biggest add-on there is. Tripleseat was seven models, a sync log,
    # webhook enforcement and suppression handling - more work than billing,
    # and bespoke to whichever system is on the far end. Variant overrides
    # carry the ones that turn out worse.
    "api-connection": (2500.0, True,  "link"),
    # Seven models with categories, tags, photos and per-job commitments.
    "inventory":      (1500.0, True,  "boxes"),
    # Roster, rates, availability, check-in, and a public application form.
    "roster":         (1500.0, True,  "users"),
    # Priced for adding it to something that already exists. On a trades build
    # scheduling usually IS the custom build, and charging for both would be
    # charging twice for one thing.
    "scheduling":     (1500.0, True,  "calendar"),
    # Two models and reporting shaped for a tax return. Texting money.
    "time-mileage":   (1000.0, True,  "clock"),
    # The church build's editable pages. Worth real money to both sides: it is
    # the one that stops them coming back for wording changes.
    "content":        (1000.0, True,  "document"),
    # Honestly small - a trigger, a link, a recorded answer. $1,000 would be
    # padding, and padding one line item is how a whole price list stops being
    # believed.
    "reviews":        (750.0,  True,  "star"),
    # The only one that leaves nothing of mine running. Priced low because it
    # is an afternoon and DNS propagation, and because a system that cannot
    # send mail is broken - this is close to the floor of what can fairly be
    # charged for separately at all.
    "email":          (500.0,  False, "envelope"),
}


def upgrade():
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("products")}

    if "includes_hosting" not in columns:
        op.add_column("products", sa.Column(
            "includes_hosting", sa.Boolean(), nullable=False,
            server_default=sa.true()))
    if "icon" not in columns:
        op.add_column("products", sa.Column("icon", sa.String(length=30),
                                            nullable=True))

    for slug, (price, hosted, icon) in PRICING.items():
        bind.execute(sa.text("""
            UPDATE products
               SET price = COALESCE(:price, price),
                   includes_hosting = :hosted,
                   icon = :icon
             WHERE slug = :slug
        """), {"price": price, "hosted": hosted, "icon": icon, "slug": slug})


def downgrade():
    op.drop_column("products", "icon")
    op.drop_column("products", "includes_hosting")
