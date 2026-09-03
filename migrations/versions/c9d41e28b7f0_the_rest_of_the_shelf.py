"""The rest of the shelf: features mined from every repo on the machine

The first seed drew on four projects. This one comes from a sweep of all of
them - the gym platform, the trainer app, the drumline tracker, the ministry
site, the signing portal, the meeting assistant, the flipping tracker, the
poker trainer, the analytics site, the anniversary game - each mined for
what it built, what it does best, and what it had to learn the hard way.

The pitfalls are the point. The gym platform's decision log, Data Dungeon's
thirty-four landmines, ChopBuilder's seven commits of iOS shell scar tissue,
Kuper Plumbing's deploy rules: every one is trapped in the repository that
paid for it. This puts them where the next build starts.

Revision ID: c9d41e28b7f0
Revises: b6e02d94c7a1
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column


revision = "c9d41e28b7f0"
down_revision = "b6e02d94c7a1"
branch_labels = None
depends_on = None


TB = "Talent Booker"
KP = "Kuper Plumbing"
CCC = "Christ Community Church"
PM = "Built By Bean (this board)"
DD = "Data Dungeon"
GE = "Gym Ecosystem"
PT = "Personal Trainer"
CB = "ChopBuilder"
WC = "Wisdom Crucible"
SD = "Signadoc"
MA = "Meeting Assistant"
BS = "Bible Study"
FL = "Flipping"
CFG = "CrossFit Games"
AN = "4th Anniversary"
VA = "Vault of Ash"

# slug, name, category, summary, value, gold standard, pitfalls, project, path
CATALOGUE = [

 # ── Getting work in ─────────────────────────────────────────
 ("csv-import-mapper", "Bring their spreadsheet in", "intake",
  "Upload the file they already keep, map its columns, see what would "
  "change, then apply - with per-row errors instead of a crash.", 900.0,
  "Four stages: upload, column mapping, dry-run diff, apply. The dry run is "
  "the feature - nobody trusts an import they cannot preview, and per-row "
  "errors let one bad line fail without taking the file with it.",
  "",
  GE, "apps/api/src/routers/imports.ts"),

 ("invite-registration", "Accounts by invitation", "intake",
  "The admin creates a person by email alone; a token link lets them set "
  "their own credentials.", 500.0,
  "Derive the username from the email with numeric-suffix collision "
  "handling, send the invite on a background thread so the request never "
  "waits on SMTP, and keep an invited-but-unclaimed flag distinct from a "
  "real account.",
  "Seed the first admin once, from an environment variable, and never "
  "reset an existing account's password on boot - this board shipped a "
  "boot that reset the admin password on every deploy. A committed literal "
  "password in a public repo is a published credential.",
  BS, "bible_study/__init__.py (_send_invite_email, claim_invite)"),

 ("instant-ballpark", "A price range on the spot", "intake",
  "The intake taxonomy carries a dollar range and an in-scope flag per "
  "leaf, so the customer hears a number before anybody calls back.", 600.0,
  "Ranges live on the taxonomy nodes the guided intake already walks. A "
  "reviewed_at stamp separates the owner's own numbers from what shipped, "
  "so the review screen shows only what they have not looked at yet.",
  "",
  KP, "models.py (ScopeSetting)"),

 # ── Scheduling ──────────────────────────────────────────────
 ("self-serve-reschedule", "They pick the new time themselves", "scheduling",
  "The customer moves their own appointment from a token link, choosing "
  "only from slots that are actually free.", 700.0,
  "One row per offer round, and the offered windows are frozen onto the "
  "row - a customer looking an hour later sees exactly what they were "
  "offered even if the day has since filled.",
  "",
  KP, "models.py (TimeProposal)"),

 ("route-optimizer", "The day's stops in driving order", "scheduling",
  "Orders a day of jobs into a sensible route with one tap.", 800.0,
  "Nearest-neighbour then 2-opt refinement - a real small-TSP solve, "
  "instant at ten stops. Presented as a suggestion the owner can override, "
  "never a dispatch order.",
  "",
  KP, "services/geo.py"),

 ("booking-enforcement", "The database refuses the double-book", "platform",
  "Two bookings cannot hold the same slot, even from two requests at "
  "once.", None,
  "A Postgres exclusion constraint on the resource and time range. An "
  "application-level check reads then writes, and two requests in flight "
  "both pass the read.",
  "",
  GE, "apps/api/src/routers/scheduling.ts"),

 # ── Records and data ────────────────────────────────────────
 ("program-builder", "Plans that freeze when published", "records",
  "Structured plans - workout programs, lesson plans, service schedules - "
  "built in a draft, versioned on publish, assigned to people.", 1500.0,
  "Versions freeze on publish and every assignment pins one, so an edit "
  "never shifts the ground under somebody mid-week. Templates apply as "
  "frozen deep copies: editing the client's plan never touches the "
  "library copy.",
  "Editing an assigned plan in place is the landmine - see "
  "smart-substitutions for the sore-shoulder version of it.",
  GE, "apps/api/src/routers/programs.ts; also Personal Trainer models.py "
      "(PlanTemplate)"),

 ("smart-substitutions", "Something else instead, today only", "records",
  "When the planned thing cannot happen - equipment taken, person "
  "injured - the system suggests a ranked alternative.", 900.0,
  "Adjustments are scoped to the session: suggested, applied to today, "
  "recorded as an operation. One ranked query serves every surface that "
  "asks the question. The plan itself stays immutable.",
  "The Personal Trainer version wrote the substitute onto the shared plan "
  "row, so one sore shoulder permanently rewrote the program for every "
  "future week and everyone else assigned to it. The gym platform's D-019 "
  "is the fix worth copying.",
  GE, "apps/api/src/services/adjust.ts, substitution.ts"),

 ("asset-registry", "Every unit of the thing they own", "records",
  "Equipment split into the model and the physical units, each unit with "
  "a QR tag, a status, and a maintenance queue.", 1200.0,
  "Model and unit are two tables - a quantity column cannot say which leg "
  "press is broken. Printable QR sheets make the tags real.",
  "",
  GE, "apps/api/src/routers/equipment.ts"),

 ("progress-prs", "Progress they can see", "records",
  "Logging against what was prescribed, with records detected and "
  "celebrated when they fall.", 700.0,
  "Detect the record server-side when the session completes, from the "
  "stored history - never trust the client to announce it.",
  "",
  GE, "apps/api/src/services/logging.ts; also Personal Trainer app.py"),

 ("kpi-dashboard", "The owner's numbers", "records",
  "Revenue, engagement, utilisation and the rest, on one screen the owner "
  "actually opens.", 900.0,
  "Live queries until scale forces rollups. Every tile the same shape - "
  "one figure, one label, one line of context.",
  "",
  GE, "apps/api/src/routers/bi.ts"),

 ("full-text-search", "Search that finds the sentence", "records",
  "One box across everything the system holds, down to the timestamped "
  "line inside a transcript or document.", 600.0,
  "SQLite FTS5 or Postgres full-text where available, with a LIKE "
  "fallback picked at request time so the same code runs on either. Keep "
  "segments timestamped - never flatten transcripts to a blob.",
  "",
  WC, "services/search.py"),

 ("data-pipeline", "Data pulled in without being trusted", "records",
  "Scraping or syncing an external source into something the business "
  "relies on.", None,
  "Assert the joins before making them - counts that must match, ids that "
  "must be unique - and abort loudly rather than continue with a corrupt "
  "join. Manual corrections live in an override file that carries its "
  "evidence, with a detector that flags new suspects automatically.",
  "The CrossFit pipeline ingested placeholder rows as real results and "
  "fabricated a posthumous season. Scraped text lies: non-breaking spaces "
  "hide matches until traced by character code, narration names things "
  "that are not there, and match order matters - specific before generic.",
  CFG, "scripts/fetch-games.mjs, data/athlete-aliases.json"),

 # ── Money ───────────────────────────────────────────────────
 ("pay-by-link", "Paid from the document itself", "money",
  "The customer pays an invoice by card from the same token link they "
  "read it on.", 800.0,
  "Record money only on the webhook, never on the browser's return "
  "redirect - the customer who closed the tab still paid. The handler is "
  "idempotent because the provider retries until it gets a 2xx.",
  "A webhook posted by Stripe or Twilio is not a browser: app-wide "
  "CSRFProtect answers it 400 before the view runs, the test suite has "
  "CSRF off so every test passes, and it fails only in production. Exempt "
  "the view and authenticate by signature instead.",
  KP, "services/payments.py"),

 ("credits-ledger", "Balances that are sums", "money",
  "Session packs, credits, anything bought in bundles and spent over "
  "time.", 600.0,
  "An append-only ledger; the balance is a sum. Redemption writes a row.",
  "A sessions_remaining counter drifts under concurrent writes and loses "
  "the story - who bought what, when it was spent, why it was refunded.",
  GE, "apps/api/src/routers/money.ts"),

 ("frozen-prices", "History keeps its price", "money",
  "What was agreed stays on the record that agreed it.", None,
  "Copy the price onto the sale or booking at agreement time and read it "
  "from there forever. The catalogue price is what it costs today; the "
  "record is what that client said yes to.",
  "Joining bookings to the current rate card at read time means a raise "
  "rewrites history - and payroll, and disputes.",
  GE, "apps/api/src/routers/money.ts; also this board's ProductSale"),

 # ── Talking to people ───────────────────────────────────────
 ("queue-first-sending", "Sends that survive the request", "comms",
  "Every outbound text, email and webhook goes through a queue that "
  "retries, dedupes and gives up honestly.", None,
  "Queue first, send later: a dedupe key with a unique index, a "
  "conditional-update claim before each attempt, backoff over about a "
  "day, and skipped-with-reason instead of retrying forever. Implemented "
  "identically three times in Kuper - copy it, do not re-derive it.",
  "A send fired inline in the request dies with the request, and a retry "
  "loop without a dedupe key double-texts a customer.",
  KP, "services/notify.py, services/hub_sync.py"),

 ("signed-webhooks", "Two apps that trust each other", "platform",
  "One app raising tickets or pushing status into another, signed so "
  "nobody else can.", None,
  "HMAC over timestamp plus exact bytes, a five-minute replay window, "
  "compare_digest never ==, and one secret per client so a leak is one "
  "client's problem. The shared protocol lives in one file both apps "
  "carry byte-for-byte.",
  "A secret in the URL leaks in logs. String equality returns at the "
  "first differing byte, and how long that took is a measurement.",
  KP, "services/hub.py; the receiving half is this board's tickets"),

 ("email-that-renders", "Email that survives Outlook", "comms",
  "Branded transactional mail that renders everywhere it lands.", 400.0,
  "Table layout, every style inline, buttons as background-coloured cells "
  "wrapping a full-bleed link with the VML rectangle for Outlook. The "
  "wrapper never touches the message content.",
  "Outlook renders through Word and Gmail strips style tags on forward - "
  "a styled div button arrives as plain text.",
  KP, "services/email_theme.py"),

 ("ask-them-mid-job", "A question they can actually answer", "comms",
  "The worker asks a clarifying question from the job screen; the "
  "customer answers on a link.", 400.0,
  "The answer is a page, not an SMS reply. A reply to an outbound text "
  "lands nowhere the app can read, so asking for one is asking for "
  "silence.",
  "",
  KP, "models.py (JobQuestion)"),

 ("a2p-registration", "Texting the carriers allow", "comms",
  "Getting a business number through A2P review without the "
  "rejection-and-resubmit cycle.", None,
  "One source of truth for the consent wording - the checkbox label, the "
  "stored consent record and the carrier submission are the same string. "
  "Reviewer sample pages are built at request time so a fresh deploy "
  "always has them, and an outside-in preflight fetches every submitted "
  "link the way the reviewer will.",
  "Kuper's registration took eight commits: submitted links that 404d in "
  "production, an opt-in a reviewer could not see, a consent form with no "
  "phone field, and Cloudflare's email obfuscation rewriting the very "
  "address under review. The preflight and samples modules exist so none "
  "of that recurs.",
  KP, "services/consent.py, services/samples.py, services/preflight.py"),

 # ── Documents ───────────────────────────────────────────────
 ("esign-portal", "The signing side of e-signature", "documents",
  "Where the client actually signs: magic-link entry, a guided walk "
  "through the fields, drawn or typed signatures, sealed PDFs anyone can "
  "verify.", None,
  "The ceremony walks the first unfilled required field sorted by page "
  "and position. Draw, type and upload all crop to the inked bounding box "
  "so every signature lands the same shape. Events chain by hash; the "
  "seal embeds in the PDF three ways so a file verifies offline. The "
  "editor's save path and the machine import share one validation "
  "function, so an API envelope obeys exactly what a dragged one does.",
  "Single-use magic links burn before the human clicks - corporate mail "
  "scanners prefetch them; multi-use until expiry. Stored field "
  "coordinates are top-left fractions and PDF draws bottom-left: flip "
  "once, in one place. Verification is independent named checks, never "
  "one opaque valid flag.",
  SD, "server/src/index.js, audit.js, pdf.js"),

 ("signature-context", "What they saw when they signed", "documents",
  "A signature stored with the exact wording shown at signing time, "
  "frozen.", 500.0,
  "The drawn mark is the least important part. Freeze the disclosure "
  "text onto the signature row so later wording changes never rewrite "
  "what a past signer agreed to, and stamp it server-side.",
  "",
  KP, "services/signing.py"),

 ("tamper-evident-log", "A log nobody can quietly edit", "platform",
  "An event history that can prove it has not been rewritten.", None,
  "Each event's hash covers the previous one; verification walks the "
  "chain and names the exact broken link. Forty-nine lines, no "
  "dependencies, portable to invoices, tickets, anything defensible.",
  "",
  SD, "server/src/audit.js"),

 # ── Their own access ────────────────────────────────────────
 ("records-before-logins", "People exist before accounts", "portal",
  "The business's records come first; the person claims theirs later.", 500.0,
  "Members, customers and staff are rows with no login until invited or "
  "claimed. The claim flow attaches credentials to the existing record "
  "instead of making a second one.",
  "A signup that writes a login but no profile leaves somebody who can "
  "sign in and see nothing, and spawns duplicates on the retry.",
  GE, "apps/api/src/routers/members.ts"),

 ("two-audiences", "Two kinds of user, one front door", "portal",
  "Owner and customer, trainer and trainee - both log in, each sees "
  "their own world.", None,
  "Two account types through one session system, ids prefixed by kind. "
  "Cheaper and safer than two auth stacks.",
  "Gate on what the profile proves, not on a role string.",
  PT, "models.py (Trainer.get_id, Client.get_id), app.py (load_user)"),

 ("content-registry", "Defaults in code, edits in the database", "platform",
  "Every piece of wording and imagery the client can change, with the "
  "shipped version always underneath.", None,
  "The registry declares each key with its shipped default; the database "
  "holds only overrides; clearing a field restores the original. Three "
  "apps reinvented this independently - it is the mechanism behind every "
  "client-editable site.",
  "",
  CCC, "services/site_content.py; also Wisdom Crucible, 4th Anniversary"),

 ("sync-preserves-edits", "The re-sync that cannot eat their edits", "platform",
  "Content pulled from an external system - YouTube, a POS, a CRM - that "
  "the client also edits by hand.", None,
  "Record every admin edit in its own table, keyed by the external id, "
  "and replay them after every re-seed. Re-pointing a record at a "
  "re-uploaded source carries the edits across. That is what makes a sync "
  "non-destructive.",
  "Admin tables must never declare a foreign key onto synced tables: the "
  "re-sync wipes those tables, and the cascade empties the admin data "
  "with them. Reference by external id or slug instead.",
  WC, "services/admin_edits.py, scripts/sync_youtube.py"),

 # ── Underneath ──────────────────────────────────────────────
 ("admin-auth", "The admin login, hardened", "platform",
  "Session auth for the owner's own door, built to survive real "
  "attackers and real infrastructure.", None,
  "DB-backed login throttle keyed on both IP and email - an in-process "
  "dict only throttles the worker that served the request. A session "
  "epoch on the user row signs every other device out on password "
  "change. Absolute and idle expiry in one guard. Unknown accounts spend "
  "a dummy hash so timing cannot reveal which emails exist.",
  "Behind a CDN, remote_addr is the proxy: prefer CF-Connecting-IP, else "
  "the rightmost X-Forwarded-For hop - the leftmost is attacker-chosen. "
  "Rate-limit every auth endpoint on that real IP.",
  CCC, "services/auth.py; also Wisdom Crucible services/auth.py"),

 ("secrets-fail-closed", "No secret ever has a default", "platform",
  "Signing keys, API keys and passwords that refuse to fall back.", None,
  "Read from the environment; when unset and any production signal is "
  "present, raise at import so the deploy fails its healthcheck and the "
  "platform keeps serving the last good release. Local dev gets a "
  "clearly-local default only when nothing looks like production.",
  "A hardcoded SECRET_KEY fallback ran Data Dungeon's production for "
  "weeks - anyone reading the repo could forge any user's session "
  "cookie, silently. And never print a variable listing: DATABASE_URL "
  "carries the Postgres password inside a URL that name-based masking "
  "sails past.",
  DD, "config.py (_resolve_secret_key); also this board's config.py"),

 ("multi-tenant-rls", "Tenants the database keeps apart", "platform",
  "Many businesses in one system, isolated where it cannot be "
  "forgotten.", None,
  "Forced row-level security with a transaction-local tenant id: no "
  "context, zero rows. The isolation test iterates every tenant table "
  "from the schema itself, so a new table without coverage fails the "
  "suite. Cross-tenant probes answer 404, never 403 - a 403 confirms the "
  "thing exists.",
  "",
  GE, "packages/db/src/client.ts, apps/api/test/isolation.test.ts"),

 ("permission-matrix", "Who may do what, as data", "platform",
  "Every action in the system authorised through one table.", None,
  "One authorize(actor, action, resource) gate consulted by every "
  "route, with the matrix as plain data. The test's expectations are "
  "written independently of the matrix so they cannot mirror its bugs. "
  "Sensitive reads audit inside the same gate, not by convention.",
  "A route that loads a child by id and touches its parent has skipped "
  "the guard. Every mutation resolved by a user-supplied id verifies "
  "ownership before the write - the sibling GET having a guard does not "
  "protect the POST.",
  GE, "packages/authz/src/matrix.ts"),

 ("offline-sync", "Works in the basement, reconciles later", "platform",
  "An app that keeps working with no signal and merges safely when it "
  "returns.", None,
  "An append-only op log with one fold function shared by client and "
  "server; writes durable locally before the UI confirms; pushes "
  "idempotent; deletes as tombstones; the pull watermark is server time. "
  "When the dataset is small, pull it all - the incremental watermark is "
  "the one piece of state that goes wrong invisibly.",
  "ChopBuilder kept its watermark in localStorage next to an IndexedDB "
  "database: iOS evicted one and not the other, and a surviving synced-up-"
  "to marker over an emptied store hid the roster while the server held "
  "everything. Flipping's stale clients pushed empty sub-lists that wiped "
  "other devices' entries until the server merged lists by union. "
  "Fifteen-second abort on every sync request - parking-lot networks "
  "hang more often than they fail.",
  CB, "src/sync/sync.ts, server.py; also Flipping server.py, "
      "Gym Ecosystem packages/sync"),

 ("installable-pwa", "An app icon without an app store", "ui",
  "The site installs to the home screen and behaves like an app - "
  "offline shell, splash, safe areas, keyboard handling.", None,
  "ChopBuilder's shell is the battle-tested copy: document never "
  "scrolls and it is overflow clip, not hidden; shell height measured "
  "from visualViewport, never dvh; overlays anchor absolute to the "
  "shell, never fixed; a splash curtain paints before any CSS arrives; "
  "keyboard docking reserves space from a remembered per-device height.",
  "Seven commits of iOS scar tissue in ChopBuilder and six more in "
  "Flipping: env() safe-area values freeze at zero on stale installs, a "
  "padding shorthand silently resets the inset, a broken icon gets "
  "pinned by the service worker until the filename changes. Price "
  "installable-PWA polish generously or scope it out loudly.",
  CB, "index.html (inline shell script), src/styles/global.css"),

 ("railway-deploys", "Deploys that actually deployed", "platform",
  "Getting a build live on Railway, and knowing it is live.", None,
  "The checklist: gunicorn and the Postgres driver in requirements, bind "
  "PORT, writable paths only under the volume, the start command in "
  "exactly one place, and the builder pinned the moment Node files join "
  "a Python root - Nixpacks guesses, and guesses Node. Verify against "
  "the public URL with a cache-buster, never the container.",
  "A pushed commit is not a deployed commit: status reads Online all "
  "through a deploy, logs default to the last successful deployment, and "
  "a failed deploy keeps serving the old commit while looking identical "
  "to a slow one. Three separate apps each spent three or more commits "
  "relearning this.",
  KP, "CLAUDE.md (Deploys); also Data Dungeon LM-30, Wisdom Crucible"),

 ("route-integrity", "No dead buttons", "platform",
  "Every link and every fetch call lands on a route that exists.", None,
  "Three cheap gates run before every commit: a smoke test that walks "
  "every route against a throwaway database, a static check that every "
  "template url_for resolves - including branches happy-path testing "
  "never enters - and one that resolves every JS fetch path against the "
  "live url_map.",
  "A renamed API prefix left fifty-four fetch calls pointing at nothing: "
  "every page loaded fine and every button 404d one click deep, "
  "invisible to url_for checks because the paths live in JavaScript.",
  WC, "smoke_test.py, scripts/check_url_for_endpoints.py; also "
      "Data Dungeon scripts/check_js_fetch_endpoints.py"),

 ("landmine-scanners", "Bugs that cannot come back", "platform",
  "Every hard-won lesson becomes a written landmine and a static check "
  "that fails the commit that repeats it.", None,
  "The landmine doc records what happened, why it was easy, the rule, "
  "and a grep that finds regressions; a scanner wired into the "
  "pre-commit hook enforces it mechanically. Data Dungeon runs about a "
  "hundred of these, each anchored to a real shipped bug.",
  "",
  DD, "services/graph_violations.py, docs/landmines/"),

 ("fuzzy-matching", "Close enough, decided carefully", "platform",
  "Grading free-text answers, linking near-duplicate records, matching "
  "voices - anywhere similar has to become same or different.", None,
  "Layer cheap signals and bias toward the recoverable mistake: a wrong "
  "miss is one tap to fix in view, a wrong match quietly corrupts. Reach "
  "for an LLM only on the genuinely ambiguous remainder.",
  "When precision is flat across the threshold range, raising the bar "
  "buys nothing - find different evidence instead: the margin over the "
  "runner-up, or a streak of consistent wins, as the Meeting Assistant's "
  "speaker linking does.",
  AN, "src/matching.js; also Meeting Assistant ml/speaker_db.py"),

 ("per-seat-redaction", "Nobody sees the other side's hand", "platform",
  "Shared state where each participant may only see their share.", None,
  "Redact per seat on the server before anything ships to a client - "
  "while a question is open the only thing you learn about the other "
  "seat is whether they have locked in. The referee runs once, "
  "server-side, so both screens agree.",
  "",
  AN, "rooms.js (viewForSeat)"),

 ("corporate-tls", "HTTPS under a corporate proxy", "platform",
  "The app keeps working on networks that re-sign TLS.", None,
  "Verify against the operating system's trust store - fifteen lines "
  "with truststore - instead of certifi's bundle, which has never heard "
  "of the corporate root.",
  "The Meeting Assistant spent nine commits toggling a VPN around every "
  "call and disabling verification before landing there. Never ship "
  "verify=False.",
  MA, "core/config.py"),

 ("wrap-frozen-apps", "New chrome on an app you must not touch", "platform",
  "A vendored or contractually frozen deliverable wearing the client's "
  "current branding.", None,
  "Inject the nav and theming at serve time by string replacement before "
  "the closing tags, keeping the wrapped app byte-for-byte unmodified on "
  "disk - replacing it with a future release then costs nothing.",
  "",
  VA, "server.js (withSiteNav)"),

 ("audio-timing", "Clicks that cannot drift", "platform",
  "Metronomes, interval timers, anything the ear will audit.", None,
  "Two clocks: a coarse interval wakes up and schedules every beat ahead "
  "of time on the audio hardware clock, which is sample-accurate under "
  "any main-thread stutter.",
  "Scheduling clicks from setInterval itself drifts audibly within "
  "seconds.",
  CB, "src/audio/metronome.ts"),

 # ── Interface patterns ──────────────────────────────────────
 ("guided-tours", "The product shows you around", "ui",
  "First-run walkthroughs that spotlight real elements, step by step.", 600.0,
  "Target stable ids, never positional guesses, and check each step's "
  "prerequisites before navigating. Below desktop width the popover "
  "docks as a bottom sheet - full width, pixel-capped height, "
  "internally scrollable, sticky footer - with the target scrolled into "
  "the gap above it by a measured delta.",
  "Placing the popover beside the target on a phone parks it on top of "
  "the thing it describes - there is no room beside a full-width card. "
  "And scrollIntoView inside a scroll-reactive engine oscillates "
  "forever; scroll by delta, which settles.",
  TB, "templates/components/tour.html (LM-51); also Data Dungeon "
      "static/js/tutorial.js (LM-14)"),

 ("phone-filter-bars", "Filters that fit a phone", "ui",
  "The search-plus-dropdowns bar, without the mobile squash.", None,
  "Keep the search full-width and always visible; collapse the dropdowns "
  "behind a Filters button carrying a server-computed active count; "
  "expand them stacked and full-width. Desktop survives byte-for-byte "
  "via lg:contents wrappers that dissolve at width.",
  "flex flex-wrap never overflows, so it passes every fit check while "
  "rendering the search one letter wide - a quality failure no geometry "
  "test sees. And every responsive grid needs a base grid-cols-1: "
  "without it the implicit auto column grows to its widest child and "
  "scrolls the whole page sideways (TB LM-54, LM-55).",
  TB, "templates/talent/list.html"),

 # ── From the Talent Booker sweep ────────────────────────────
 ("broadcast-engine", "One message to everyone who fits", "comms",
  "Blast an opportunity to every matching, available person - paced, "
  "resumable, and impossible to double-send.", 900.0,
  "Async and paced so carriers tolerate it, resumable after a restart, "
  "and idempotent by a unique constraint rather than by memory - the "
  "database is the only send-once guard that survives a crash.",
  "Measure the rendered message, never the template, when counting "
  "segments - and fold non-GSM-7 characters mechanically, or one accent "
  "silently doubles the cost of every text.",
  TB, "models.py (CastingBroadcast); the GSM-7 fold is app.py _gsm7_safe"),

 ("asset-checkout", "Things that leave and come back", "records",
  "Costumes, tools, equipment - tracked out the door, through the job, "
  "and home again, with overdue nudges.", 800.0,
  "Two stamps per stage - when, and who - never one enum. The current "
  "stage is derived backward from the furthest stamp, not stored, so it "
  "cannot drift from the facts.",
  "",
  TB, "models.py (Booking costume columns), templates/admin/costumes.html"),

 ("payroll-tracking", "Who has been paid, and how", "money",
  "Per-job payout records: check or app, issued when, issued by whom.", 500.0,
  "Nullable with no default and no backfill guess - an unrecorded payment "
  "must look unrecorded, not paid.",
  "Never invent a value a human should supply; a blank is what lets the "
  "completeness check catch it.",
  TB, "models.py (Booking check columns), /admin/checks"),

 ("editable-templates", "Their wording, without a deploy", "comms",
  "Every automated message body editable from the admin.", 400.0,
  "Templates in the database with the variables documented beside the "
  "box. The same registry idea as editable page copy, pointed at "
  "messages.",
  "",
  TB, "models.py (SmsTemplate), /admin/sms-templates"),

 ("sms-roi", "What the texting is actually worth", "money",
  "Turns a texting bill into a defensible savings number the client can "
  "repeat.", 600.0,
  "Anti-flattery by construction: a reach cap, a counts-as-saving flag "
  "per message type, suggested-versus-confirmed assumptions, and a "
  "replacement factor below one. A dashboard that claims dollars saved "
  "earns trust by underclaiming.",
  "An unscoped version of the sibling profit dashboard once reported a "
  "99.6% margin - scope analytics to the records that carry real costs.",
  TB, "models.py (SmsAssumption), /admin/sms-analytics"),

 ("capability-flags", "Permissions that name the action", "platform",
  "Who may do what, as individual grants instead of a role ladder.", None,
  "Capability flags on the account - can_manage_money, can_edit_roster - "
  "checked by a decorator that asks the capability, never the role "
  "string. Fail closed, with an orphan-admin guard so the owner cannot "
  "lock themselves out.",
  "Role-string checks admit the wrong people twice over: staff_required "
  "lets agents into admin surfaces, and role == talent misses the "
  "profile that actually proves it.",
  TB, "models.py (User capability properties)"),

 ("ask-off-workflow", "Asking off a job, on the record", "scheduling",
  "Somebody already assigned asks to be released; the office approves or "
  "declines, with reasons that feed reliability history.", 500.0,
  "Its own table, not a fourth status on the assignment - the request "
  "outlives the booking it releases. Categorised reasons split what the "
  "record needs from what the person is told.",
  "",
  TB, "models.py (RemovalRequest, RemovalReason)"),

 ("calendar-feeds", "Their calendar, subscribed", "scheduling",
  "A personal feed that puts their schedule in the calendar app they "
  "already use.", 400.0,
  "A token-addressed ICS feed per person, plus a public events feed. No "
  "login on the feed URL - the token is the credential, so it must be "
  "revocable.",
  "",
  TB, "/calendar/feed/<token>.ics"),

 ("bulk-invites", "Six hundred people, invited safely", "intake",
  "A pasted roster becomes previewed, deduped, staggered invitations.", 700.0,
  "Preview and dedupe before anything sends; pace the sends; make the "
  "pipeline resumable. The rollout runbook is part of the feature: "
  "SPF, DKIM and DMARC verified before the first message, a go/no-go, "
  "and a rollback.",
  "",
  TB, "/admin/users/bulk-invite, docs/ROLLOUT.md"),

 ("day-of-brief", "The morning-of text", "comms",
  "Whoever is running the day gets one logistics message, once.", 300.0,
  "A unique constraint on event, person and date is the send-once "
  "guard - not a flag somebody clears, not a memory of having sent.",
  "",
  TB, "models.py (EventDayOfNotice)"),

 ("page-anatomy", "Pages that are stacks of sections", "ui",
  "The shape every screen shares, so nothing has to be designed "
  "twice.", None,
  "A page is a stack of sections: title left, at most one action right, "
  "content under it. Discrete operable things get cards; interchangeable "
  "rows stay flat. Empty states are plain grey text under the title. A "
  "fixed spacing ladder - an inline arbitrary margin is a drift bug.",
  "",
  DD, "docs/conventions/ui_patterns.md"),

 ("no-flash-dark", "Dark that never flashes white", "ui",
  "Dark-mode apps that stay dark between pages and on cold starts.", None,
  "Paint the background inline on the html tag itself - a style block in "
  "head is already too late between navigations. Resolve theme "
  "preferences in a pre-paint script so the first frame is right.",
  "The Wisdom Crucible's owner is photophobic: the white flash is a "
  "shipped bug, not a nitpick. Data Dungeon fixed it four times across "
  "web and the native wrapper before pinning the rule.",
  WC, "CLAUDE.md (UI rules); also Data Dungeon, Bible Study"),
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
            "sort_order": 400 + i * 10,
        })
    if rows:
        op.bulk_insert(features, rows)


def downgrade():
    slugs = ", ".join(f"'{row[0]}'" for row in CATALOGUE)
    op.execute(f"DELETE FROM features WHERE slug IN ({slugs})")
