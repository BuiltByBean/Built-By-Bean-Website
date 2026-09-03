"""Rules become their own kind, under the features

There are things that get sold, and there is the layer beneath them: ways
of building that must not be broken no matter which features were bought.
The catalogue held both in one undifferentiated list, so the nitpicky
rules - the tojson quoting, the stacking contexts, the migration guards -
sat between priced capabilities where nobody browses for them.

One column splits them. Every guidance-bearing pattern that was never
really for sale becomes kind "rule"; the sellable capabilities stay
"feature". The rules get their own page, they all ride into every build
prompt, and they stay out of the MVP picker.

Also seeds the first rule written as a rule: contained scroll for list
pages, learned today after its sticky predecessor shipped wrong twice.

Revision ID: a4b83e51c7d0
Revises: f0a72d51e3c8
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa


revision = "a4b83e51c7d0"
down_revision = "f0a72d51e3c8"
branch_labels = None
depends_on = None


# Patterns, not products: guidance that applies to how anything gets built,
# with nothing a client would ever buy by name.
RULE_SLUGS = (
    "jinja-attr-quoting", "teleported-dropdown", "timezones",
    "cascade-deletes", "badge-counts", "empty-states", "stat-tiles",
    "mobile-chrome", "fk-indexes", "migrations-with-create-all",
    "media-volume", "role-guards", "third-party-sync",
    "booking-enforcement", "data-pipeline", "frozen-prices",
    "queue-first-sending", "signed-webhooks", "content-registry",
    "sync-preserves-edits", "admin-auth", "secrets-fail-closed",
    "permission-matrix", "railway-deploys", "route-integrity",
    "landmine-scanners", "per-seat-redaction", "corporate-tls",
    "audio-timing", "phone-filter-bars", "page-anatomy", "no-flash-dark",
    "two-audiences",
)

NEW_RULE = {
    "slug": "contained-scroll-lists",
    "name": "A list page scrolls inside itself",
    "category": "ui",
    "summary": "Search-and-filter over results: the window never scrolls, "
               "the bar stands still, the results scroll in their own "
               "container.",
    "gold": "When the list IS the page, the main area is sized to the room "
            "under the header and clipped, the filter bar is a normal block "
            "that simply stands still, and the results region is the one "
            "scroller (flex column, min-h-0, overflow-y-auto) - so the "
            "scrollbar starts below the bar, never up the full viewport. "
            "Sticky bars are only for MIXED pages, where content above the "
            "list must itself scroll away; there they sit flush under the "
            "header with a solid background.",
    "pitfalls": "This board shipped the sticky version twice before landing "
                "here: first with a gap the rows scrolled through in the "
                "clear, then with glass the rows read straight through. A "
                "window-level scrollbar running the full viewport height on "
                "a filtered list page is the tell that the page is built "
                "wrong.",
    "project": "Built By Bean (this board)",
    "path": "templates/pm/base.html (.contained-scroll), "
            "templates/pm/features/index.html",
}


def upgrade():
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("features")}
    if "kind" not in columns:
        op.add_column("features", sa.Column(
            "kind", sa.String(length=10), nullable=False,
            server_default="feature"))
        op.create_index("ix_features_kind", "features", ["kind"])

    slugs = ", ".join(f"'{s}'" for s in RULE_SLUGS)
    bind.execute(sa.text(
        f"UPDATE features SET kind = 'rule' WHERE slug IN ({slugs})"))

    exists = bind.execute(sa.text(
        "SELECT 1 FROM features WHERE slug = :s"), {"s": NEW_RULE["slug"]}
    ).first()
    if not exists:
        last = bind.execute(sa.text(
            "SELECT COALESCE(MAX(sort_order), 0) FROM features")).scalar()
        bind.execute(sa.text("""
            INSERT INTO features
                (slug, name, category, summary, typical_value,
                 gold_standard_md, pitfalls_md, reference_project,
                 reference_path, status, kind, is_active, sort_order)
            VALUES
                (:slug, :name, :category, :summary, NULL,
                 :gold, :pitfalls, :project, :path,
                 'built', 'rule', :active, :sort)
        """), {"slug": NEW_RULE["slug"], "name": NEW_RULE["name"],
               "category": NEW_RULE["category"],
               "summary": NEW_RULE["summary"], "gold": NEW_RULE["gold"],
               "pitfalls": NEW_RULE["pitfalls"],
               "project": NEW_RULE["project"], "path": NEW_RULE["path"],
               "active": True, "sort": last + 10})


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM features WHERE slug = :s"),
                 {"s": NEW_RULE["slug"]})
    op.drop_index("ix_features_kind", table_name="features")
    op.drop_column("features", "kind")
