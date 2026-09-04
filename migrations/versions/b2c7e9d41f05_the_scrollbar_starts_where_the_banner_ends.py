"""The scrollbar starts where the banner ends

A rule, written as a rule: on any page with a banner, the window never
scrolls. The region under the banner is the one scroller, so the scrollbar
begins at the banner's bottom edge and never runs up behind it. The board
shipped the other way on every page, and the owner named the fix in a line.
The contained-scroll rule for list pages still holds inside it.

Seeded here the way the first rule was, so it rides into every build prompt
from the next deploy rather than waiting to be typed in.

Revision ID: b2c7e9d41f05
Revises: f1d63a08c527
Create Date: 2026-09-04

"""
from alembic import op
import sqlalchemy as sa


revision = "b2c7e9d41f05"
down_revision = "f1d63a08c527"
branch_labels = None
depends_on = None


RULE = {
    "slug": "scroller-under-banner",
    "name": "The scrollbar starts where the banner ends",
    "category": "ui",
    "summary": "On any page with a banner the window never scrolls: the "
               "region under the banner is the one scroller, so the "
               "scrollbar begins at the banner's bottom edge and never runs "
               "up behind it.",
    "gold": "Build the shell as a viewport-high column that is clipped: "
            "height 100vh, then 100dvh where the browser has it, so a phone "
            "toolbar cannot hide the last rows. The banner is a plain block "
            "at the top of it. The region under the banner is the ONE "
            "scroller: flex 1, min-height 0, overflow-y auto, overflow-x "
            "hidden. Nothing is sticky at the window level, because the "
            "window never moves. A filter bar that must pin does so inside "
            "the scroller at top 0, flush under the banner, with a solid "
            "background and no header height to measure. Anything that "
            "moves the page moves that box (scroller.scrollTop), never "
            "window.scrollTo, scroll memory included. A page that is one "
            "filtered list (see the contained-scroll rule) fills the "
            "scroller and clips, so its results region is the only thing "
            "that moves. Verify on every page: documentElement.scrollHeight "
            "is at most innerHeight, and the scroller's top edge equals the "
            "banner's bottom edge; sweep sideways overflow on the scroller's "
            "scrollWidth, because it clips what the window used to show.",
    "pitfalls": "A sticky banner over a scrolling window is correct in every "
                "screenshot, and the tell is only at the right edge: the "
                "scrollbar runs the full height of the viewport, up behind "
                "the banner. This board shipped that way on every page until "
                "the owner named it in one line: the scrollbar stops at the "
                "bottom of the banner. Converting is a layout change with "
                "two silent breakages: anything that read window.scrollY or "
                "called window.scrollTo stops working and reports nothing "
                "(grep for both), and a sticky bar offset by a measured "
                "header height is now offset exactly that far too low, since "
                "the banner is no longer inside its scroller.",
    "project": "Built By Bean (this board)",
    "path": "templates/pm/base.html (.pm-shell, #pm-scroll, .sticky-filters)",
}


def upgrade():
    bind = op.get_bind()
    exists = bind.execute(sa.text(
        "SELECT 1 FROM features WHERE slug = :s"), {"s": RULE["slug"]}).first()
    if exists:
        return
    last = bind.execute(sa.text(
        "SELECT COALESCE(MAX(sort_order), 0) FROM features")).scalar()
    # Bound parameters for every piece of text: Postgres and SQLite disagree
    # about multi-line string literals, and these are long.
    bind.execute(sa.text("""
        INSERT INTO features
            (slug, name, category, summary, typical_value,
             gold_standard_md, pitfalls_md, reference_project,
             reference_path, status, kind, is_active, sort_order,
             created_at, updated_at)
        VALUES
            (:slug, :name, :category, :summary, NULL,
             :gold, :pitfalls, :project, :path,
             'built', 'rule', :active, :sort,
             CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """), {"slug": RULE["slug"], "name": RULE["name"],
           "category": RULE["category"], "summary": RULE["summary"],
           "gold": RULE["gold"], "pitfalls": RULE["pitfalls"],
           "project": RULE["project"], "path": RULE["path"],
           "active": True, "sort": last + 10})


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM features WHERE slug = :s"),
                 {"s": RULE["slug"]})
