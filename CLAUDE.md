# Built By Bean - website + project manager

This repo serves builtbybeans.com and the live PM at `/admin`. Flask +
SQLAlchemy + Alembic, Jinja + Tailwind + Alpine, Postgres on Railway in
production, SQLite locally. Pushing to `main` deploys.

The feature catalogue at `/admin/features` is the CROSS-REPO lesson store:
when any project teaches a lesson, it goes there (pitfalls_md) as well as
here. Its second half is `/admin/features/rules` - the layer under the
features, `kind='rule'` on the same table: ways of building that hold no
matter what was bought. Every rule rides into every MVP build prompt as a
house rule, so writing a lesson there is how every future project gets
it. This file is for lessons about THIS repo's own code.

## The god door

Other Claude sessions reach the catalogue live through
`/api/guidance/*` (`pm/guidance_routes.py`): the rules brief, feature
search, playbook runbooks, and a POST that files lessons back - bearer
token `GUIDANCE_API_KEY`, compared in constant time, 401 on everything
when unset. `tools/pm_guidance_mcp.py` is the zero-dependency stdio MCP
bridge that puts those four tools (`get_rules`, `get_feature_guidance`,
`get_playbook`, `report_lesson`) into every session on this machine; it
is registered at user scope in Claude Code with the deployed board's URL
and key, and `~/.claude/CLAUDE.md` carries the standing order to use
them. The text of that order is `tools/STANDING_ORDER.md`, and
`tools/bootstrap_guidance.ps1 -Key <key>` puts both the order and the
registration on a new machine in one command; on 2026-09-04 neither
turned out to exist on the owner's laptop, so check both before
assuming any session can file anything. Neither travels with a repo or
an account, so the MVP build prompt now carries the loop itself: it
tells the session to consult the live board, to stop and say so if the
tools are missing, and to file what it learns as it goes. The write path appends with attribution and refuses duplicates,
because reporting sessions retry like any other API client.

The catalogue grows itself through the same door, with the policy set by
the SHAPE of a change, not by trust in the sender. Everything a session
sends becomes a `CatalogueProposal` (`pm/guidance_routes.py`, the
`suggest_update` tool): an append or a create applies on arrival and can
be reverted from `/admin/features/inbox` in one press; a replace of
existing words waits there as pending and touches no build prompt until
accepted. `previous` is snapshotted at apply time so revert is exact.
The Rules and Playbooks pages carry no add button on purpose: sessions
write those through the door, and a hand-typed one is never written
properly. Features keep their quick-add, because a client names one on
a call and it has to be caught in seconds.
Sessions may also file operational records - `upsert_project`,
`log_expense`, `log_time`, `register_hosting_resource` - and may NOT
contact a client, resolve a ticket or send a contract: those are
Michael's, and the API has no route for them on purpose. A playbook's
checklist goes through the same door: `steps` is a structured field on
kind playbook, a list in the payload rather than text. Append adds to
the end on arrival, replace rewrites the list and waits in the inbox, a
create may carry steps, and revert puts back the exact list that was
there.

## Needs attention

`pm/attention_routes.py` is the mail waiting on a reply, and nothing else.
It carried seven signals once - declined contracts, hosting fees under the
floor, overdue invoices, catalogue rewrites, untriaged tickets, late
builds and mail - and six of them already had a home on the page that owns
the work, which made this a page to skim rather than clear. Mail was the
only one with nowhere else to be answered. Hosting still reads its own
sidebar badge out of `attention_counts()`, so that dict keeps a `hosting`
key that is not a row on the page; `total` is the mail alone.

Each row carries Reply and Dismiss. Dismiss is `messages.archive`, which
archives the inbound thread AND the row pressed - it matched the thread
alone once, so a message with no `thread_id` was left untouched while the
flash still said "Archived." A press that reports success has to have
acted on the thing that was pressed.

A dismissal holds across a sync because `mail_service.ingest` only ever
inserts. It hung entirely on the Message-ID header though, with the check
SKIPPED when that header was absent, and the IMAP search reaches two days
behind the newest row - so a mail with no Message-ID was re-inserted every
five minutes as a NEW row with a new id and a new status, and archiving it
did nothing anybody could see. Mail without that header now gets a
fingerprint of its sender, date and subject.

## Tickets travel both ways

Tickets are PUSHED here by each client app's outbox, and `hub.fetch` is
the board asking for them: the same signed POST as a push, because the
signature covers a body and a GET has none. Daily, five minutes after boot
so a deploy is also a catch-up, plus a Resync button on the tickets page.
`Client.hub_pulled_at` and `hub_pull_note` are when the board last asked
and what came back, and the tickets page names the apps that are not
answering rather than drawing an empty list. A 200 that is not JSON is a
failure, not an empty list of tickets.

Only Talent Booker and Kuper Plumbing speak this hub, and each answers
`/api/hub/tickets/since` by calling its OWN outbox builder rather than
writing the payload a second time. The board's side is the same:
`_apply_hub_ticket` is lifted out of the push endpoint and the pull goes
through it, so a pulled ticket cannot overwrite triage that a pushed one
respects. Two builders is two shapes and two ingest paths is two answers
to "what may an update touch", and in both cases the copy that drifts is
the one nobody watches.

## The mail comes in

`pm/mail_service.py` reads Michael's Gmail over IMAP with the same app
password that already sends (`MAIL_USERNAME`/`MAIL_PASSWORD`; no OAuth,
no Google Cloud project), pulling only mail from watched senders: every
client's address and everyone who has written through the site's form.
The mailbox is opened read-only; the board never marks, moves or deletes
in Gmail. `/api/contact` writes a `Message` row BEFORE it tries SMTP, so a
lead survives a mail outage. Replies (`/admin/messages/<id>/reply`) go
out from his own address with a real In-Reply-To, and are stored as
`out` rows in the thread. Sync runs in a background thread when the
attention or messages page opens, at most every five minutes; "Check
mail" is the synchronous version. Unanswered inbound mail is an attention
signal; the messages page is the full history, linked from there.

## The loop, enforced

Telling a session to consult the board and file what it learns was a
standing order, and a standing order is obeyed as well as it is
remembered. `tools/hooks/` makes the harness do it instead: SessionStart
fetches the rules brief and prints it, so every session on the machine
opens already briefed (and says LOUDLY if the bridge is missing or the
board answers 401); PostToolUse on Edit|Write notices a CLAUDE.md being
written and leaves a marker; Stop refuses to end the turn (exit 2, reason
on stderr) while that marker has no report_lesson or suggest_update
after it in the transcript, at most twice, never when stop_hook_active.
`tools/hooks/install.py` merges them into ~/.claude/settings.json without
touching anything else; the bootstrap runs it. Hooks print UTF-8 on
purpose - Windows hands them cp1252 and one minus sign in a rule killed
the injection after its header.

## The sweeper

`sweep_repos.py` runs after `sync_costs.py` in the same nightly cost-sync
service. It reads every repo on the GitHub account (GITHUB_TOKEN on that
service for private ones; public without), splits each CLAUDE.md into
headed sections, and proposes any heading the board has not seen for
that repo - through `_propose(..., hold=True)`, so it lands PENDING on
Needs attention rather than riding into every build prompt as repo
prose. `RepoWatch` holds the blob sha and the headings seen; the first
read of a repo only records, so nothing mined by hand comes back.

## Cerebro

`pm/cerebro_routes.py` is every client held against the catalogue: chips
picked from products, features, playbooks and rules become columns, the
projects are rows, and a cell says who has it or who is breaking it. All
state is the query string (`?c=kind:slug&view=`), so a question is a URL.
Products come from sales, playbooks from ProjectPlaybook, features from
the client's packages, rules from `RuleAudit`. Rules carry their scanner
(`check_pattern`, `check_globs`, `check_exclude`, `check_unless`,
`check_fixture`); `audit_repos.py` runs every scanner over every repo's
tarball nightly, after the sweep, and upserts one row per (repo, rule).
Data Dungeon's principle holds here: a scanner that does not fire on its
own fixture is skipped and shown as failing, because zero hits from a
broken scanner reads exactly like a clean repo - and the first seeded
secrets scanner was exactly that until the fixture caught it. A project
knows its repo through `Project.repo` (the edit form, or the link list at
the bottom of Cerebro, which suggests from a shared word in the names).
Sessions may propose scanners on rules through `suggest_update`. A product carries a
signature the same way (`presence_pattern`, `presence_globs`,
`presence_exclude`, `presence_fixture`) and `ProductAudit` holds where
it fires: a product cell reads sale, then runbook applied, then "in the
code". The first version read the sales ledger alone and told the
owner two sites with working texting did not have it, because texting
was built into them before the catalogue existed - the code is the
truth about what a site has, the ledger is the truth about what was
billed, and Cerebro asks the code first when the ledger is silent.

## Users

`pm/users_routes.py`, CEO only, guarded on the route by `ceo_required`
(one decorator per audience) and not merely hidden in the nav. Four
titles: the CEO runs the board and its people; CTO, CMO and member are
titles with every other door and no Team section. The old values "owner"
and "admin" read as CEO (`User.is_ceo`, `role_label`) and the migrations
rewrote them, so nothing that existed lost a door. An account is switched
off (`is_active`), never deleted, because time entries and timer rows
point at it; a switched-off login gets the same "invalid" answer as a
wrong password, so the door does not say which. Passwords are never typed
here: a new account or a reset gets a temporary one, shown to the CEO
once (carried in the server session, popped on the next load, never a
flash - the flash strip would print it too) and replaced on first sign-in
by the existing must_change_password gate. You cannot switch off or take
CEO off yourself, nor the last active CEO. The login takes a username or
an email, either case. Locked out entirely: set `RECOVERY_USERNAME` and
`RECOVERY_PASSWORD` on the web service, the boot after the restart sets
that password and says so in the log, then remove both. Michael's one
account is `Mbean`; on 2026-09-05 a merge of his two rows kept the other
one and dropped the password he knew, which is what that door is for. A
migration that touches the row somebody signs in with carries the
password forward or it has locked him out.

## Leads

`pm/leads_routes.py` at `/admin/leads`, the marketing seat's page and the
only one built for somebody other than Michael: Hannah Bean is the CMO and
lives in it. Signed in is the whole guard, because a call list nobody can
open is a call list nobody works.

The list is every business in the Paris trade area with EVIDENCE OF
TRADING, built by `import_leads.py` out of public records: the
Comptroller's Active Sales Tax Permit Holders (the spine, with trading
name, street, NAICS, and the date they started selling), **Overture Maps
places** (the only source that carries contact details at scale - four
thousand places for this area with telephone numbers, emails, websites and
social pages; read straight off its public parquet with DuckDB over S3, and
skipped with a message if DuckDB is missing), the FMCSA motor carrier
census, the CMS provider registry, OpenStreetMap, and the business licences
from TDLR. Active Franchise Taxpayers ENRICH and never create,
because a registration proves an entity exists and nothing more. Lamar,
Red River and Delta counties plus the eastern edge of Fannin; Bonham,
Leonard, Trenton, Savoy and Whitewright are forty to sixty miles out
toward Sherman and belong to a different town's list.

Two counts were wrong on the first build and are worth remembering. Every
individual worker licence in the state file - 586 cosmetology operators,
560 apprentice electricians - became a "business", and every franchise
registration became one too: 12,334 rows where about 2,300 businesses
trade. A licence held by a PERSON is a qualification; only the
establishment and contractor licences are businesses.

Employees and revenue are columns the import leaves empty except where a
haulier files a driver count, and the page prints "not published" rather
than a figure. No free public source carries either for a private firm in
a town this size, and a guessed number on a call sheet is worse than a
blank: it gets repeated on the phone.

**"No site found" is a checked fact, not a blank column.**
`check_websites.py` goes and looks: for each business it builds the domains
that business would plausibly own, resolves them, fetches what exists and
reads the page to decide whether it is really theirs, refusing registrar
holding pages. A name made only of ordinary words has to see its own town or
its state on the page as well, and a short list of famous domains is never
anybody's: a shop called The White House was matched to whitehouse.com,
which then supplied a contact named Donald Trump. `--reguess` re-tests only
the websites this file guessed, never one a places dataset published. A hit is proof; a miss is recorded as `website_checked_at`
with no website, which is why the tile says "no site found" rather than "no
website". Of 3,746 businesses it found 1,046 sites nobody had listed, and
2,591 have none to be found. Before it existed the board printed that
absence straight off an empty column, which is this repo's own Cerebro
principle broken in its own words: zero hits from a check that never ran
reads exactly like a clean result.

A business that opened in the last twelve months is the one that has not
bought a website from anybody yet, so "Started" is a filter of its own rather
than something to reach by sorting: three windows (12 months, 2 years, 5
years) counted in days against `started_on`, with a blank start date counted
as no answer rather than as young. 342 of the 5,740 opened in the last year
and 252 of those have no site found, which is the call list this page exists
to produce.

The tiles count the FILTERED query, not the table, and every number on the
board wears its commas (catalogue rule "Numbers wear their commas"). The
filter options are alphabetical, each control is labelled with what it
filters, and the long ones carry a search box from `select_dropdown`
(catalogue rule "A long filter list is searchable and alphabetical").

Every filter's counts are FACETED: `narrowed(skip=...)` builds the list
under all the filters except one, so a trade's count means "how many of what
you are looking at", and an option that would return nothing is not offered.
Picking Paris and then "Pet grooming (1)" used to return an empty page,
because the 1 was counted over the whole table and that groomer is in
Blossom. Whatever is already chosen stays in its own list even at zero, or
the control cannot show its own value. The sort options say what they do; "Best bets" said nothing.
One vocabulary names each trade, because a map, a licence file and an
industry code called the same shop Restaurant, Restaurants and bars, and
Restaurants and cafes, and filtering to one of the three silently hid the
other two. The Comptroller files an unknown start date as 1961-09-01, the
day the sales tax began, and that is stored as no date rather than rendered
as sixty-five years of trading.

`enrich_sites.py` then reads each business's own website: the emails and
telephone numbers on its contact page, and the PEOPLE. A headcount is taken
only where the business states one itself ("a team of fourteen"); nothing is
estimated, ever, for the reason above.

Getting a NAME right is harder than it looks and the first two attempts both
shipped rubbish onto a live call sheet. "Featured There", "Founding Member"
and "Athletics Athletics" all arrived as contacts, because any two
capitalised words beside a job title look like a person and page headings
are exactly that shape. Then "Prmc Gme" and "Credit Department" arrived from
mailboxes shaped like firstname.lastname@, and "Christian Ministries" and
"Russell Cellular" from business names whose first word happens to be a
forename. Four rules now, and they cost recall on purpose:

  - titles are MASKED out of the text before names are looked for, because a
    non-overlapping scan reads "Owner Marla" as a name and, having eaten it,
    never offers "Marla Quinn";
  - the first word must be a forename people are actually given, from a
    list, and that applies to mailbox-derived names too;
  - the second word must not be a word businesses end in (ministries,
    cellular, distributing, roofing);
  - and a name wholly inside the business's own name is the business.

A wrong name is worse than a blank one, because somebody reads it out.

`dedupe_key` (flattened trading name plus house number and street) is what
makes the import re-runnable, and the loader never overwrites a phone,
email, website or owner that somebody typed over it, nor any stage, note or
person added on the board. `norm()` folds "and" into "&", because that is
the commonest way one business is spelled two ways between a tax roll and a
map, and a merge pass at the end of the import folds any that still arrive
twice into the row that knows most - never one somebody has worked. The
`sources` column keeps marks the import does not own, so a re-import does
not make `enrich_sites.py` redo every site. Re-run it with
`python import_leads.py --cache <dir>` to reuse a pull rather than ask the
same APIs again.

A row opens on press and only one opens at a time. That is LM-1 avoidance
rather than taste: the open row carries `select_dropdown` panels, so it
alone takes `relative z-30` while every other row sits at `z-0`, and a
later sibling card cannot paint over the panel. Logging an attempt moves
the stage as far as the outcome warrants and no further, so a call logged
against a lead already at "proposal sent" does not walk it backwards; the
filters ride in each row form as `f_*` fields so a press returns to the same
page of the same list, and the prefix is load bearing because the stage form
posts `stage` as the new stage. "Make them a client" writes a `Client`
carrying the address, the contact and everything learned, and links the two
rows.

## Hosting fees that raise themselves

`pm/hosting_routes.py` holds every priced project's fee against last
month's cost. Under `MIN_MARGIN` ($25 left over) the page offers "Draft
the increase": one link that opens the hosting agreement form filled in
as a fee update - the fee `RAISE_STEP` ($25/month) higher, the fee it
cancels, the first of next month as the start, the reason - and what is
left is reading it and sending it through the normal signing flow. The
sidebar badge on Hosting is that count, cached ten minutes. The fee only
lands on the project when the agreement goes out, through the same route
as every hosting agreement. `contract_docs.HOSTING_LAPSE` is the clause
that says what the fee is for and what stops when it stops being paid -
read into the SOW, the standalone agreement and every fee update from
that one place, so no two documents can describe it differently.

## House rules

- **Phone first.** Design at 375px and let it grow. Nothing scrolls the page
  sideways, nothing overflows its card, every tap target is at least 44px.
  Verify with `getBoundingClientRect()`, not by looking. Sweep every route
  by loading it in a 375px-wide iframe and asserting
  `#pm-scroll.scrollWidth <= #pm-scroll.clientWidth` (the scroller clips
  sideways overflow so nobody sees it, but scrollWidth still reports it;
  `documentElement.scrollWidth` no longer tells you anything) - and seed
  the fixtures with
  LONG strings and a long URL first, because short seed data hides all four
  of the causes found this way: a `flex-1` input with no `min-w-0` (its
  min-width is its placeholder's intrinsic width), a `truncate` span with no
  `max-w-full` on the flex parent to ellipsis against, a pill row that
  cannot `flex-wrap`, and a long URL in rendered markdown, which overflows
  as a TEXT node so every element box still measures inside the viewport. A
  wide table is fine inside its own `overflow-auto` container: the table
  scrolls, the page does not.
- **The window never scrolls.** The banner is a plain block at the top of
  `.pm-shell` and `#pm-scroll` under it is the one scroller, so every
  scrollbar starts at the banner's bottom edge and never runs up behind
  it. Anything that moves the page moves that box (`scroller.scrollTop`),
  never `window.scrollTo`; sticky bars stick to it at `top: 0`. Verify on
  every page: `documentElement.scrollHeight <= innerHeight`, and
  `#pm-scroll.getBoundingClientRect().top` equal to the banner's bottom.
- **No em dashes. Anywhere.** Not in product copy, not in commit messages.
- **Text alone is never a button.** Anything that acts on press gets a border
  or a fill. Actions sit on the trailing edge.
- **No explainer copy on pages.** Reasoning goes in code comments, never on
  the screen. Never reuse one icon for two things.
- **Migrations:** name every constraint, guard every create_table on the
  table not existing (create_all runs on boot and wins the race), drop
  children before parents, and run `flask db downgrade <prev>` then
  `flask db upgrade` before pushing. SQLite accepts orderings Postgres
  refuses, and Postgres performs newline string-literal concatenation in SQL
  that SQLite refuses - use bound parameters for any multi-line text.
- **A pushed commit is not a deployed commit.** Check
  `railway deployment list` for SUCCESS on the new deploy, then verify
  against the public URL, never the container.
- **An expression built from `|tojson` goes in a SINGLE-quoted attribute.**
  `|tojson` escapes `<`, `>`, `&` and `'` and leaves `"` alone, so
  `x-show="{{ list|tojson }}.includes(x)"` ends at the first double quote it
  writes. It shipped as `x-show="["`, Alpine threw on every row, and the
  buttons that record how a call went were never once on the screen. Grep:
  `rg -n 'x-[a-z]+="\{\{[^"]*tojson' templates/`.
- **PowerShell mangles UTF-8.** Never round-trip a template through
  `Get-Content | Set-Content` - the box-drawing and arrow characters in
  comments come out as mojibake. Use targeted editing tools.

## Landmines

Each one shipped from this repo. Format: what happened, why it is easy to
do, the rule, and a grep that finds regressions.

### LM-1 - a staggered card paints over the dropdown panel of the card above it

**What happened.** On 2026-09-03 every `select_dropdown` on the MVP Builder
pages opened to a panel where only the first option was readable - the rest
sat as blank rows. The options were in the DOM and the accessibility tree
the whole time. TWO separate mechanisms make every card on these pages its
own stacking context: `.glass-card` carries `backdrop-filter`, which
creates one permanently and on its own, and `.stagger-in > *` ran its entry
animation with `animation-fill-mode: both`, whose final keyframe keeps
`transform: translateY(0)` applied forever - still a transform, a second
context. The dropdown's `absolute z-50` panel is scoped INSIDE its card's
context, so the next sibling card - later in DOM order, equal in the root
stacking order - painted on top of it, and that card's glass backdrop-blur
wiped the text. The first option survived only because it landed in the gap
between the two cards. The invoices page had carried the same bug since
before the animation existed, because backdrop-filter alone is enough.

**Why it is easy to do.** The panel, the card, the glass effect and the
animation are four places that each look correct alone, and the bug needs a
dropdown in one card WITH content below it - short lists and single-card
forms hide it, so the pattern shipped many times before it bit. Worse, the
failure reads as a rendering glitch: the text exists in the DOM,
`read_page` returns it, and only pixels - or an `elementFromPoint` check -
see that another element is on top.

**The rule.** Any container holding a `select_dropdown` whose panel can
overlap LATER sibling content carries `relative z-30` - including panels
that can poke past the bottom edge of their own card when the list below
the filters is short. Entry animations use `animation-fill-mode:
backwards`, never `both` or `forwards`, so they stop adding contexts of
their own. Layering budget: page content never exceeds `z-30`; dropdown
panels are `z-50` inside their card's context; the mobile drawer overlay
is `z-40` with the sidebar at `z-50`. A paint-order fix is verified with
`document.elementFromPoint()` on an OPEN panel's rows, never by eye.

**Grep.**
```
rg -n "animation:.*(both|forwards)" templates/
rg -n "select_dropdown\(" templates/pm --files-with-matches
```
Every file in the second list: each dropdown-bearing card with later
siblings must carry `relative z-30`.

### LM-2 - a native `<select>` is never the answer

**What happened.** The Features page, the clients list, the client detail
stage picker and the MVP quick-add all shipped with native `<select>`
elements while the rest of the app used `select_dropdown` - so half the app
opened OS-grey squared option lists in a dark themed product. Three more
natives hid in the products sell modal and the SOW and hosting forms with a
comment excusing them: "the options are filtered live by the chosen client
and the macro renders a fixed list at template time."

**Why it is easy to do.** The CLOSED control styles fine, so a native select
looks right in every screenshot until somebody opens it. And the moment a
picker needs live-filtered options, the fixed-list macro genuinely could not
serve it - so the workaround propagated with its own justification attached.

**The rule.** Every picker is `select_dropdown`, no exceptions. The
component renders its rows from Alpine at runtime, so a live-filtered list
is served by dispatching `dropdown-set-options` with
`{ name, options: [{v, l}] }` from an `x-effect` that references its
dependencies synchronously and delivers with PLAIN DOM APIs deferred by
`setTimeout(..., 0)`:
`setTimeout(() => window.dispatchEvent(new CustomEvent(...)), 0)`. The
deferral is what lets the first run land after descendants register their
listeners - and it must not be `$nextTick`, because `$dispatch` inside a
`$nextTick` callback is a SILENT no-op (verified against Alpine 3.17.1:
the direct call updates the rows, the wrapped one does nothing, no error
anywhere). Pass `model=` for two-way binding - a modal that resets its
fields resets the visible label too. Include an explicit `{v: '', l: ...}`
row when "none" must be re-pickable; the placeholder alone is not an
option.

The same rule caught checkboxes next, on the same day: nine native ones
wearing the OS-blue tick in a purple app, and the products-page one gave
no feedback until Save. Every checkbox is the `components/checkbox.html`
macro - real input kept `sr-only` inside the label so names, x-model and
submits all still work; the visible box is styled through `peer-checked`
with no script. When the label must react to the state, pass `model=` and
put the reactive markup in a `{% call %}` block.

Then `confirm()` turned out to be the same sin a third time: ten OS dialogs
- system grey, system font, blocking the page - appearing at the exact
moment somebody deletes something. Destructive actions now ask in place
with `components/confirm_button.html`: pressed once the button becomes its
own question with Cancel beside it, clicking outside backs out, and the
armed button is the ONLY submit and is `:disabled` until armed, so a stray
Enter cannot fire the destructive path. Two actions that had no guard at
all (deleting an MVP package, erasing a sale) got one while sweeping.

And the widgets no component can replace - the date, month and number
pickers, the autofill wash, scrollbars - are handled by `:root {
color-scheme: dark; }` in base.html. Without it the browser paints its own
chrome LIGHT: white calendar popups dropped into a dark app.

**Grep.**
```
rg -n "<select" templates/pm --glob "!components/*"
rg -n '<input type="checkbox"' templates/pm --glob "!components/*"
rg -n 'confirm\(|alert\(' templates/pm --glob "!components/*"
```
Any hit is the regression.

### LM-3 - "the DOM is right" is not "the screen is right"

**What happened.** The LM-1 bug was visible during this repo's own browser
verification: a screenshot showed the open panel with one readable option
and blank rows below. It got written off as a preview-pane rendering glitch
because `read_page` and `get_page_text` returned every option, and the
session shipped on that. The owner found it in production within the hour.

**Why it is easy to do.** Text tools read the DOM, and the DOM was correct -
the failure was paint order, which only pixels and hit-testing see. When a
screenshot disagrees with the accessibility tree, the comfortable
conclusion is that the screenshot is wrong.

**The rule.** A control is verified in the state the user fears: a dropdown
with its panel OPEN, a modal opened over content, a drawer over a page.
When pixels and DOM disagree, the pixels are the bug until hit-testing
proves otherwise: `document.elementFromPoint(x, y)` at the control's own
coordinates must return the control or a descendant of it. A rendering
anomaly in verification is a finding, never a tooling excuse.

**Grep.** None - this one is a discipline, enforced by the audit snippet in
LM-1 whenever a dropdown or overlay changes.

### LM-4 - the filters scroll away with the list they filter

**What happened.** The Features page put ninety-three rows under a search
box, and the first scroll took the search box off the screen. The first
fix made the bar sticky - and shipped twice wrong: once with a gap the
rows scrolled through in the clear, once translucent with row text
reading straight through it. The owner's verdict named the real design:
the window should never have been scrolling at all. The scrollbar ran the
full height of the viewport on a page that is one filtered list. Then the
same tell showed on every other page: the window's scrollbar ran up
behind the banner. The owner's second verdict, the same day, made it the
house rule above: the scrollbar starts where the banner ends, everywhere.

**Why it is easy to do.** A filter bar laid out above its list is correct
in every screenshot, because screenshots are taken at the top of the
page. And sticky is the reflex fix because it changes one element; the
right fix changes who owns the scroll.

**The rule, two tiers.** A page that IS a filtered list - features,
rules, clients, tickets, time, resource mappings - gets CONTAINED scroll:
the child template fills `{% block main_class %}` with
`contained-scroll` (declared at template top level, never nested inside
the content block, where it silently does nothing), the bar and any tabs
are `shrink-0` normal blocks that simply stand still, and the results
region is the one scroller (`flex flex-col` chain, `min-h-0`,
`overflow-y-auto`). The window never scrolls; the scrollbar lives inside
the results and starts below the bar - a viewport-height scrollbar on a
list page is the tell that it is built wrong. `relative z-30` stays on
the bar per LM-1 so its panels paint over the list.

A MIXED page - real content above the list that must itself scroll away,
like the MVP builder - scrolls in `#pm-scroll` like every other page, and
its bar uses `.sticky-filters`: `top: 0`, which is flush under the banner
because the banner sits outside the scroller (nothing to measure, however
tall it wraps), backed SOLID by the class (`var(--surface)`), with no
Tailwind bg utility beside it because the CDN sheet loads later and wins
the cascade back to translucent.

Verify by scrolling, whichever tier: on every page
`document.documentElement.scrollHeight <= innerHeight`; on contained pages
the inner scroller's `scrollHeight` exceeds its height while
`#pm-scroll`'s does not; on sticky pages the bar's top equals
`#pm-scroll`'s top exactly once scrolled, and probes behind the bar
hit-test as the bar, never as a row.

**Grep.**
```
rg -n 'form method="GET"' templates/pm
rg -L 'main_class' $(rg -l 'form method="GET"' templates/pm)
```
Every filter-over-list page must either fill `main_class` with
`contained-scroll` or sit in a `.sticky-filters` container - and the
first choice is the default.

### LM-5 - a switch that means "there is a fee" was tested with `is not none`

**What happened.** The products row showed a ticked monthly box beside
"$0/mo", and after one fix it still did. The tick was
`monthly_price is not none`, a zero had been stored, and so the row
asserted a fee that did not exist. The first fix made the label react to
the tap and left the test alone. The fix after that added a field to type
the monthly into, which was never the design: nobody types the monthly on
that page.

**Why it is easy to do.** None and zero are different values with the
same meaning here, and the form only ever wrote None, so the zero case
looked impossible until one arrived from somewhere else. And a wrong
number on a label invites a field to correct it, when the number was
never meant to be editable there.

**The rule.** The product's monthly is a switch, not a figure. On means
the standard fee (`DEFAULT_HOSTING_FEE`, fifty) rides with the product;
what a client actually pays is set on the sale and raised from the
hosting page. A stored amount is on when it is truthy, and only then, and
the save route replaces a stored zero with the default, so on-at-zero
cannot be stored, not merely not shown. The row is the price field, then
three icon buttons on the trailing edge in the order toggle, sell, save.
Dollar figures render through the `commas` filter and reformat on blur.

**Grep.**
```
rg -n "monthly_price is not none|hosting_fee is not none" templates/
rg -n 'name="monthly_price"' templates/pm/products/index.html
```
The first: any hit is the regression. The second: exactly one hit, in the
sell dialog, never in the row.

### LM-7 - the panel was wider than the button, and the rows read over the search box

**What happened.** The owner photographed the town filter on the leads page:
the open panel stood 90px wider than the button that opened it and hung over
the filter beside it, and the option rows scrolled up through a strip above
the search box and read in the clear. Both faults were in the shared
`select_dropdown`, so both were on every picker in the product.

The width was deliberate and wrong. `min-w-full w-max max-w-[20rem]` was
written because a five-column triage grid is narrower than "Not classified"
and a panel pinned to the trigger wraps rows onto three lines. Wrapped rows
are the correct outcome; a panel that does not belong to its button is not.

The bleed was `position: sticky; top: 0` on the search header inside the
scrolling panel. A sticky child is clamped to its CONTAINING BLOCK, the
scroller's content box, while it is offset against the scrollport, the
padding box: with `p-1.5` on the scroller the header could never rise into
the top 6px, and rows scrolled up through it. Measured: panel top 394,
header top 401.

**Why it is easy to do.** Both are invisible in a screenshot of a closed
control, and the bleed needs more rows than fit before it exists at all.
Sticky reads as the one-line fix for a header that must stay put, and it is
correct everywhere except inside a box with padding, which is every panel in
this app.

**The rule.** The panel is `w-full` of the trigger's wrapper and carries
nothing else that touches width; a long label wraps (`break-words`, never
`truncate`, because the panel is no longer allowed to grow to fit it). The
search box is a `shrink-0` SIBLING of the rows, which are the only scroller,
inside a `flex flex-col overflow-hidden` panel - nothing sticks to anything.
Both are catalogue rules now: "A dropdown panel is exactly as wide as its
control" and "A filter box never scrolls with what it filters".

And the row that holds an open dropdown is the row that paints on top,
whichever way the panel opened. Cerebro's repo list gave every row `relative
z-20`, which is a TIE that the later sibling wins, so each panel was covered
by the row below it; ordering the rows top to bottom only moved the fault to
the last row, whose panel opens UPWARD into the row above. `focus-within:z-30`
on the row is the whole fix, with no state to keep, because the browser
already knows which row is being used.

**Grep.**
```
rg -n "w-max|max-w-\[min\(" templates/pm/components/select_dropdown.html
rg -n "sticky top-0" templates/pm
```
Any hit in the first is the width regression. The second: a filter box inside
the thing it filters.

### LM-6 - the merge kept the wrong row, and the seed that fixed it took the site down

**What happened.** The owner had two accounts for one person: `Mbean`,
which he had signed in with for as long as the board existed, and
`Michael.Bean`, which the `ADMIN_PASSWORD` seed had made and he had never
used. Asked to leave one, a migration kept `Michael.Bean` and deleted
`Mbean` - so the surviving account answered to a username he does not type
and a password he does not know, and he was locked out of his own board.
The repair renamed the survivor back to `Mbean`, which handed it the email
`michael@builtbybean.com`. The boot seed still asked only whether that
USERNAME existed. It did not, so every boot inserted a second row on an
email column that is unique, every gunicorn worker died on the
IntegrityError, and builtbybeans.com served 502 for nine minutes.

**Why it is easy to do.** A user row looks like a record to tidy, and the
merge reads correctly in every way except the one that matters: identity
is the username AND the credential together, and the migration moved
neither with the person. The test database made both faults invisible -
it has no seeded accounts and no email collision, so the migration passed
on data that could not reproduce production. And the second failure was
introduced BY the fix for the first, at the moment attention was on
getting the owner back in.

**The rule.** A migration that renames, merges or deletes a row somebody
signs in with carries their username and their password hash forward, or
it has locked them out; before writing it, name every row a human
authenticates as and say which survives and which credential it keeps. A
boot seed is idempotent on EVERY unique column, not the one it happens to
query: `username ILIKE x OR email ILIKE y` before any insert. The whole
seeding block is wrapped so nothing in it escapes the boot - a seed that
cannot run is a missing convenience, a seed that raises is a site that
will not start. And the way back in is built before it is needed:
`RECOVERY_USERNAME` with `RECOVERY_PASSWORD` on the service sets that
account's password on the next boot, says so in the log and is then
removed, and the login form takes an email as well as a username, so one
renamed account is never a closed door.

**Grep.**
```
rg -n "User\(" app.py
rg -n "username.ilike" app.py
```
Every seeding insert must be guarded by a query that ORs username with
email, and the block that holds them must sit inside its try.
