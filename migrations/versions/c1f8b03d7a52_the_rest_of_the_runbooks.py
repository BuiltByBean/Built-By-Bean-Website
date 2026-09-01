"""the rest of the runbooks, and real logos on the four that had none

Closes the gap: Postgres, Sentry, OpenStreetMap, the YouTube Data API, the ESV
API, the LLM APIs and the App Store. Seventeen playbooks now, which is every
third party any of these apps actually talks to.

Two of these correct something believed rather than checked. Kuper's geocoding
is not Google Maps — it is Nominatim, one request a second with a User-Agent,
and `GOOGLE_MAPS_API_KEY` is a dead credential sitting in production that
nothing reads. And `RC_PUBLIC_KEY` in Data Dungeon is RevenueCat, which means
that app ships in-app purchases.

Also backfills logos onto AWS, Gmail and Squarespace, which shipped as
initials in the previous wave. Every mark is simple-icons' published path
data, fetched rather than drawn. Tripleseat and the ESV API have no published
mark and keep their initials rather than get a guess.

Revision ID: c1f8b03d7a52
Revises: b7d4f6a29e01
Create Date: 2026-09-01 16:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c1f8b03d7a52'
down_revision = 'b7d4f6a29e01'
branch_labels = None
depends_on = None


# Marks that arrived after their playbook did.
BACKFILL_LOGOS = {
    "aws": "pm/logos/aws.svg",
    "gmail-smtp": "pm/logos/gmail.svg",
    "squarespace": "pm/logos/squarespace.svg",
}


POSTGRES = {
    "slug": "postgres",
    "display_name": "PostgreSQL",
    "logo_path": "pm/logos/postgresql.svg",
    "vendor_url": "https://www.postgresql.org/docs/",
    "is_active": True, "is_default": False, "sort_order": 42,
    "one_liner": (
        "Every app here runs on one. Nobody has written down what happens when "
        "one is lost."
    ),
    "client_only_md": """\
**Nothing, and that is the point.** The database is part of the hosting they
are already paying for, and it is not a decision they should be asked to make.

The one thing that is theirs: **their data is theirs**, and they are entitled
to a copy of it on request in a format they could actually use. Say that
before they ask, not after.

**If it is their Railway account rather than yours**, the database lives on
their bill and their plan determines whether backups exist at all. Find out
which plan before promising anything about recovery.
""",
    "access_grant_md": """\
**One connection string, injected by the host.**

    DATABASE_URL          postgresql://user:pass@postgres.railway.internal:5432/railway
    DATABASE_PUBLIC_URL   the same database over the open internet

Railway sets both. **Use the internal one.** It never leaves Railway's network,
it is faster, and it is not exposed to anybody who guesses a hostname.

**`postgres://` is not `postgresql://`.** SQLAlchemy stopped accepting the
short scheme, and some hosts still hand it out. If the app dies at startup with
a dialect error, this is it. Normalise the scheme on read rather than depending
on what the host chose to write.

**`railway connect` opens psql against the linked service** without you ever
handling the password, which is the right way to look at production data.
""",
    "your_steps_md": """\
**Run migrations before the server starts, not by hand.** Kuper's
`railway.json` does this with a `preDeployCommand` of `flask db upgrade`, so a
deploy cannot serve a schema it has not migrated. A deploy that boots against
the wrong schema fails in a way that looks like application code.

**Round-trip every migration before pushing.** `upgrade`, `downgrade`,
`upgrade`. A downgrade that half-works leaves a state neither version expects,
and the only time you find out is the one time you need it.

**Count your connections.** Gunicorn workers multiplied by threads is the
number of connections the app can hold open. Managed Postgres plans cap that
lower than people expect, and exhaustion shows up as intermittent timeouts
rather than as a connection error.

**Know where the backups are before you need them.** Not "assume the host does
it". See the traps — this is the one that ends a business.
""",
    "traps_md": """\
**A Railway Postgres can be exposed to the open internet, and one here is.**
J&D's database has `RAILWAY_TCP_PROXY_DOMAIN` = `interchange.proxy.rlwy.net`
and a `DATABASE_PUBLIC_URL`, which means it is reachable from anywhere with
nothing but the password in front of it. That public proxy exists so you can
connect a GUI once, and it then stays on forever because nobody remembers it
is there. **Turn it off when you are done with it**, and use `railway connect`
instead.

**Backups are a plan feature, not a law of nature.** Check what your plan
actually retains and how far back. An app with a volume and a database has two
different things to lose and they are backed up by different mechanisms, if at
all.

**A backup you have never restored is not a backup.** Restore one into a scratch
database and open the app against it. The first restore attempt should not be
during the incident.

**`postgres://` versus `postgresql://` kills the app at boot** and the error
names a dialect, not a URL.

**Deleting a project takes the database with it.** Railway will ask once. That
is the only warning there is.

**The ORM's delete and the database's `ON DELETE CASCADE` are different
things.** A relationship without `passive_deletes` makes SQLAlchemy try to null
a child's foreign key first, which a NOT NULL column refuses — so the delete
raises instead of cascading. This is live in this codebase: deleting a project
that has time entries fails exactly this way.
""",
    "verify_md": """\
**Is the public proxy on?**

    railway variables -s <db-service> --json | grep -i proxy

`RAILWAY_TCP_PROXY_DOMAIN` present means the database is on the internet.

**Does a restore actually work?** Take a backup, restore it somewhere scratch,
point a local app at it and log in. Anything less is a file you hope is a
backup.

**Did the migration actually run on this deploy?** Read `alembic_version` from
the running database, not from your machine:

    railway connect
    select * from alembic_version;

**How many connections is the app holding?**

    select count(*) from pg_stat_activity where datname = current_database();

Compare it against workers x threads and against the plan's cap.
""",
    "steps": [
        ("Use the internal connection string, never the public one",
         "`postgres.railway.internal` never leaves Railway's network. "
         "`DATABASE_PUBLIC_URL` crosses the internet and is protected by a "
         "password alone.", None, "", ""),
        ("Normalise the URL scheme on read",
         "SQLAlchemy rejects `postgres://`. Some hosts still hand it out. The "
         "failure is a dialect error at boot that names everything except the "
         "URL.", None, "", ""),
        ("Run migrations before the server starts",
         "A `preDeployCommand` of `flask db upgrade`, as in Kuper's "
         "`railway.json`, so a deploy cannot serve a schema it has not "
         "migrated.", None, "", ""),
        ("Round-trip every migration before pushing it",
         "upgrade, downgrade, upgrade. A downgrade that half-works leaves a "
         "state neither version expects, and you find out on the one day you "
         "need it.", None, "", ""),
        ("Turn the public TCP proxy off once you are done with it",
         "It exists so a GUI can connect once, and then stays on forever. J&D's "
         "database is on the open internet right now for exactly this reason. "
         "Use `railway connect` instead.", None, "", ""),
        ("Find out what the plan actually backs up, and how far back",
         "Not \"assume the host does it\". An app with a volume and a database "
         "has two different things to lose, backed up by different mechanisms "
         "if at all.", None, "", ""),
        ("Restore a backup into a scratch database and open the app against it",
         "A backup you have never restored is a file you hope is a backup. The "
         "first attempt should not be during the incident.",
         None, "", ""),
        ("Count workers x threads against the connection cap",
         "Exhaustion shows up as intermittent timeouts rather than as a "
         "connection error, which sends you debugging the wrong layer.",
         None, "", ""),
        ("Tell the client their data is theirs, before they ask",
         "They are entitled to a copy in a format they could use. Saying it "
         "first costs nothing and answers the question underneath most exit "
         "conversations.", "email", "Your data on {project}",
         "Hi {client},\n\nOne thing worth putting in writing now rather than "
         "later: everything in {project} — your customers, jobs, invoices and "
         "history — is yours, not mine.\n\nIf you ever want a copy, ask and I "
         "will send you the lot in a spreadsheet-readable format within a "
         "couple of weeks, no questions and no charge. That holds whether we "
         "are still working together or not.\n\nThanks,\nMichael\n"
         "Built by Bean LLC"),
    ],
}


SENTRY = {
    "slug": "sentry",
    "display_name": "Sentry",
    "logo_path": "pm/logos/sentry.svg",
    "vendor_url": "https://sentry.io",
    "is_active": True, "is_default": False, "sort_order": 70,
    "one_liner": (
        "Finds out an app is broken before the client rings. The risk is what "
        "it carries out of the app with the error."
    ),
    "client_only_md": """\
**Whose Sentry account.** Free tier is generous enough for every app here, and
if it is yours the errors from their app land in your account — which is what
you want operationally and worth them knowing.

**That errors leave their server.** A crash report contains a stack trace and,
unless scrubbed, whatever was in scope when it happened. For an app holding
customer records that is a sentence worth saying out loud once.

Nothing else. This is your tool, not theirs.
""",
    "access_grant_md": """\
**A DSN, which is not a secret in the way the others are.**

    SENTRY_DSN            identifies the project, safe in client-side code
    SENTRY_ENVIRONMENT    production / staging, so the two do not merge
    SENTRY_AUTH_TOKEN     reads issues back out — this one IS a secret
    SENTRY_ORG_SLUG
    SENTRY_PROJECT_SLUG

The DSN can only write events. The auth token can read every issue in the
organisation, so it is scoped and stored like any other key.

**Ship it dark.** Data Dungeon's whole Sentry block is a no-op when
`SENTRY_DSN` is unset, so local development and any environment you have not
configured send nothing at all. That is the right default: reporting is opt-in
per environment rather than something to remember to switch off.
""",
    "your_steps_md": """\
**Scrub before send, not after.** Data Dungeon filters keys whose names look
sensitive out of the event before it leaves the process. Do this in
`before_send`, because anything that reaches Sentry has already left your
control and deleting it later is a request to a vendor.

**Set the environment.** Without it, staging noise and production incidents
land in the same stream and the stream stops being read.

**Tag releases.** An error you cannot tie to a deploy is an error you cannot
tie to a change.

**Read the issues back into the admin if it helps.** Data Dungeon exposes an
Errors surface at `/admin` via `services/sentry_api.py` using the auth token,
which puts the last errors where you already are rather than behind another
login.
""",
    "traps_md": """\
**PII walks out inside the stack trace.** Local variables at the point of the
crash routinely include an email, a phone number or a token, and Sentry will
happily store all of it. This is the entire risk of the tool and it is silent.

**One noisy error will eat the whole quota in an afternoon.** A crash in a loop
sends an event per iteration. The free tier then drops everything else,
including the incident you would have cared about.

**Errors from local development pollute production** the moment somebody sets
the DSN in a `.env` and forgets. Ship dark and set it per environment.

**A resolved issue reopens on the next occurrence**, which is correct and
surprising. An issue you resolved without fixing comes back looking new.

**Sentry going down does not take the app down** — the SDK fails quietly — but
it also means silence is not proof that nothing broke.
""",
    "verify_md": """\
**Does an event actually arrive?** Raise a deliberate exception on a throwaway
route and watch it land. Reading configuration is not evidence.

**Does the scrubbing work?** Raise one deliberately holding a fake token in a
local variable, then read the event in Sentry and confirm the value is gone.
This is the only check that matters and it is the one nobody runs.

**Is the environment tag set on the event you just sent?** Look at the event,
not the config.

**Is the auth token scoped to one project?** Try reading a different project
with it. It should be refused.
""",
    "steps": [
        ("Ship it dark — no DSN, no reporting",
         "The whole block should be a no-op when `SENTRY_DSN` is unset, so "
         "local development and unconfigured environments send nothing. "
         "Opt-in per environment beats remembering to switch it off.",
         None, "", ""),
        ("Scrub sensitive values in before_send",
         "Local variables at the crash point routinely hold an email, a phone "
         "number or a token. Anything that reaches Sentry has left your "
         "control; deleting it afterwards is a support request.",
         None, "", ""),
        ("Set SENTRY_ENVIRONMENT on every deploy",
         "Without it, staging noise and production incidents share one stream "
         "and the stream stops being read.", None, "", ""),
        ("Raise a deliberate error and watch it arrive",
         "Reading the config is not evidence. One throwaway route, one "
         "exception, one event in the dashboard.", None, "", ""),
        ("Raise one holding a fake token and confirm it was stripped",
         "The only check that proves the scrubbing works, and the one nobody "
         "runs.", None, "", ""),
        ("Tag releases so an error ties to a deploy",
         "An error you cannot attach to a change is an error you investigate "
         "from scratch.", None, "", ""),
        ("Put a cap or a filter on anything that can loop",
         "One error inside a loop sends an event per iteration and eats the "
         "free tier in an afternoon, dropping the incident you cared about.",
         None, "", ""),
        ("Decide whether the errors belong in the admin too",
         "Data Dungeon reads issues back with `SENTRY_AUTH_TOKEN` and shows "
         "them at `/admin`, which puts them where you already are rather than "
         "behind another login.", None, "", ""),
    ],
}


NOMINATIM = {
    "slug": "openstreetmap",
    "display_name": "OpenStreetMap",
    "logo_path": "pm/logos/openstreetmap.svg",
    "vendor_url": "https://operations.osmfoundation.org/policies/nominatim/",
    "is_active": True, "is_default": False, "sort_order": 75,
    "one_liner": (
        "Free geocoding with a usage policy instead of a bill. Break the policy "
        "and you are blocked, not invoiced."
    ),
    "client_only_md": """\
**Nothing, and that is why it was chosen.** No account, no key, no card. This
is the reason to reach for it over Google for the volumes these apps do.

The one thing to be honest about: **it is a volunteer-run service with no
SLA.** If it is down, addresses do not resolve. The app must carry on without
coordinates rather than fall over, and the client should know a map pin is a
convenience rather than a guarantee.
""",
    "access_grant_md": """\
**None. There is no key.** That is not an oversight in the setup, it is the
service.

What it wants instead is a **User-Agent that identifies your application** on
every request. Kuper passes one built from the business name. A generic or
absent User-Agent is the fastest way to get an IP blocked, and the block is not
announced.

**Google Maps needs no key either, for what it is used for here.** Kuper builds
`https://www.google.com/maps/dir/?...` deep links, which are plain URLs. There
is no Maps API call anywhere in that codebase — see the traps.
""",
    "your_steps_md": """\
**One request per second, maximum, and never during a page render.** Kuper's
`geocode_all` sleeps a full second between addresses. Geocoding on request
render means the policy is broken by traffic rather than by you.

**Look an address up once, then store the result on the record.** Kuper writes
the coordinates to the property and never looks the same address up twice. This
is what turns a policy problem into a non-problem.

**Make it explicit rather than automatic.** Lookups happen when somebody asks
for them, not on a timer and not on save.

**Separate "cannot geocode right now" from "this address has no match".** Kuper
raises `GeocodeUnavailable` for the first and returns `None` for the second.
Collapsing them means a service outage looks like a bad address forever after.
""",
    "traps_md": """\
**There is a dead Google Maps key in production right now.** Kuper's Railway
service carries `GOOGLE_MAPS_API_KEY`, and nothing in that codebase reads it —
not the geocoder, which is Nominatim, and not the directions links, which need
no key. It is an unused credential sitting in production, which is the kind of
thing that is fine until it is in a leak. **Delete it or start using it.**

**Bulk geocoding is against the policy and gets you blocked.** Not
rate-limited, blocked. A one-off import of an address list is exactly the shape
of use that triggers it.

**The block is by IP and you share one.** On a managed host, being blocked may
have nothing to do with your traffic.

**No User-Agent, or a generic one, is treated as abuse.** The requirement reads
like a formality and is enforced.

**Results are best-effort and rural addresses miss often.** A plumber's
customer on a county road may simply not resolve. Design for a missing pin, not
for a failed operation.
""",
    "verify_md": """\
**Is the User-Agent actually being sent, and does it identify the app?**
Log one outbound request and read the headers.

**Is anything geocoding during a page render?** Search for the call and check
every caller. This is the failure that scales into a block.

**Is a repeat address hitting the network again?** Look one up twice and watch
whether a second request goes out. It should not.

**Does the app still work with geocoding switched off?** Turn it off and load
the screens that show a map. A missing coordinate should be a missing pin, not
an error page.

**Is that Google Maps key still there?**

    railway variables -s <service> --json | grep -i google

If nothing reads it, it should not exist.
""",
    "steps": [
        ("Send a User-Agent that names the application",
         "Not optional and not a formality. A generic or absent one gets the "
         "IP blocked, and the block is not announced.", None, "", ""),
        ("Never geocode during a page render",
         "Lookups on render mean the rate policy is broken by traffic rather "
         "than by you, and you cannot slow traffic down.", None, "", ""),
        ("Sleep a full second between lookups in any batch",
         "One request per second is the policy. Kuper's `geocode_all` does "
         "exactly this.", None, "", ""),
        ("Store the result on the record and never look it up twice",
         "This is what turns a rate policy into a non-issue.", None, "", ""),
        ("Separate 'service unavailable' from 'no match'",
         "Kuper raises `GeocodeUnavailable` for one and returns `None` for the "
         "other. Collapsing them makes an outage look like a permanently bad "
         "address.", None, "", ""),
        ("Make sure the app works with no coordinates at all",
         "It is a volunteer service with no SLA. A missing pin is acceptable; "
         "an error page is not.", None, "", ""),
        ("Delete GOOGLE_MAPS_API_KEY from Kuper, or start using it",
         "It is in production and nothing reads it. The geocoder is Nominatim "
         "and the directions links are plain URLs that need no key. An unused "
         "credential is fine until it is in a leak.", None, "", ""),
    ],
}


YOUTUBE = {
    "slug": "youtube-api",
    "display_name": "YouTube Data API",
    "logo_path": "pm/logos/youtube.svg",
    "vendor_url": "https://console.cloud.google.com/apis/library/youtube.googleapis.com",
    "is_active": True, "is_default": False, "sort_order": 80,
    "one_liner": (
        "Pulling a channel's videos onto their own site. The quota is spent in "
        "units, and search costs a hundred of them."
    ),
    "client_only_md": """\
**Which channel, by handle and by id.** A handle can be changed; the channel id
cannot. Store the id, display the handle. The Wisdom Crucible is
`@TheWisdomCrucible`, and the id is what the code should hold.

**Whether videos are public.** Unlisted and private videos do not come back
from the API, and a client who uploads as unlisted and expects the site to show
it will report that as a bug in your code.

**Nothing else** — reading public videos needs no permission from them. If you
ever need to *upload* or read private data, that is OAuth against their Google
account and a different conversation.
""",
    "access_grant_md": """\
**An API key from a Google Cloud project, not an OAuth client.**
`console.cloud.google.com`, enable the YouTube Data API v3, then create an API
key.

    YOUTUBE_API_KEY

**Restrict it.** An unrestricted Google API key is a key anybody who finds it
can spend your quota with. Restrict by API (YouTube Data v3 only) and, for a
server-side key, by IP if the host has a stable one.

**It is a read key for public data.** It cannot upload, cannot see private
videos and cannot touch the client's account, which is what makes it the right
choice here.
""",
    "your_steps_md": """\
**Use playlists, not search.** A channel's uploads are a playlist, and
`playlistItems.list` costs **1 unit**. `search.list` costs **100**. Same
result, a hundredth of the quota. This single choice is the difference between
comfortably free and running out by lunchtime.

**Store the video id, not the embed URL.** Jakob's Crucible keeps
`youtube_id` unique and indexed and builds URLs from it. An embed URL in a
database row is a rendering decision written permanently into data.

**Cache, and refresh on a schedule rather than on a page load.** A channel's
videos change a few times a week. Fetching per visitor spends quota on traffic.

**Embed via `youtube-nocookie.com`** and allow it explicitly in the
Content-Security-Policy. Jakob's Crucible has `frame-src
https://www.youtube-nocookie.com` for exactly this — the embed silently fails
to render if the CSP does not name it.
""",
    "traps_md": """\
**The quota is 10,000 units a day and `search.list` costs 100 of them.**
That is a hundred searches. `playlistItems.list` costs 1, so the same job done
the other way is ten thousand calls. People discover this by running out.

**Quota resets on Pacific time**, not yours and not UTC. An exhausted quota
comes back at an hour that will not match when you expect it.

**A deleted or privated video keeps its row and stops rendering.** Handle a
missing video as normal rather than as an error; the client will delete things.

**An unrestricted API key is a spendable credential.** Somebody who finds it in
a public repo cannot read anything private, but they can exhaust your quota
daily, which looks exactly like your code being broken.

**The CSP is the silent failure.** The embed simply does not appear. Nothing in
the server log, nothing in the network tab that reads as an error unless you
look at the console.
""",
    "verify_md": """\
**Which endpoint is being called, and what does it cost?** Read the code, not
the intention. If `search` appears anywhere in a loop, the quota is already
gone.

**What is the quota actually at?** Google Cloud console, APIs and services,
Quotas. Check it after a real day rather than assuming.

**Does the embed render on the live site?** Not locally. The CSP differs, and
this is the failure that only appears in production.

**Is the key restricted?** Console, Credentials. An unrestricted key is the
finding.

**Does a deleted video break the page?** Delete one on a test channel, or point
a row at a bogus id, and load the page.
""",
    "steps": [
        ("Get an API key, not an OAuth client",
         "Reading public videos needs no permission from the channel owner. "
         "OAuth is for uploading or reading private data, which is a different "
         "and much longer conversation.", None, "", ""),
        ("Restrict the key to the YouTube Data API",
         "An unrestricted Google key is a credential anybody who finds it can "
         "spend your quota with, and that looks exactly like your code being "
         "broken.", None, "", ""),
        ("Fetch uploads via playlistItems, never search",
         "`playlistItems.list` costs 1 unit; `search.list` costs 100. The "
         "daily quota is 10,000. This one choice is the difference between "
         "free and exhausted by lunchtime.", None, "", ""),
        ("Ask the client for the channel id, not just the handle",
         "A handle can be changed and the id cannot. Store the id, display the "
         "handle.", "email", "Two details about your YouTube channel",
         "Hi {client},\n\nTo pull your videos onto the site automatically I "
         "need two things:\n\n1. Your channel handle (the @name)\n2. Your "
         "channel ID — in YouTube Studio go to Settings, then Channel, then "
         "Advanced settings, and it is listed there\n\nI need the ID as well "
         "as the handle because handles can be changed later and the ID never "
         "changes, so building on the ID means the site keeps working if you "
         "ever rename.\n\nOne thing worth knowing: only public videos will "
         "appear. Anything uploaded as unlisted or private stays "
         "invisible.\n\nThanks,\nMichael\nBuilt by Bean LLC"),
        ("Store the video id and build URLs from it",
         "An embed URL in a database row is a rendering decision written "
         "permanently into data.", None, "", ""),
        ("Refresh on a schedule, not on a page load",
         "A channel changes a few times a week. Fetching per visitor spends "
         "quota on traffic.", None, "", ""),
        ("Name youtube-nocookie.com in the Content-Security-Policy",
         "The embed silently fails to render otherwise — nothing in the server "
         "log, nothing that reads as an error unless you open the console. It "
         "only shows up in production.", None, "", ""),
        ("Handle a deleted or privated video as normal, not as an error",
         "The client will delete things without telling you.", None, "", ""),
    ],
}


ESV = {
    "slug": "esv-api",
    "display_name": "ESV API",
    "logo_path": "",
    "vendor_url": "https://api.esv.org",
    "is_active": True, "is_default": False, "sort_order": 85,
    "one_liner": (
        "Scripture text from Crossway. The licence is the interesting part, not "
        "the endpoint."
    ),
    "client_only_md": """\
**Nothing technical.** The key is free and takes minutes.

**One thing that is genuinely theirs: how the text will be used.** Crossway's
licence distinguishes between a site quoting passages and a product
redistributing scripture, and the second needs their permission rather than an
API key. If what is being built looks like a Bible rather than a study aid,
that conversation happens with Crossway before it happens in code.
""",
    "access_grant_md": """\
**A free key from `api.esv.org`**, tied to an account and to a stated use.

    ESV_API_KEY

Requests go to `https://api.esv.org/v3/passage/text/` with the key in an
`Authorization: Token <key>` header.

**Degrade rather than break when it is absent.** Bible Study returns an empty
verse list and an explicit `"ESV_API_KEY not configured"` rather than raising,
so a missing key is a visible gap in a working page instead of a stack trace.
That is the pattern worth copying to every optional integration.
""",
    "your_steps_md": """\
**Display the copyright notice. It is a licence condition, not a courtesy.**
Bible Study carries `ESV_COPYRIGHT` alongside the verses and returns it even in
the error case, so no code path can render text without it.

**Cache aggressively.** Scripture does not change. A passage fetched once
should never be fetched again, and this makes almost every rate concern
disappear.

**Ask for exactly the passage you need.** The API takes a reference string and
will happily return a whole chapter you did not want.

**Turn off the extras you are not using.** Footnotes, headings and verse
numbers are all parameters; leaving them on and stripping them client-side
wastes both bandwidth and the reader's attention.
""",
    "traps_md": """\
**There is a limit on how much of the text you may show**, and it is a licence
term rather than a rate limit. Quoting whole books, or enough that the app
substitutes for a Bible, is outside what the key grants.

**The copyright notice is required on every rendering.** Attaching it to the
success path only means the one page that shows cached verses after an error is
the page that breaks the licence.

**Rate limits are per key and undocumented in any useful detail.** Cache and
the question never comes up.

**A reference the API cannot parse returns empty, not an error.** A typo in a
passage reference looks exactly like a passage with no verses.
""",
    "verify_md": """\
**Does the copyright notice appear on every path that renders text?**
Including cached, including error-with-stale-content. Grep for the render and
check each one.

**Does the app work with no key at all?** Unset it and load the page. A visible
"not configured" beats a 500.

**Does a nonsense reference behave?** Ask for something invalid and confirm it
reads as "nothing found" rather than as a broken page.

**Is anything fetching the same passage twice?** Watch the outbound requests on
a page that shows a passage more than once.
""",
    "steps": [
        ("Get a free key and state the actual use",
         "The key is tied to a stated use. If the product looks like a Bible "
         "rather than a study aid, that is a conversation with Crossway before "
         "it is a line of code.", None, "", ""),
        ("Return the copyright notice on every path, including errors",
         "It is a licence condition. Bible Study returns `ESV_COPYRIGHT` even "
         "in the error case so no code path can render text without it.",
         None, "", ""),
        ("Degrade visibly when the key is missing",
         "Bible Study returns an empty verse list and an explicit \"not "
         "configured\" message rather than raising. A visible gap beats a "
         "stack trace, and this pattern belongs on every optional "
         "integration.", None, "", ""),
        ("Cache every passage permanently",
         "Scripture does not change. Fetch once and the rate question never "
         "arises.", None, "", ""),
        ("Turn off footnotes, headings and verse numbers you do not render",
         "They are parameters. Fetching them and stripping them client-side "
         "wastes bandwidth and attention.", None, "", ""),
        ("Confirm a bad reference reads as empty, not as broken",
         "An unparseable reference returns nothing rather than an error, so a "
         "typo looks exactly like a passage with no verses.", None, "", ""),
    ],
}


LLM = {
    "slug": "llm-apis",
    "display_name": "LLM APIs",
    "logo_path": "pm/logos/anthropic.svg",
    "vendor_url": "https://docs.anthropic.com",
    "is_active": True, "is_default": False, "sort_order": 90,
    "one_liner": (
        "Anthropic and OpenAI behind one interface. The bill is usage, so the "
        "bug is a loop."
    ),
    "client_only_md": """\
**Whose account and whose card**, because this is the one integration where a
bug costs money in real time rather than degrading service.

**What may be sent.** Transcripts, customer records and documents all leave the
server. Check the provider's data-retention terms against what the client
believes, especially if the content is anyone's health, finance or legal
matter.

**A spend limit on the account.** Both providers offer one. It is the only
thing standing between a runaway loop and a card.
""",
    "access_grant_md": """\
**One key per provider, and the client is chosen at runtime.**

    ANTHROPIC_API_KEY
    OPENAI_API_KEY
    HUGGING_FACE_KEY      only where a hosted model is used

Meeting Assistant reads them from the environment and constructs whichever
client is configured, so a provider can be swapped without touching call sites.

**Handle the two failures separately.** Meeting Assistant catches
`AuthenticationError` and `RateLimitError` as distinct cases, because they need
different responses: one is a broken key that will never succeed, the other is a
retry. Collapsing them into one `except` means retrying forever against a key
that is simply wrong.

**Tool definitions are not portable.** The same tool needs a different shape for
each provider — Meeting Assistant keeps `active_tools_anthropic` and
`active_tools_openai` side by side rather than pretending one schema fits both.
""",
    "your_steps_md": """\
**Set a hard spend limit before the first call.** Not after the first bill.

**Pin the model and know its cutoff.** "Latest" changes underneath you, and an
app whose behaviour changed without a deploy is a bad afternoon.

**Cap the loop.** Anything agentic needs a maximum number of turns and a
maximum spend per request. The failure mode of an unbounded loop is not a crash,
it is an invoice.

**Never log the prompt when it carries customer data.** The prompt is the most
sensitive thing in the request and the most tempting thing to log.

**Stream when a person is waiting.** A response that takes twenty seconds and
arrives at once reads as broken; the same response streaming reads as fast.
""",
    "traps_md": """\
**Cost scales with input, and context is input every single time.** A
conversation that grows to fifty messages pays for all fifty on every turn.
This is the bill nobody predicts.

**A retry loop against a rate limit is an amplifier.** Back off exponentially,
and cap the attempts. Retrying immediately turns a busy minute into a longer
one.

**A wrong key and a rate limit look similar from a distance and are opposite
problems.** One will never succeed; one will succeed shortly.

**Model deprecation has a date and the SDK knows it.** Anthropic's client ships
a table of models and their deprecation dates. Pin deliberately, and check that
table rather than finding out from a 404.

**Local Whisper and hosted Whisper are different products with the same name.**
Meeting Assistant runs a local preset with hot-swapping; assuming an API call
where a local model runs, or the reverse, changes both the cost and the privacy
answer entirely.

**Output tokens cost several times input tokens.** A prompt asking for a long
answer is more expensive than a long prompt.
""",
    "verify_md": """\
**Is there a spend limit on the account right now?** Provider console. This is
the check to run first and the one most likely to be missing.

**What does one typical request actually cost?** Read the usage dashboard after
a real request rather than estimating from token counts.

**Does an authentication failure stop, and a rate limit retry?** Break the key
deliberately and confirm the app gives up instead of hammering.

**Is there a turn cap on anything agentic?** Read the loop. If there is no
maximum, there is no ceiling on the bill.

**Is any prompt reaching the logs?** Grep the logging calls for the prompt
variable.
""",
    "steps": [
        ("Put a hard spend limit on the account before the first call",
         "The only thing between a runaway loop and a card. Both providers "
         "offer one.", None, "", ""),
        ("Agree with the client what may leave the server",
         "Transcripts, customer records and documents all go to a third party. "
         "Check the retention terms against what they assume, especially for "
         "anything medical, financial or legal.",
         "email", "What {project} sends to the AI service",
         "Hi {client},\n\nOne thing to be straight about before we switch this "
         "on.\n\nFor {project} to do the AI parts, the text it is working on "
         "gets sent to an outside service to be processed. That means whatever "
         "is in it — names, notes, whatever was said in a meeting — leaves our "
         "server and goes to theirs.\n\nThey do not train on it and they "
         "delete it on a set schedule, and I am happy to send you their terms "
         "in writing.\n\nI want you to say yes to that knowingly rather than "
         "find out later. If any of your material is sensitive enough that you "
         "would rather it stayed put, tell me and we will look at what can run "
         "locally instead.\n\nThanks,\nMichael\nBuilt by Bean LLC"),
        ("Pin the model, and check its deprecation date",
         "\"Latest\" changes underneath you. Anthropic's SDK ships a table of "
         "models and their deprecation dates; read it rather than finding out "
         "from a 404.", None, "", ""),
        ("Catch authentication and rate-limit failures separately",
         "One will never succeed, the other will succeed shortly. One `except` "
         "for both means retrying forever against a key that is simply wrong.",
         None, "", ""),
        ("Back off exponentially and cap the attempts",
         "An immediate retry against a rate limit is an amplifier: it turns a "
         "busy minute into a longer one.", None, "", ""),
        ("Cap turns and spend on anything agentic",
         "The failure mode of an unbounded loop is not a crash, it is an "
         "invoice.", None, "", ""),
        ("Keep the tool definitions per provider rather than one shared shape",
         "They are not portable. Meeting Assistant keeps "
         "`active_tools_anthropic` and `active_tools_openai` side by side "
         "instead of pretending one schema fits both.", None, "", ""),
        ("Make sure no prompt carrying customer data reaches the logs",
         "The prompt is the most sensitive thing in the request and the most "
         "tempting thing to log.", None, "", ""),
        ("Stream anything a person waits on",
         "Twenty seconds arriving at once reads as broken. The same response "
         "streaming reads as fast.", None, "", ""),
        ("Know whether the speech model is local or hosted",
         "Local Whisper and hosted Whisper share a name and nothing else. "
         "Which one is running changes both the cost and the privacy answer.",
         None, "", ""),
    ],
}


APPSTORE = {
    "slug": "app-store",
    "display_name": "App Store",
    "logo_path": "pm/logos/appstore.svg",
    "vendor_url": "https://developer.apple.com",
    "is_active": True, "is_default": False, "sort_order": 95,
    "one_liner": (
        "Shipping a Capacitor app to iOS. The build is the easy half; review is "
        "the half that costs weeks."
    ),
    "client_only_md": """\
**An Apple Developer Program membership, in their name, on their card.**
$99 a year, and enrolment for an organisation needs a D-U-N-S number, which can
take days to obtain on its own. Start it before anything else.

**The legal entity name has to match**, exactly, across the developer account,
the app listing and the privacy policy. This is a rejection reason.

**Their decisions on the listing**, and all of them block submission: app name,
subtitle, category, age rating, support URL, marketing URL, privacy policy URL,
and screenshots at every required size.

**A privacy policy that is true.** App Privacy answers on the listing are a
declaration. Getting them wrong is worse than a rejection because it is a
statement about their business.

**Anything paid, decided up front.** Digital goods must use Apple's in-app
purchase and Apple takes its cut. That is a pricing conversation, not a
technical one.
""",
    "access_grant_md": """\
**An invite to their developer account** — App Store Connect, Users and Access.
Admin to configure the app, Developer to build and upload. Never their Apple ID.

**Certificates and provisioning profiles are per account.** Let Xcode manage
signing automatically unless there is a reason not to; hand-managed profiles
expire quietly and the failure surfaces as a build error weeks later.

**RevenueCat, if there is anything to buy.** Data Dungeon carries
`@revenuecat/purchases-capacitor` and `RC_PUBLIC_KEY`, which is a RevenueCat
public key. It sits between the app and StoreKit so receipts, restores and
subscription state are not hand-rolled — which is the right call, because
receipt validation is where homegrown IAP goes wrong.

    RC_PUBLIC_KEY      RevenueCat, safe in the client
""",
    "your_steps_md": """\
**Decide Path A or Path B and write down why.** Data Dungeon documents this in
`docs/APP_STORE_PATH_DECISION.md`:

  - **Path B**, chosen for v1: the WebView loads the live site through
    `server.url`, so the app is identical to the website with no second surface
    to maintain.
  - **Path A**, kept as the fallback: bundle the frontend into `webDir` and
    drop `server.url`. Moved to only if Apple rejects Path B on Guideline 4.2.

Having the fallback already scaffolded is what turns a rejection from a crisis
into a switch.

**Add native value deliberately.** Haptics, local notifications, share, splash
and status bar are all there in Data Dungeon's plugin list, and they are the
argument against 4.2 as much as they are features.

**In-app account deletion has to exist, in the app.** Guideline 5.1.1(v). Under
Path B it is the live account page; under Path A it has to be built.

**Write the review notes as though the reviewer has never seen it.** Test
credentials, what to tap, what the app is for. Most rejections are a reviewer
who could not get in.

**Ship through TestFlight first, to a real device that is not yours.**
""",
    "traps_md": """\
**Guideline 4.2 is the one that kills web wrappers.** An app that is a website
in a shell gets rejected as offering minimal functionality. Data Dungeon takes
this risk knowingly and mitigates it with native plugins and explicit review
notes — but it is recorded as a *medium, recoverable* risk with a fallback
ready, not as a solved problem. Treat any `server.url` app the same way.

**Guideline 5.1.1(v): account deletion must be possible inside the app.** Not a
link to email support. Apps get rejected for this constantly and it is trivial
to add before submission and awkward after.

**Enrolment is not instant.** D-U-N-S lookup, verification calls, and a wait.
Weeks, not days, if it starts late.

**Digital goods must use in-app purchase.** Taking payment for digital content
any other way is a rejection, and Apple's cut has to be in the client's pricing
from the start rather than discovered at submission.

**`npx cap sync` after every web build, or you ship the old bundle.** The
native project holds a copy. A build that looks fine on the web and stale in the
app is almost always a missed sync.

**Screenshots are required at specific sizes and a missing one blocks
submission** with no partial save.

**The first review is the slow one.** Budget for a rejection, because the
turnaround on a resubmission is the thing that pushes a launch date.
""",
    "verify_md": """\
**Does the app run on a real device, not the simulator?** Camera, notifications
and StoreKit all behave differently, and the simulator will let you believe
otherwise.

**Can you delete an account from inside the app?** Walk it as a user. If it
takes an email, it fails 5.1.1(v).

**Does the bundle actually contain the current build?** Run `npx cap sync`, then
check the version the app reports against the one you built.

**Does a purchase restore on a fresh install?** Delete the app, reinstall, sign
in, restore. This is what a reviewer tests and where hand-rolled IAP fails.

**Do the review notes let a stranger in?** Hand them to somebody who has never
seen the app and watch them try.

**Does the App Privacy declaration match what the app actually collects?**
Compare it against the network calls, not against what you remember building.
""",
    "steps": [
        ("Get the client enrolled in the Apple Developer Program",
         "$99/year on their card, in their name. Organisation enrolment needs a "
         "D-U-N-S number, which takes days on its own. This is the long pole "
         "and it is entirely on their side.",
         "email", "The Apple account for {project} — worth starting now",
         "Hi {client},\n\nTo put {project} on the App Store you need an Apple "
         "Developer account in your business's name. It has to be yours rather "
         "than mine, because the app is published as your company and the "
         "agreements with Apple are with you.\n\nIt is $99 a year at "
         "https://developer.apple.com/programs/\n\nHave ready:\n- Your legal "
         "business name, exactly as registered\n- Your D-U-N-S number — if you "
         "do not have one Apple will walk you through getting it free, but it "
         "adds a few days\n- A business phone and address\n\nApple may "
         "telephone to verify. I would start this now even though we are weeks "
         "from submitting; it is consistently the slowest part and everything "
         "else waits on it.\n\nOnce it exists, add me under Users and Access "
         "and I will handle the rest.\n\nThanks,\nMichael\n"
         "Built by Bean LLC"),
        ("Get added under Users and Access, never their Apple ID",
         "Admin to configure the app, Developer to build and upload.",
         None, "", ""),
        ("Decide Path A or Path B, and write down why",
         "Path B loads the live site through `server.url` — one surface, full "
         "parity, and the shape Guideline 4.2 scrutinises. Path A bundles the "
         "frontend. Data Dungeon chose B and keeps A scaffolded, which turns a "
         "rejection from a crisis into a switch.", None, "", ""),
        ("Add native capability deliberately, not decoratively",
         "Haptics, local notifications, share, splash, status bar. Under 4.2 "
         "these are the argument as much as they are features.",
         None, "", ""),
        ("Build in-app account deletion",
         "Guideline 5.1.1(v). Not a link to email support. Trivial before "
         "submission, awkward after, and a constant rejection reason.",
         None, "", ""),
        ("Collect the listing decisions from the client in one ask",
         "Name, subtitle, category, age rating, support URL, marketing URL, "
         "privacy policy URL, and screenshots at every required size. All of "
         "them block submission and a missing one cannot be saved around.",
         "email", "What the App Store needs from you for {project}",
         "Hi {client},\n\nApple needs a set of details before {project} can be "
         "submitted. All of them block the submission, so it is easiest to get "
         "them in one go:\n\n- App name as it should appear (30 characters "
         "max)\n- A subtitle (30 characters)\n- Which category it belongs in\n"
         "- A support URL and a marketing URL\n- A link to your privacy "
         "policy\n- Your age rating — I will send the questionnaire\n\nOn the "
         "privacy policy: Apple asks us to declare exactly what the app "
         "collects, and that declaration is a statement about your business "
         "rather than a formality. I will draft what I know the app does and "
         "have you confirm it before it goes in.\n\nThanks,\nMichael\n"
         "Built by Bean LLC"),
        ("Use RevenueCat rather than hand-rolling receipts",
         "`@revenuecat/purchases-capacitor` with `RC_PUBLIC_KEY`, as in Data "
         "Dungeon. Receipt validation, restores and subscription state are "
         "where homegrown in-app purchase goes wrong.", None, "", ""),
        ("Run `npx cap sync` after every web build",
         "The native project holds its own copy. A build that looks right on "
         "the web and stale in the app is almost always a missed sync.",
         None, "", ""),
        ("Test on a real device, not the simulator",
         "Camera, notifications and StoreKit all behave differently, and the "
         "simulator will let you believe otherwise.", None, "", ""),
        ("Delete the app, reinstall and restore a purchase",
         "Exactly what a reviewer does, and where hand-rolled in-app purchase "
         "fails.", None, "", ""),
        ("Write review notes that let a stranger in",
         "Test credentials, what to tap, what the app is for. Most rejections "
         "are a reviewer who could not get in. Hand them to somebody who has "
         "never seen it and watch.", None, "", ""),
        ("Ship to TestFlight before submitting, and budget for one rejection",
         "The first review is the slow one, and the resubmission turnaround is "
         "what moves a launch date.", None, "", ""),
    ],
}


PLAYBOOKS = [POSTGRES, SENTRY, NOMINATIM, YOUTUBE, ESV, LLM, APPSTORE]

FIELDS = ("slug", "display_name", "logo_path", "vendor_url", "is_active",
          "is_default", "sort_order", "one_liner", "client_only_md",
          "access_grant_md", "your_steps_md", "traps_md", "verify_md")


def upgrade():
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())
    if "playbooks" not in tables:
        return
    has_steps = "playbook_steps" in tables
    cols = {c["name"] for c in sa.inspect(conn).get_columns("playbooks")}
    fields = [f for f in FIELDS if f in cols]

    # Marks for the three that shipped as initials last wave. Only where the
    # playbook still has none, so a hand-picked logo is never overwritten.
    if "logo_path" in cols:
        for slug, path in BACKFILL_LOGOS.items():
            conn.execute(sa.text(
                "UPDATE playbooks SET logo_path = :p WHERE slug = :s "
                "AND (logo_path IS NULL OR logo_path = '')"),
                {"p": path, "s": slug})

    # One step from the original seed shipped with no detail line, so it is
    # the only step in 155 that renders as a bare title. Filled in here rather
    # than by editing a migration that has already run everywhere.
    if has_steps:
        conn.execute(sa.text(
            "UPDATE playbook_steps SET detail_md = :d "
            "WHERE title = :t AND (detail_md IS NULL OR detail_md = '') "
            "AND playbook_id IN (SELECT id FROM playbooks WHERE slug = 'railway')"),
            {"t": "Tell the client it is live, with the URL",
             "d": "After the deploy has been checked against the commit, not "
                  "before. A handover message pointing at a URL that 404s is "
                  "worse than no message, and it is the first thing they will "
                  "click."})

    for pb in PLAYBOOKS:
        if conn.execute(sa.text("SELECT 1 FROM playbooks WHERE slug = :s"),
                        {"s": pb["slug"]}).first():
            continue
        conn.execute(
            sa.text("INSERT INTO playbooks (%s) VALUES (%s)" % (
                ", ".join(fields), ", ".join(f":{f}" for f in fields))),
            {f: pb[f] for f in fields})

        if not has_steps:
            continue
        row = conn.execute(sa.text("SELECT id FROM playbooks WHERE slug = :s"),
                           {"s": pb["slug"]}).first()
        for i, (title, detail, channel, subject, message) in enumerate(pb["steps"]):
            conn.execute(sa.text(
                "INSERT INTO playbook_steps (playbook_id, position, title, detail_md, "
                "client_channel, client_message_subject, client_message_md) "
                "VALUES (:p, :pos, :t, :d, :c, :s, :m)"),
                {"p": row[0], "pos": i, "t": title, "d": detail,
                 "c": channel, "s": subject, "m": message})


def downgrade():
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())
    if "playbooks" not in tables:
        return
    for pb in PLAYBOOKS:
        # Steps first: SQLite does not enforce the cascade during a migration,
        # and orphaned steps reattach to whichever playbook next takes the id.
        if "playbook_steps" in tables:
            conn.execute(sa.text(
                "DELETE FROM playbook_steps WHERE playbook_id IN "
                "(SELECT id FROM playbooks WHERE slug = :s)"), {"s": pb["slug"]})
        conn.execute(sa.text("DELETE FROM playbooks WHERE slug = :s"),
                     {"s": pb["slug"]})
    # The backfilled marks go back to empty, which is where they started.
    for slug, path in BACKFILL_LOGOS.items():
        conn.execute(sa.text(
            "UPDATE playbooks SET logo_path = '' WHERE slug = :s AND logo_path = :p"),
            {"s": slug, "p": path})
