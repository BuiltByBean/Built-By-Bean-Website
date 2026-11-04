"""Best Practices and the MVP Builder hold no money

Michael, 2026-11-03, on Best Practices: "no price shit left over", and of the
MVP Builder, 2026-11-04: no money at all. What a build costs is typed on the
SOW form. Product prices stay on the Products page, where the sell flow writes
them onto a sale, and that page has left Best Practices.

Goes: features.typical_value, mvp_packages.price_override, and
mvp_package_items.price and monthly_price. The two packages on the board were
tests. The downgrade puts the feature figures back as they were on 2026-11-03;
the package columns come back empty.

Revision ID: b8e4d17a6c30
Revises: c3e7a1f90b42
"""
from alembic import op
import sqlalchemy as sa


revision = "b8e4d17a6c30"
down_revision = "c3e7a1f90b42"
branch_labels = None
depends_on = None


GOING = (
    ("features", "typical_value"),
    ("mvp_packages", "price_override"),
    ("mvp_package_items", "price"),
    ("mvp_package_items", "monthly_price"),
)
# features.typical_value by slug, as it stood, for the downgrade alone.
WAS = {
    'applications': 700,
    'ask-off-workflow': 500,
    'ask-them-mid-job': 400,
    'asset-checkout': 800,
    'asset-registry': 1200,
    'booking-availability': 1800,
    'broadcast-engine': 900,
    'bulk-invites': 700,
    'calendar-feeds': 400,
    'client-cms': 1000,
    'credits-ledger': 600,
    'csv-import-mapper': 900,
    'customer-records': 600,
    'day-of-brief': 300,
    'day-of-checkin': 600,
    'document-filing': 400,
    'editable-templates': 400,
    'email-that-renders': 400,
    'expense-receipts': 500,
    'full-text-search': 600,
    'guided-intake': 800,
    'guided-tours': 600,
    'inquiry-form': 400,
    'instant-ballpark': 600,
    'inventory': 1500,
    'invite-registration': 500,
    'invoice-pdf': 800,
    'job-scheduling': 1500,
    'kpi-dashboard': 900,
    'magic-link': 400,
    'mileage': 400,
    'notification-log': 300,
    'pay-by-link': 800,
    'payroll-tracking': 500,
    'photo-capture': 400,
    'program-builder': 1500,
    'progress-prs': 700,
    'proposals': 700,
    'records-before-logins': 500,
    'referrals': 700,
    'review-requests': 400,
    'route-optimizer': 800,
    'sales-tax-by-jurisdiction-from-the-state-s-own-table': 1200,
    'search-across-everything': 900,
    'self-serve-reschedule': 700,
    'signature-context': 500,
    'smart-substitutions': 900,
    'sms-roi': 600,
    'tagging': 300,
    'the-way-out-export-everything': 450,
    'ticket-thread': 700,
    'time-tracking': 500,
}


def _cols(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    for table, column in GOING:
        if column in _cols(table):
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column)


def downgrade():
    for table, column in reversed(GOING):
        if column not in _cols(table):
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column(column, sa.Float(), nullable=True))
    bind = op.get_bind()
    for slug, value in WAS.items():
        bind.execute(sa.text("UPDATE features SET typical_value = :v WHERE slug = :s"),
                     {"v": value, "s": slug})
