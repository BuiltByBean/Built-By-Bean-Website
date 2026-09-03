"""Seed the feature catalogue from what has already been built

Every entry here is real: a capability that exists in Kuper Plumbing, Talent
Booker, Christ Community Church or this board, with the file worth copying
named, and the pitfalls taken from the landmines those projects recorded the
day each one cost an afternoon.

Talent Booker's CLAUDE.md carries 53 of those and Data Dungeon's docs carry
34. All 87 are trapped in the repository that learned them. Talent Booker's
LM-19 - a `|tojson` inside a double-quoted HTML attribute breaks the attribute
- describes a bug shipped from THIS repository on 2026-09-03, because nothing
here could see what was written over there. The pitfalls column is the fix for
that, and it is why several entries below are patterns rather than features
anybody would sell.

Revision ID: a91c53e0d7b4
Revises: f4c08b2e7a15
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column


revision = "a91c53e0d7b4"
down_revision = "f4c08b2e7a15"
branch_labels = None
depends_on = None


TB = "Talent Booker"
KP = "Kuper Plumbing"
CCC = "Christ Community Church"
PM = "Built By Bean (this board)"
DD = "Data Dungeon"

# slug, name, category, summary, value, gold standard, pitfalls, project, path
CATALOGUE = [
 ("inquiry-form", "Public enquiry form", "intake",
  "A form on the public site that turns a stranger into a record: name, "
  "contact, what they want.", 400.0,
  "Write straight to a real record rather than an inbox, so nothing depends "
  "on somebody reading email. Confirm on screen and by mail.",
  "Truncate every field to its column bound - a public endpoint is the one "
  "place unbounded input arrives. Honeypot the spam. Never `int()` a raw form "
  "value: a non-numeric string 500s the page (TB LM-28, LM-31).",
  KP, "routes/public.py"),

 ("guided-intake", "Guided intake questions", "intake",
  "A branching questionnaire that asks what the job actually needs, so the "
  "first call is not a fact-finding call.", 800.0,
  "Model the questions as data, not templates - a taxonomy with follow-ups "
  "hanging off answers. The business changes its own questions without a "
  "deploy.", "", KP, "models.py (TaxonomyNode, FollowUpQuestion, ScopeSetting)"),

 ("applications", "Applications from the public", "intake",
  "People applying to work for them: a public form that lands in a roster as "
  "a pending record.", 700.0,
  "An application is its own record with a status, not a half-made user. "
  "Approving it creates the profile.",
  "A signup that writes a User but no profile leaves somebody who can log in "
  "and see nothing, and spawns duplicate roster rows on the next attempt "
  "(TB LM-13).", TB, "models.py (TalentApplication)"),

 ("booking-availability", "Booking against real availability", "scheduling",
  "The customer picks a day, sees only times that are actually free, and "
  "books one. The haircut model.", 1800.0,
  "Availability is its own record per person, and the slot offered is "
  "computed from it rather than stored. Booking writes a slot; nothing is "
  "double-sold because the read and the write use the same source.",
  "A per-booking field wired on one booking path silently does nothing on the "
  "others - direct add, casting call and self-serve are three paths to the "
  "same row (TB LM-20).",
  TB, "models.py (TalentAvailability, Booking, TalentSlot)"),

 ("job-scheduling", "Job scheduling and dispatch", "scheduling",
  "Work on a calendar, assigned to somebody, with the day-of handling that "
  "goes with it.", 1500.0,
  "Comes with the custom build rather than being sold on top - a business "
  "that books jobs needs a screen to book jobs on.", "",
  KP, "services/scheduling.py"),

 ("day-of-checkin", "Day-of check-in", "scheduling",
  "Who turned up, when, and why anybody was late.", 600.0,
  "Check-in is a record with a time, not a boolean. Late is a reason code so "
  "it can be counted later.", "",
  TB, "models.py (TalentCheckIn, EventDayOfNotice, TardyReason)"),

 ("customer-records", "Customer and site records", "records",
  "Who they are, where the work happens, and everything filed against both.",
  600.0,
  "Separate the customer from the place - one customer can have several "
  "properties and the history belongs to the place as much as the person.",
  "", KP, "models.py (Customer, Property)"),

 ("tagging", "Tagging that can be searched", "records",
  "Free-form labels on a record that survive being searched for more than one "
  "at a time.", 300.0,
  "Tags are rows with a join table, never a comma-separated string in a "
  "column. Searching for two tags is then an intersection instead of a LIKE "
  "that cannot express it. Categories above tags where the vocabulary is "
  "known.",
  "A comma-separated column cannot answer \"gold AND black\" - the query "
  "either misses rows or matches substrings of other tags. Talent Booker was "
  "rebuilt away from exactly that, and the client ticket asking for "
  "multi-tag search is what forced it.",
  TB, "models.py (CostumeTag, CostumeCategory, CostumeItem)"),

 ("photo-capture", "Photos against a record", "records",
  "Pictures taken on a phone, attached to the job, visible to whoever needs "
  "them.", 400.0,
  "Store a bare relative path in the database and build the URL at render "
  "time.",
  "Never build a full URL in a route handler - the moment the media backend "
  "or the domain changes, every stored row is wrong (TB LM-7).",
  KP, "models.py (JobPhoto), services/records.py"),

 ("inventory", "Inventory with categories and tags", "records",
  "What the business owns, where it is, and what is committed to which job.",
  1500.0,
  "Items, categories, tags and photos are separate tables. Commitment to a "
  "job is its own row so an item can be reserved without being moved.", "",
  TB, "models.py (CostumeItem, CostumeCategory, CostumeTag, CostumeProject)"),

 ("invoice-pdf", "Invoices as PDFs", "money",
  "An invoice built from work already recorded, numbered, and produced as a "
  "document.", 800.0,
  "Generate from the recorded work rather than a typed form, so the invoice "
  "and the job cannot disagree. Number them from a counter row.",
  "reportlab's `Paragraph()` parses its input as mini-HTML - unescaped "
  "customer text with an ampersand or a bracket 500s the PDF (TB LM-29).",
  KP, "services/invoice_pdf.py"),

 ("time-tracking", "Time against the job", "money",
  "Hours captured as they happen, attached to the work they belong to.",
  500.0,
  "Round at display, store exact. A timer that writes on stop is the only "
  "kind that survives a closed laptop.", "", KP, "models.py (TimeEntry)"),

 ("mileage", "Mileage and trips", "money",
  "Miles driven, per job, in the shape a tax return wants.", 400.0,
  "Store the trip, not the total - a total cannot be audited or corrected.",
  "", KP, "models.py (Trip), services/mileage.py"),

 ("expense-receipts", "Expenses with receipts", "money",
  "Money spent on the job, with a photograph of the receipt attached.", 500.0,
  "The receipt is a child record, not a column, so several can attach and one "
  "can be replaced.", "", KP, "models.py (Expense, ExpensePhoto)"),

 ("proposals", "Proposals and quotes", "money",
  "A priced proposal the customer can accept, which then becomes the job.",
  700.0,
  "Accepting a proposal creates the work rather than copying it - the "
  "proposal stays as the record of what was agreed.", "",
  KP, "services/proposals.py"),

 ("sms-consent", "SMS with a consent gate", "comms",
  "Texts that only go to people who agreed to receive them, with the "
  "agreement recorded.", None,
  "Consent is a column checked on the send path, not a policy in a document. "
  "Every send goes through one function.",
  "A send path that skips the gate is an A2P 10DLC violation, not a bug - and "
  "carriers act on it. Talent Booker had one (TB LM-18).",
  TB, "models.py (SmsLog, SmsTemplate), services/notify.py"),

 ("ticket-thread", "Two-way support thread", "comms",
  "The client raises something, you answer, both sides see the same "
  "conversation.", 700.0,
  "One table for both directions, with a delivered timestamp. A reply that "
  "only ever sat in the database, shown as sent, is the failure the column "
  "exists to make visible.",
  "Talent Booker shipped this as outbound email only - the reporter had "
  "nothing to read and nothing to reply to, and it had to be rebuilt.",
  PM, "models.py (Ticket, TicketNote); templates/pm/tickets/list.html"),

 ("notification-log", "A record of what was sent", "comms",
  "Every message the system sent, to whom, and whether it arrived.", 300.0,
  "Log the attempt and the outcome separately. \"Sent\" without a delivery "
  "result is a guess.", "", KP, "models.py (NotificationLog)"),

 ("document-filing", "Documents filed against a record", "documents",
  "PDFs and uploads attached to the client or job they belong to, findable "
  "later.", 400.0,
  "Store the original filename beside the stored one - the stored name is a "
  "uuid and nobody can search for it.", "", PM, "models.py (Document)"),

 ("esign-flow", "Signing in a browser", "documents",
  "A document sent for signature, signed without an account, filed back "
  "against the record it came from.", None,
  "Anchor the signature fields to the drawn lines rather than guessing "
  "coordinates, so the signature lands where the document says to sign.", "",
  PM, "signadoc_service.py, contract_docs.py"),

 ("magic-link", "Access without a password", "portal",
  "A link that signs somebody in, for people who will never create an "
  "account.", 400.0,
  "Gate on the profile that proves what they are, not on a role string. "
  "Expire the token and bind it to the record it opens.",
  "A link to a login-required page must BE a magic link, not a bare URL, or "
  "it lands on a login form (TB LM-22). Gate on `talent_profile`, not "
  "`role == talent` (LM-26). Never render a user-supplied URL raw in an href "
  "- `javascript:` is stored XSS (LM-27).",
  TB, "app.py (/portal/enter/<token>)"),

 ("client-cms", "Content they can edit themselves", "portal",
  "Pages, team, FAQs and announcements the client changes without coming back "
  "to me.", 1000.0,
  "Model each content type properly rather than one blob of HTML. They edit "
  "fields; the design stays yours.", "",
  CCC, "models.py (SiteContent, TeamMember, Belief, FaqItem, Announcement)"),

 ("referrals", "Referral programme", "portal",
  "Partners who send work, what they sent, and what they are owed.", 700.0,
  "The partner, the referral and the document they signed are three records. "
  "Paying out reads from the referral, not from memory.", "",
  KP, "models.py (ReferralPartner, Referral, PartnerDocument)"),

 ("review-requests", "Asking for the review", "portal",
  "The request goes out when the work is finished, and the answer is "
  "recorded.", 400.0,
  "Trigger on the job reaching done, not on a person remembering. Record the "
  "response so the ones who did not answer are visible.", "",
  KP, "models.py (Feedback)"),

 ("media-volume", "Media on a volume, not a bucket", "platform",
  "Uploads served from disk the app already has, with no object store to pay "
  "for or lock into.", None,
  "One backend switch read from config, one storage module, bare relative "
  "paths in the database. Moving between backends is then a migration script "
  "and an environment variable.",
  "Leaving the old backend's credentials on the service after moving off it "
  "is live keys for a bucket nothing reads - Talent Booker still carried four "
  "AWS variables after moving to a volume.",
  TB, "storage.py (MEDIA_BACKEND)"),

 ("third-party-sync", "Sync with somebody else's system", "platform",
  "Reading from, and writing back to, a platform the business already runs "
  "on.", None,
  "Upsert on their id, keep a sync log, and honour their webhook shape "
  "exactly. Suppress locally-deleted records explicitly.",
  "A local delete is resurrected by the next sync unless suppression is "
  "recorded (TB LM-12). An upsert must preserve a populated field when the "
  "payload omits it: `X = new or existing.X` (LM-35). Single-record detail "
  "endpoints are rate-limited - never bulk-fetch them (LM-16). Their webhook "
  "field names are not the obvious ones (LM-15).",
  TB, "tripleseat.py"),

 ("role-guards", "Gating by what somebody is", "platform",
  "Staff, agents, clients and the public seeing only what they should.", None,
  "One decorator per audience, applied on the route. Ownership checked on the "
  "record, not inferred from the URL.",
  "A route that loads a child object by id and then touches its parent skips "
  "the ownership guard entirely (TB LM-17). `@staff_required` is not admin "
  "gating - it lets agents through (LM-37).",
  TB, "app.py (decorators)"),

 ("fk-indexes", "Indexes on foreign keys", "platform",
  "The indexes Postgres does not create for you.", None,
  "Index every foreign key that is queried. Postgres indexes the primary key "
  "and the unique constraints, and nothing else.",
  "Postgres does NOT auto-index foreign keys. A join that was instant on "
  "SQLite crawls in production (TB LM-36).", TB, "models.py"),

 ("migrations-with-create-all", "Migrations beside create_all", "platform",
  "Schema changes that survive an app which also builds its own tables on "
  "boot.", None,
  "Guard every create_table on the table not already existing. The deploy "
  "runs `flask db upgrade`, which loads the app, which runs create_all - so "
  "create_all wins the race and the migration must tolerate it.",
  "Ungarded, the migration dies on CREATE TABLE. With `flask db upgrade && "
  "gunicorn` in the Procfile the site then never starts. This board hit it on "
  "2026-09-03.",
  PM, "migrations/versions/f8b3c1d09a47_products_and_what_was_sold.py"),

 ("jinja-attr-quoting", "Data into an HTML attribute", "ui",
  "Putting a server value into an Alpine or JS handler without breaking the "
  "attribute.", None,
  "Single-quote any attribute containing `|tojson`. Flask's tojson escapes "
  "apostrophes, angle brackets and ampersands - the quotes it writes are "
  "exactly the ones a single-quoted attribute tolerates.",
  "In a double-quoted attribute the value ends at the first quote tojson "
  "writes, and the handler is truncated mid-call with no error anywhere "
  "(TB LM-19). Shipped again from this board on 2026-09-03.",
  TB, "CLAUDE.md LM-19"),

 ("teleported-dropdown", "Dropdowns that are not clipped", "ui",
  "A menu inside a card or a scrolling list that opens over everything "
  "instead of being cut off.", None,
  "Teleport the panel to `<body>` and position it against the trigger. Match "
  "its width to the trigger, and give it a z-index above the drawer.",
  "Inside `overflow:auto` it is clipped (TB LM-8). Floating it in a clipping "
  "ancestor in a list row has the same effect (LM-41). A `relative z-30` card "
  "ties with the mobile drawer and paints over it (LM-53).",
  TB, "CLAUDE.md — Filters & Dropdowns"),

 ("timezones", "Times that are the right times", "ui",
  "Storing, comparing and displaying times without a five-hour drift.", None,
  "Store aware UTC. Convert once, at render. Compare aware with aware.",
  "A UTC audit timestamp printed verbatim as local time is wrong by the "
  "offset (TB LM-4). Piping dates through a formatter shifted them −5h "
  "(LM-10). Subtracting a naive DB datetime from `datetime.now(timezone.utc)` "
  "raises outright (LM-42).", TB, "CLAUDE.md LM-4, LM-10, LM-42"),

 ("cascade-deletes", "Deleting a parent that has children", "platform",
  "Removing a record without a 500 and without orphans.", None,
  "Declare the cascade on the relationship where the child's foreign key is "
  "NOT NULL. Decide deliberately between cascade and SET NULL: a record "
  "somebody was invoiced for should be detached, not destroyed.",
  "Without the cascade the delete 500s, because nulling the key is not "
  "allowed (TB LM-11).", TB, "CLAUDE.md LM-11"),

 ("badge-counts", "Badges that match their page", "ui",
  "A number on a nav item that agrees with what the page shows.", None,
  "Count with the same filter the page renders with - same status, same "
  "dates, same scope. Share the query.",
  "A badge counting a different scope than its page is a bug report every "
  "time somebody clicks it (TB LM-24).", TB, "CLAUDE.md LM-24"),

 ("empty-states", "Empty states that say the state", "ui",
  "What a list shows when there is nothing in it.", None,
  "Name the state and offer the one action that changes it. No explanation of "
  "the feature.", "", DD, "docs/conventions/ui_patterns.md §5"),

 ("stat-tiles", "Stat tiles", "ui",
  "A row of headline numbers with one line of context each.", None,
  "One figure, one label, one line under it. Same shape across every tile in "
  "the row so they read as a set.", "",
  DD, "docs/conventions/ui_patterns.md §6"),

 ("mobile-chrome", "Things that work on a phone", "ui",
  "Sticky bars, touch targets and reveals that survive a real device.", None,
  "44px minimum touch target. No hover-only controls. Solid sticky bars.",
  "A translucent sticky bar bleeds through and vanishes on iOS (TB LM-45). "
  "Full-text header buttons overflow the mobile topbar (LM-46). A "
  "hover-to-reveal control is unreachable on touch (LM-47).",
  TB, "CLAUDE.md LM-45, LM-46, LM-47"),
]


def upgrade():
    features = table(
        "features",
        column("slug", sa.String), column("name", sa.String),
        column("category", sa.String), column("summary", sa.Text),
        column("typical_value", sa.Float), column("gold_standard_md", sa.Text),
        column("pitfalls_md", sa.Text), column("reference_project", sa.String),
        column("reference_path", sa.String), column("status", sa.String),
        column("is_active", sa.Boolean), column("sort_order", sa.Integer),
    )
    bind = op.get_bind()
    have = {r[0] for r in bind.execute(sa.text("SELECT slug FROM features"))}
    rows = []
    for i, (slug, name, cat, summary, value, gold, traps, project, path) in \
            enumerate(CATALOGUE):
        if slug in have:
            continue
        rows.append({
            "slug": slug, "name": name, "category": cat, "summary": summary,
            "typical_value": value, "gold_standard_md": gold,
            "pitfalls_md": traps, "reference_project": project,
            "reference_path": path, "status": "built", "is_active": True,
            "sort_order": i * 10,
        })
    if rows:
        op.bulk_insert(features, rows)


def downgrade():
    slugs = ", ".join(f"'{row[0]}'" for row in CATALOGUE)
    op.execute(f"DELETE FROM features WHERE slug IN ({slugs})")
