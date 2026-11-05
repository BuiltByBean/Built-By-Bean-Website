# Built By Bean - website + project manager

This repo serves builtbybeans.com and the live PM at `/admin`. Flask +
SQLAlchemy + Alembic, Jinja + Tailwind + Alpine, Postgres on Railway in
production, SQLite locally. Pushing to `main` deploys.

**Best Practices** (`/admin/practices`) is the CROSS-REPO lesson store:
when any project teaches a lesson, it goes there (pitfalls_md) as well as
here. It is one sidebar link over five tabs (`pm/practices/_tabs.html`):
Everything (one search across all of it, `pm/practices_routes.py`), Rules
(`/admin/features/rules`, `kind='rule'`: ways of building that hold no
matter what was bought), Features (`/admin/features`, what has been built
before, which is what the MVP Builder picks from), Playbooks, and History
(every change and the curator's nights, each with Revert). Every build prompt
carries the rules, so writing a lesson there is how every future project gets
it. This file is for lessons about THIS repo's own code.

**No money lives in Best Practices** (Michael, 2026-11-03: "no price shit left
over"). `Feature.typical_value` is gone, the guidance door takes no price and
hands none out, and the price list with its sell flow is the MVP Builder's
Price list tab. Vendor costs inside a playbook ("$99 a year") are facts
about the vendor and stay.

On 2026-11-02 the owner called the old Catalogue, five sidebar links and
Cerebro, "a good idea on paper, but it's not functional", and asked for one
place for everything he works on. The pages kept their URLs and endpoints
because the MVP Builder, project pages and the guidance API link into
them; what changed is that they read as one thing. My Apps stays its own
link: it is what was built, not how to build.

**Nothing waits on a yes** (Michael, the same day, looking at a Waiting tab
reading 188: "stop this waiting on a yes thing. Just have it adjust properly
over time ... add new, delete or prune ... based on my core projects'
repos"). Every change a session sends applies on arrival, rewrites and
retires included, and `curate_practices.py` runs last in the nightly
cost-sync job: Claude (Opus, `ANTHROPIC_API_KEY` on cost-sync, recorded as
a skipped night without it) turns the sweeper's notes into rules for any
project, folds them into the rule they belong to, or sets them aside; then
reads the whole rule list for merges, rules to tighten and rules to retire,
capped per night so it converges over days rather than rewriting everything
at once. Every change it makes goes through the door as project "curator",
so History shows it with a Revert, and a retire switches a rule off rather
than deleting it. `CuratorRun` is the night; `tools/test_curator.py` runs
one against a scripted model.

**The paid curator is off; Tend does the job on Michael's plan** (2026-11-04:
"could I just have it where I manually am able to run this off of my max plan
usage? that way it doesn't cost me any extra and later once im making more
money we can set it up automatic every night"). `curate_practices.curate`
does nothing and writes no night unless `CURATOR_ENABLED=1` is on cost-sync;
the free parts of the night (sweep, audit, store ids) still run. The nightly
bank suggestions were a second paid call nobody had named, and are off the
same way unless `BANK_SUGGEST_NIGHTLY=1`; Ask Claude on the Bank page still
spends on the press. The upkeep
is the Tend command, `.claude/skills/tend/SKILL.md` (`.gitignore` lets
`.claude/skills/` through so it travels with the repo), run in a Claude Code
session in this repo: fold the notes into rules and playbooks, prune the
rules, bring each blueprint up to date with its repos, bring each business
map in line with its blueprint, and file the Gaps each app has against the
others. Its half of the board is `tend_service.py` behind the door
(`/api/guidance/tend`, `/notes/<id>`, `/maps/<slug>`, `/gaps`, `/tend/runs`)
and six bridge tools. A map change is a `CatalogueProposal` of kind `map`
holding the whole map before it, so History reverts it exactly. `AppGap` is
one gap per (blueprint, key): Tend upserts, Michael closes as done or not
wanted, and a closed gap is never reopened by a run. History lists Tend runs
beside any paid ones, with the paid ones' approximate cost from their token
counts (`CuratorRun.estimated_cost`). `tools/test_tend.py`.

Applying a held note writes it as filed, and a replace is the whole field, so
`_overtaken` sets aside any held replace whose field has changed since it was
written. On 2026-11-04 twenty-two runbook rewrites from three days earlier were
queued, and sessions had filed lessons on those fields in between. They were
filed again from the live text, and tonight's run clears the old copies.

The catalogue had only ever grown: 485 rules, and the session-start brief
was 986KB. Claude Code keeps about ten thousand characters of a hook's
output and replaces the rest with a 2KB preview, so every session on the
machine had been starting with the first few rules while the hook said it
had briefed them. `/api/guidance/brief` is now the one-line index
(`rules_index`, held under `INDEX_BUDGET`), `?full=1` is every rule in full,
and the curator's target of about 120 rules is the size at which the index
carries every summary.

## Work from the issues board

Every piece of work here starts from a GitHub issue that you claim before the
first edit (Michael, 2026-11-05; catalogue rule "Work is tracked on the repo's
GitHub issues"). It keeps sessions running at the same time out of each other's
files, and the open issues are where a cold session finds out where things stand.

1. See what is taken and read each one's Where:
   `gh issue list -R BuiltByBean/Built-By-Bean-Website --label "in progress"`
2. Pick an open, unassigned issue (P1 first) or file one with the task, bug or
   decision form's headings, then claim it:
   `gh issue edit N -R BuiltByBean/Built-By-Bean-Website --add-assignee @me --add-label "in progress"`,
   plus a comment naming the session and its worktree. An earlier claim wins.
3. One issue, one session, one worktree:
   `git worktree add ../Built-By-Bean-Website-N -b N-short-slug origin/main`
4. Every commit says `Part of #N`. `Closes #N` goes only in the commit that
   ticks the last Done when box; never close with a box unticked.
5. Before stopping, tick what is true and comment what is left. Work you find
   and were not asked to do becomes an issue, not a side quest.

Labels: one type (`bug`, `feature`, `chore`, `docs`, `ops`, `decision`), one
priority (`P1`, `P2`, `P3`), and `in progress`, `blocked`, `needs decision`,
`needs human`, `triage` as they apply. `idea` issues come from the Ideas app
and are triage until written up.

## The MVP Builder

`pm/mvp_routes.py`, `/admin/mvp`. Michael, 2026-11-03: "when i get new client I
can easily grab features from those best practices in my mvp and spit out that
prompt". Type a new client's name or pick one, tap what they ask for, press Copy
build prompt. A second tap takes one back off.

**It holds no money** (2026-11-04). What a build costs is typed on the SOW form;
the package, its items, the prompt and "What they see" carry none.

**A feature is what a client would call it.** The list reads on a call and on
"What they see", and its names used to be lessons and poetry ("Close enough,
decided carefully", "Things that leave and come back"), with five entries for
e-signature. Now a short plain name and one sentence in the client's words, with
the lesson in its guidance. The bridge's `suggest_update` and the standing order
say so, because sessions are who add them. A way of building is a rule.

**The prompt has to fit.** It printed every rule in full until 2026-11-04, and
two items came out at 1,077,939 characters: nobody can hand that to a session.
Now it is the chosen features whole, rules in full for the areas they touch up
to `FULL_RULES_BUDGET`, every other rule as one line (`rules_index`,
`RULE_LINES_BUDGET`), and for a vendor what waits on the client, the access to
ask for and the checklist, with the runbook one get_playbook away (Twilio's is
46,000 characters). `/api/guidance/brief?full=1` is still every rule in full.
`REFERENCE_REPOS` says which GitHub repo a reference project is, because the
prompt named a Windows folder that no longer exists. `tools/test_mvp_prompt.py`.

**The price list is a tab of the builder** (Michael, 2026-11-04: Products folds
into the MVP Builder). `pm/mvp/_tabs.html` is the strip, Packages and Price list;
`mvp.price_list` (`/admin/mvp/price-list`) draws `pm/mvp/price_list.html` from
`products_routes.price_list_context`, and the presses on it (price, sell, erase a
sale) still post to the `products` blueprint and come back there.
`/admin/products/` redirects with its query string, because the Handbook's "Sell
it" is `?sell=<id>`. The SOW the builder opens carries `package_id`, so the
package is contracted when that SOW is signed. `tools/test_price_list.py`.

**A catalogue that grows needs a test on what it is assembled into.** Nothing
failed as the prompt grew from a page to a megabyte: every test read the features
and none measured the text. The number was only found by asking for it.

**Blueprints: a whole app to start from** (Michael, 2026-11-04: "if I'm
starting a brand new project ... it can basically look at a full end-to-end
app and how everything integrated into it ... we're not saying we're going to
copy this one-to-one ... and then we'll make that 10% tweaks"). A playbook is
one vendor; a blueprint is one app: what it is, its parts, how they talk, the
build order (each stage linking the playbooks and features it leans on), what
changes per project, and the traps that live between systems. The model is
`AppBlueprint` with `AppBlueprintStage` rows, because a Flask Blueprint is
already a thing in every route file; the screen says Blueprints, a tab of Best
Practices (`pm/app_blueprints_routes.py`). Shared logic is `app_blueprints.py`:
`normalise_stages` resolves each playbook and feature named by slug OR name and
REPORTS the ones that match nothing rather than storing a guess, because a
stage linking a runbook nobody wrote reads as covered; `blueprint_lines` is the
one text the door (`get_blueprint`, `/api/guidance/blueprints`) and the MVP
Builder share. Written only through the door (`suggest_update`, kind
`blueprint`, `stages` as its structured field like a playbook's `steps`), with
Revert in History. A package in the MVP Builder can "Start from" one, and its
prompt then opens with the whole plan before THE STACK. The first three,
2026-11-04, were read from the repos: EntertainHQ (Talent Booker is the same
product), Kuper Plumbing and Data Dungeon. Sessions write lists straight under
a line of prose, which the markdown renderer runs into one paragraph, so the
page puts the blank line in (`tidy_md`). `tools/test_blueprints.py`.

## The icon vocabulary

Michael, 2026-11-04: "give me an icon overhaul. and heck that is another thing
that should likely go into handbooks is icons that I like to use for concepts."
One drawing per concept (notifications, clients, delete, sign out), the same in
every project: the Handbook's Icons tab (`/admin/practices/icons`,
`pm/practices/icons.html`), each drawn at 20px on the sidebar's own ground,
plain and lit. Heroicons v2 outline, viewBox 0 0 24 24, stroke 1.5; under 18px
the same paths draw at stroke 2 so no line is thinner than a pixel, and that is
the only thing size changes.

- **Defaults in code, edits in the database.** `icon_defaults.py` is the
  vocabulary as harvested from his repos; `IconConcept` holds a concept once
  the door has changed it, written from its default on first touch
  (`icon_vocabulary.row_for`). A concept with no row draws its default. Never
  call `_target("icon", ...)` from a GET: it writes that row, which is why
  `target_label` reads icons through `icon_vocabulary.get`.
- **The board never draws an icon inline.** Every icon is
  `{{ icon('concept', 'w-4 h-4 ...', label=None, attrs='') }}`, a Jinja global
  (`pm/practices_routes.py`), cached per worker for 60 seconds and cleared on
  every apply and revert. `attrs` is markup the call site owns (an Alpine
  `:class`), dropped in verbatim, so never put data a user typed in it. A script
  that draws its own (the business map's surface tiles) takes the shapes from
  `icon_shapes([...])` and sets them with `x-html`. `icon_button`'s names are
  concepts too. `tools/test_icons.py` fails on any `<svg` in `templates/pm`
  outside the brand marks and the map's lines layer, and on an `icon()` naming
  a concept the vocabulary lacks.
- **The door** is `suggest_update` kind `icon` (fields `icon_vocabulary.FIELDS`;
  the slug is the concept) and `get_icons` in the bridge (`/api/guidance/icons`,
  `?concept=` by any word of its name or aliases). A drawing goes through
  `clean_svg`: shapes and geometry only, re-written from what parsed, another
  viewBox refused, because this markup is drawn on every page of the board.
  A drawing another live concept already has is refused: catalogue rule
  "One icon, one meaning" as a check, not a hope.
- **Every build prompt carries THE ICONS**, one line per concept
  (`prompt_lines`), after the rules.
- **Where the picks came from** (the harvest of 2026-11-04, notes in the
  session's harvest file): his own action sheet in EntertainHQ
  (`scripts/action_icons.py`, 2026-10-01) wins, so add is a circled plus, back
  an arrow, send a circled arrow, save and done a circled tick, filter the
  sliders, remove the circled x, and power is every switch off. Then whatever
  two repos already agree on (a receipt for expenses, the inbox for Workspace).
  Where they split he answered on the Icons tab the same day: support is
  EntertainHQ's bug, tasks wear the Workspace inbox because tasks live in the
  Workspace (an alias, not a second concept), the finances overview keeps the
  pie, and the 2x2 grid means Dashboard, so My Apps is a stack of windows.

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
assuming any session can file anything (`tools/bootstrap_guidance.sh` is the
Mac's, which adds the order between markers rather than overwriting the file; on
2026-11-03 this Mac had none of it either). Neither travels with a repo or
an account, so the MVP build prompt now carries the loop itself: it
tells the session to consult the live board and file what it learns as it
goes. If the tools are missing it reaches the same door over HTTPS, and failing
that builds from the snapshot and lists its lessons at the end. It told the
session to stop and name a script until 2026-11-04, which on a Mac without the
bridge halted every build on a terminal command for an owner who does not do
terminal work. The write path appends with attribution and refuses duplicates,
because reporting sessions retry like any other API client. A proposal's
text is kept whole up to `TEXT_MAX` (60,000) and refused past it, never cut:
appends grow a field without limit, and the old 6000 bound truncated a
replace in silence, so a rewrite of a grown field would have deleted its
tail while the record said it was in.

`/api/guidance/search` is what a session reaches before it builds, and it takes
words, not a phrase (`_search_stems`, `_search_rank`). It looked for the whole
query as one string until 2026-11-04, so "sign a contract" answered "nothing in
the catalogue" with e-signature right there, and that answer sends a session off
to build it blind. Most of the words have to be there, a name counts for more
than a body, and the best matches come whole up to `SEARCH_WHOLE`, because
"dropdown" handed back 76,917 bytes. The rest come by name, and searching a slug
brings that one back whole. `tools/test_guidance_search.py`.

The catalogue grows itself through the same door. Everything a session
sends becomes a `CatalogueProposal` (`pm/guidance_routes.py`, the
`suggest_update` tool) and applies on arrival: append, create, replace
and retire. History (`/admin/features/inbox`) lists each with a Revert.
`previous` is snapshotted at apply time so revert is exact. A held change
(`hold=True`, the sweeper's) is a `candidate`: a note for the curator,
never in a build prompt as it stands.
The Rules and Playbooks pages carry no add button on purpose: sessions
write those through the door, and a hand-typed one is never written
properly. Features keep their quick-add, because a client names one on
a call and it has to be caught in seconds.
Sessions may also file operational records - `upsert_project`,
`log_expense`, `log_time`, `register_hosting_resource`, `register_app`,
`retire_app` - and may NOT
contact a client, resolve a ticket or send a contract: those are
Michael's, and the API has no route for them on purpose. A playbook's
checklist goes through the same door: `steps` is a structured field on
kind playbook, a list in the payload rather than text. Append adds to
the end and replace rewrites the list, both on arrival, a create may
carry steps, and revert puts back the exact list that was there.

**`retire_app` is its other half** (`/api/guidance/apps/retire`, 2026-11-05).
Personal Trainer and Dom's Painting were deleted on Railway and their tiles
stayed, because only a signed-in press could take a tile off and nothing a
session could call did. By `url` (the tile's host), `name` (exactly) or
`railway_project` (the id), with a `reason`: the tiles go as the page's own
delete takes them (icon file too) with their site checks, the project's
hosting mappings are switched OFF rather than deleted so a billed month keeps
its split, and its `RailwayService` rows go. A board project is never
touched: it holds money and time. The answer is every removed tile whole,
enough to register it again. Two leaks closed beside it: the nightly site
check now drops a `SiteCheck` no tile or surface points at (a deleted tile's
"down" row would have stayed on Needs attention), and the Railway read skips a
project whose `deletedAt` is set, because Railway keeps a deleted project in
its answer for two days. `tools/test_retire_app.py`.

`register_app` keeps ONE card per app on My Apps: the same host edits the same
card, and so does the same project, whatever the address is this week. On
2026-09-10 two projects had two cards each, because a second registration
under the same project with a new name made a new card: Robinson & Co. on
its Railway address and again on its real domain, EntertainHQ on the apex
and again on app. The address rule (`better_address` in
`pm/guidance_routes.py`) is that a real domain beats a platform's temporary
one whichever came second, so a session re-registering the Railway address
never puts it back on a card that has a domain, and between two real
domains the apex beats the subdomain. Names are unescaped on the way in,
because one arrived as "Robinson &amp; Co." and was shown that way. The
migration that folded the pairs together keeps the oldest name, the real
domain, and every link and icon the others carried.

My Apps splits into Client work and Mine by the project a tile carries,
unless the tile says otherwise (`AppLink.board_group`, "Shows under" on the
edit form). The two came apart on 2026-11-01: Robinson & Co., Christ
Community Church, Lets Cook and Piped have projects and are not current
client work, and Data Dungeon has no client and is. Never move a tile by
detaching its project: the project page lists its app, and `register_app`
re-attaches the project on the next call. `tools/test_app_groups.py`.

On 2026-11-04 the halves were renamed for what they mean to him: "the top
section is products that make me money. bottom section is my personal
projects." The screen says Makes money and Personal projects
(`apps_routes.GROUP_LABELS`); the stored values stay `client` and `mine`, so
no row moved. Each tile has a drag edge down its left side, the whole height
of the tile (his pick, from a screenshot of another app: "I prefer a drag edge
like this"). It drags a tile to ANY place, in its own half or the other
(2026-11-05: "move it up a row into the middle to where everything shifts";
until then it only knew which half it was dropped in and re-filed the tile by
id). While carried, the tile is fixed to the pointer, a dashed gap stands
where it will land, and the other tiles slide there (first, last, invert,
play); the place under the pointer is hit-tested against where each tile WILL
sit, measured with its slide taken off, never with elementFromPoint, which
would catch a tile mid-slide and send the gap back and forth. Letting go
fills the gap and one POST to `apps.order` saves that half's order
(`AppLink.position`, drawn position first, then id) and writes `board_group`
only on the tile that crossed, so the rest keep following their projects. A
tap on the edge moves nothing, so a stray thumb cannot move a tile; Enter
sends it to the other half and the arrows move it one place, for the
keyboard. `tools/test_apps_drag_browser.py` drags with a mouse at 1600 and a
real touch at 375 and reloads after each drop. It is pointer events on the edge with `touch-action: none`, because
HTML5 drag and drop does nothing on a phone; the empty half is drawn only
while dragging, as somewhere to drop; the drop target is read at release, not
from the last frame, so a quick flick lands; and the edge auto-scroll runs on
a timer, because a finger held still sends no moves and animation frames do
not run in a throttled tab (they never fired in the preview pane at all).

A phone app's tile also carries its two store ids (`app_store_bundle_id`,
`play_package`; `register_app` takes them as `app_store_bundle_id` /
`play_package`, or `bundle_id` / `package`) and the last answer each PUBLIC
store page gave for the live version (`store_versions_service`: Apple's
lookup endpoint by bundle id, the Play listing page's data blob by package;
no store credentials on purpose, so an app in review reads "not live" until
the store publishes it). The board asks again when the answer is older than
six hours, on the way into `/admin/apps`, and the tile says "Versions match"
or "Versions differ" - the whole point, asked for 2026-11-01: one product,
one version on both stores. A store that errors keeps its previous answer;
the Play parse is a regex on the page's About blob
(`[[["1.2.3"]],[[[<targetSdk>]],[[[<minSdk>,`), so when Play changes its
markup the tile reads "unreachable" rather than wrong. It shipped reading
`]]],"1.2.3",null,` instead, which is the end of every REVIEW and carries the
version that reviewer had installed: Firefox read 135.0.1 against a live
159.0, and an app with no reviews (every app on its launch day) matched
nothing and would have stayed "not live". A listing with per-device builds
has no single version and reads "varies by device", which never counts as a
difference. `tools/test_store_versions.py`, and `--live` reads Firefox's real
page.

**The ids come out of the repo** (Michael, 2026-11-04: EntertainHQ's tile
said App Store live and nothing about Play, which he had submitted to, "I
need every ... thing automated"). A tile only asks a store whose id it holds,
and the Play id had never been typed. `store_ids_service.py` reads them
nightly, with no model, off GitHub for every tile with a `github_url`: the
Android `applicationId`, the Xcode bundle id (the shortest, so not a test or
extension target), an Expo `app.json`, or a Capacitor `appId` for a platform
whose folder the repo has. It fills only an empty field; a typed id is never
overruled. `tools/test_store_ids.py --repo <clone>` parses a real repo.

## What is live, watched nightly

Audit items 7, 9, 10, 18, 19, 20 and 4's store half (`docs/automation_gaps.md`),
2026-11-04. All of it runs from `live_night.steps(night)`, one line in
`sync_costs._sweep` after the receipts, each part its own recorded step.

- **Railway reads itself** (`railway_watch.py`). One GraphQL query per workspace
  with the account token (`PM_RAILWAY_ACCOUNT_TOKEN`, through `railway_token`):
  `serviceInstances { source { repo image } domains { serviceDomains customDomains }
  latestDeployment { status meta } }`. `meta` carries `commitHash`, `branch` and
  `serviceManifest.deploy` (`healthcheckPath`, `preDeployCommand`); a custom domain
  can be a wildcard (`*.entertainhq.com`), which is a routing rule and is dropped.
  `RailwayService` is one row per service per environment. A `ServiceMapping` is
  written only when a Railway project points at exactly ONE board project (by
  `Project.repo`, or by a tile it serves), and only where none exists or the one
  that does names no project; a tile's `railway_url` and `github_url` only into an
  empty field from exactly one production service. Two candidates is a guess.
  "Live on Railway, not on My Apps" is `/admin/apps/railway`, one row on Needs
  attention, with a one-press "Put it on My Apps" and a "Not an app" that sticks
  (`RailwayService.ignored`). Template databases (no repo, a template image) and
  crons with no address are never listed. A service the workspace no longer has
  comes off (`prune`, 2026-11-05): `store` only ever upserted, so Personal Trainer
  and Dom's Painting, deleted on Railway that day, would have read "live, not on My
  Apps" for good. Only after a read that answered, and never when the answer is
  empty or lacks more than half the workspace's services: that is a bad read, and
  the night's step says what it held back.
- **Hosting** has a **Not mapped** band: a priced project with no cost and no
  active mapping read "Fine" and sat out of the badge. It counts now and offers the
  mapping form with the project chosen. `_status(fee, cost, mapped=True)`.
- **Billed against agreed** (`hosting_billing.py`). Per client, its priced
  projects' monthly fees against its Stripe hosting items as a month (a product or
  nickname saying "hosting", `HOSTING_LINE`). Unbilled and different both count in
  the badge, once per client on its first row. A different single item gets one
  press that asks first (`confirm_button`) and moves the item to the agreed fee
  from the next cycle, no proration. **The badge never waits on Stripe**:
  `snapshot()` answers from the last read and refreshes in a thread; only the page
  reads synchronously. **One reading, two places**: `hosting_rows()` is the page's
  rows and the badge's count, and the page leaves its count in `_DUE_CACHE`, so a
  fresh Stripe answer on the page and an older one in the badge cannot disagree.
  The bill press is a live action inside `data-live` regions, as are the Railway
  list's presses: the row changes where it stands and the page does not move.
  `tools/test_hosting_billing.py`.
- **Sites, certificates, domains** (`live_watch.py`). Every tile URL and map
  surface URL is fetched nightly (`SiteCheck`): under 400, or 401/403, is up.
  `fail_nights` counts nights in a row; two is a row. Domains (`DomainWatch`) come
  from Cloudflare's registrar (expiry and auto-renew) or public RDAP (expiry only,
  so "held outside Cloudflare" counts as not renewing). `attention_rows()` reads
  the database only, cached five minutes, and its links never need a request
  (`_url`): a `url_for` outside one raised inside the try and every row vanished.
- **Store versions** refresh nightly (`refresh_all`), and `store_differ_since`
  makes a difference older than a day a row. The repo's own version
  (`versions_from_files`: `versionName`, `MARKETING_VERSION`, `expo.version`) is
  read every night into `AppLink.repo_versions`, and the tile says "1.4.0 in the
  repo, stores on 1.3.2".
- **Tiles** (`tile_upkeep.py`): an empty description fills from the repo, else the
  site's meta description; a fetched icon is fetched again monthly, an uploaded
  one (`icon_file` with no `icon_source`) never.
- **Railway bills from mail** (`railway_mail.py`): a tokenless Railway account's
  month is recorded from the receipt mailbox of the business that pays for it,
  noted "From mail"; the month is the receipt's date less a month. A typed or
  pulled row is never touched.
- **The map notices** (`map_checks.py`). A playbook carries a presence signature
  now (`Playbook.presence_*`, the Product mechanism reused, proven on its fixture,
  seeded for 21 vendors and writable through the door). A vendor in a business's
  blueprint repos, or on its books in the last year, with no service node, is a
  gap on its blueprint (`filed_by` "nightly map check"); so is a service quiet for
  90 days that has charged before. A closed gap stays closed and one whose cause
  went is closed as done. A production custom domain not on the map becomes a
  surface once, its memory a closed gap, so a deleted node is not put back. A
  surface's status follows its site check (`down` reads Unreachable); Building and
  Planned are left alone.
- **Steps tick themselves** (`step_checks.py`). `PlaybookStep.check_kind` is repo
  (globs and a regex, the audit's scanner), railway (one of `RAILWAY_FACTS`, read
  from the mapped project's services) or http (a path on the project's site). A
  pass ticks the step with why in an empty note; nothing is ever unticked. The door
  takes `check_kind`, `check_target`, `check_pattern` on a step and refuses one
  that cannot run. Five Railway checklist steps carry checks from the migration.

`tools/test_live_apps.py`, `tools/test_hosting_billing.py`,
`tools/test_map_and_step_checks.py`.

## The Workspace

Michael, 2026-11-04: "I have a notes section. I want to replace that and
integrate the workspace feature from Entertain HQ into that, where we have the
messages, task, and projects. And so then the projects page that we have
standalone right now will get folded into that workspace thing ... I want that
to be the second tab under needs attention." `pm/workspace_routes.py`,
`/admin/workspace`, templates in `pm/workspace/`. EntertainHQ's shape, cut to a
board with two people on it, his pick on every question:

- **Messages** is team chat between logins (him, Hannah, anyone added), direct
  or group, and a message links to anything on the board (project, client,
  task, ticket, contract, lead, business for the CEO). No email, no text; client
  mail stays on Needs attention. The models are `Team*`, never `Message`, which
  is the client mail. A pair has ONE conversation by `pair_key` ("3:7", unique);
  a conversation opens only to its people, a 404 on every door otherwise. A send
  appends the rows since the last one on screen, the poll answers 204 when
  nothing is new, and the list polls and swaps only when it differs.
- **Tasks** replaced Notes. Migration `a5d17c3e92b4` carried every note across
  with its id, open ones to Backlog and done ones to Done, given to Michael and
  already seen, and dropped `notes`; its downgrade puts every one back. Backlog,
  In progress, Done with a pointer drag from the grip only (a thumb scrolling
  never picks a card up), one JSON post per drop, the card put back if it fails.
  The board opens on yours; Everyone shows the rest.
- **Projects** are the client projects, not a new kind. The tab is cards; the
  project page kept everything and gained its task board and the messages about
  it under a Tasks / Playbooks / Messages switch, with tiles that open Client
  support, Time and Expenses filtered to it. `pm.project_detail`, `project_edit`
  and `project_create` kept their endpoint names and moved under
  `/admin/workspace/projects`, so every `url_for` across the board still lands;
  `/admin/projects...` and `/admin/notes` redirect.
- **The counts are what is NEW**: unread messages and tasks given to you that
  the board has not shown you, never the standing backlog. The board's render
  is what marks a task seen. The sidebar badge is their sum (`workspace_new`).

The tab row is `data-keep`: `bbbNavigate` (base.html) carries an element marked
`data-keep` across a page swap when the next page has one too, and tells it what
the new one said through `bbb:kept`, so moving between tabs never redraws the
row and its mark slides. The conversation list is kept the same way between
chats. The page's scripts are inline functions (`pm/workspace/_js.html`) on
purpose: a swapped-in inline script runs before Alpine reaches the new markup,
a script by `src` loads after it. `tools/test_workspace.py`, which runs every
request as its own login (`As`): inside one app context Flask-Login's user is
cached on `g`, and every client would otherwise be whoever asked first.

**A project has a kind** (Michael, the same evening: "EntertainHQ, Ideas, Piped
those are my products they wouldnt even follow the same phases", "Lets Cook
doesnt even belong on this page"). `Project.kind` is client, product or
personal; NULL follows the client (`kind_effective`: his own client row, by
address or by a CEO's name, means product). Only a client build walks the client
phases, is moved by dates (`sync_project_phases`, `project_autofill`), bills
hours or has a free maintenance window. A product walks `PRODUCT_STAGES` (Idea,
Building, Beta, Live, his pick), set by a press on its page, in `Project.stage`.
The Projects tab's Work view is Client builds then My products; Personal and
Archived are views of their own. A card wears its My Apps tile's icon, and a
project with no tile finds its one unattached tile by repo, name or domain
(`project_autofill.tile_for`), which the night then attaches without moving the
tile's half of My Apps. Migration `d3b8f6a2c915` folded Workforce into Talent
Booker ("workforce was never ever its own project it was a feature added to
talent booker"): both are Kenali's, so everything on it moved, money included,
and no client's figures changed. A checklist Talent Booker already had takes the
ticks it lacked; a second My Apps tile is let go rather than doubled. Workforce
is deleted, and `ProjectFold` keeps its row and every id and row touched, so the
downgrade puts it all back. The deploy log says what moved.

**A tab press swaps the panel, not the page.** Keeping the tab row was not
enough: every press still rebuilt the banner and `#pm-main`, whose entry
animation played again. Pages of one group wrap what changes in
`data-panel="<group>"`; `bbbNavigate` replaces only the innermost panel both
pages share (a chat is a panel inside the Messages tab, so another chat leaves
the list), a banner piece only when it reads differently, and `#pm-main`'s
classes in place. Every in-page choice is the `seg` kit (`pm/workspace/_tabs.html`,
`wsSeg`): one sliding mark, its own state, never inside a swapped region.
`tools/test_workspace_tabs.py` stamps all of it and presses every tab and
switch at 1600 and 375; it fails on the old swap.

**A project's dates come from its repo and its domain** (audit item 11,
`project_autofill.py`, the "project dates" step of the night, before the store
ids). The repo pair (`Project.repo`, the tile's `github_url`) fills whichever is
empty from the other, then from a repo whose `homepage` is the tile's host.
Contracted moves to MVP on the first commit after the contract (the earliest
signed contract on the project, else the day it was put on the board), and
`build_started_on` is that commit's day: GitHub lists newest first, so with one
per page the Link header's last page is the oldest. Go-live is FILLED, not
proposed (his pick), the first night the project's real domain answers, for a
project in MVP or Delivered; a platform address never counts, and
`go_live_source` says where the date came from on the project page. Only empty
fields, never past `phase_locked`, never an archived project.

## Needs attention

`pm/attention_routes.py` is the mail waiting on a reply, and last month's
vendor invoice. Nothing else.
It carried seven signals once - declined contracts, hosting fees under the
floor, overdue invoices, catalogue rewrites, untriaged tickets, late
builds and mail - and six of them already had a home on the page that owns
the work, which made this a page to skim rather than clear. Mail was the
only one with nowhere else to be answered. Hosting still reads its own
sidebar badge out of `attention_counts()`, so that dict keeps a `hosting`
key that is not a row on the page; `total` is the mail alone.

A row opens on press and shows the whole message, one at a time, the same
shape the leads page uses: the summary is the press target, a chevron says so,
and the snippet gives way to the body rather than repeating its first hundred
characters above it. The body is capped and scrolls inside itself, because one
long mail would otherwise push every other row off the page it exists to
clear. `openId` lives on the card OUTSIDE `data-live`, or a Dismiss would swap
the region and close the row somebody was reading.

Each row carries Reply and Dismiss. Dismiss is `messages.archive`, which
archives the inbound thread AND the row pressed - it matched the thread
alone once, so a message with no `thread_id` was left untouched while the
flash still said "Archived." A press that reports success has to have
acted on the thing that was pressed.

The second signal is a vendor bill that has not been recorded. It earns the
place on the same test the mail does: only Michael can do it, and there is
nowhere else it would be noticed. `ProviderInvoice` is one row per provider
per month, typed off the bill on the same monthly page the per-project usage
goes into, and the row links straight to the month it is asking about. Only
finished months are asked for, and only for a provider this board already
tracks money for.

The lifetime Railway figure used to be assembled by summing every expense
whose description began with the provider's name. A flat monthly charge and
the sync's per-project rows both match that, so a month holding both was
counted twice: the page read $231.65 against $136.90 of real invoices, and a
single month reproduced at $71.30. The invoice is the truth about what a
month cost; per-project usage is the truth about how to split it. The tile
says which of the two it is showing, because a derived number in the same
type as a recorded one is a guess wearing a fact's clothes. Catalogue rule
"A total somebody is billed for is recorded, not pattern matched".

His own address is never a row. He has a Client row of his own and
`watched_senders` reads every client email, so his mail was syncing as client
mail; taking him off the client list would not have held either, because that
function re-adds any address that has ever written in.
`mail_service.own_addresses` is one answer used twice, subtracted from the
sync and filtered on this page, because the sync only ever inserts and rows
already written stay written.

A dismissal holds across a sync because `mail_service.ingest` only ever
inserts. It hung entirely on the Message-ID header though, with the check
SKIPPED when that header was absent, and the IMAP search reaches two days
behind the newest row - so a mail with no Message-ID was re-inserted every
five minutes as a NEW row with a new id and a new status, and archiving it
did nothing anybody could see. Mail without that header now gets a
fingerprint of its sender, date and subject.

**The nightly job keeps a record** (`night_log.py`, `NightRun`, 2026-11-04).
Every step of cost-sync runs through `Night.step`, which records its summary or
its error and moves on, and the invoice import no longer returns early with the
vendors when none is active. Needs attention carries ONE row when the newest
night has a failed step or no night has finished in 26 hours; it links to
`/admin/attention/nights`. A new nightly step goes through `night.step(...)` in
`sync_costs._sweep`, never a bare try/print. `tools/test_night_log.py`.

**The sidebar is Michael's groups** (2026-11-04, second pass), divided by rules
with no headings: Needs attention and the Workspace; then Businesses, My Apps,
Client support and Org (Team, renamed, once its session lands); then Clients,
Contracts and Leads; then the Handbook (Best Practices in the code and URLs),
the MVP Builder and Time; then Finances, for the CEO alone: Books, Taxes,
Invoicing, Hosting (Michael retired the Overview into Books the evening it
shipped). Notes and Projects left when the
Workspace landed, and Products folded into the MVP Builder.

## Finances, consolidated

`docs/finances_plan.md` is Michael's decision on every item (2026-11-04: "the
finances section as a whole could use some better processes top to bottom").
Six pages computed the same figures in up to four places over different
periods. Now:

- **Every Finances page is CEO only** (`ceo_required` on every route, GET and
  POST; the sidebar section is not drawn for anybody else). A refusal lands on
  `/admin` (`admin_hub`), never on a money page: `ceo_required` sent a refused
  login to the Dashboard, which would have refused it again for ever.
  Login, the error pages and the contract fallback land there too.
- **One tab kit** (`templates/pm/finances/_kit.html`): `fin_tabs` is the row on
  every money page, kept across a press (`data-keep`) and told what the new page
  said, so its links and counts follow the page that arrived (a company switch
  changes every sub-tab's address); it scrolls sideways on a phone with the
  current tab brought into the row by its own scrollLeft. What changes sits in
  one `data-panel`, so a press swaps only that.
- **Books is the front door; the Dashboard is retired.** An Overview replaced
  the Dashboard for a few hours on 2026-11-04, then Michael: "Dashboard (retire
  move books into this spot)". `pm.dashboard` (`/admin/finances`) now 301s to
  the company's Books, keeping `business` and `year`. The top of each company's
  Months tab is what the Overview held: Income, Expenses and Net from
  `books_service.summarize`, the estimated tax from `income_tax.estimate`
  (`books_routes.estimated_tax`), and one To do list (`books_routes.todo`),
  each row a link to where it is cleared (overdue and stalled invoices, bank
  lines to sort, missing receipts, vendor bills not recorded, hosting fees
  under the floor; not the months, which are listed right below it). A GET
  changes nothing; the Dashboard ran `sync_project_phases`. Financials by client
  went to the Clients list (Paid, Open, Spent on; CEO only, `_client_money`),
  ticket and delivery dates to Client support (`_support_deadlines`).
- **Books is each company's one place for its money** (`pm/books_routes.py`,
  `templates/pm/books/_hub.html`): a row of companies, then Months, Bank,
  Expenses, Receipts, Year report, Connections, each `/admin/books/<id>/...`.
  A DBA's address opens its company. Bank is the review list moved in from
  `/admin/bank/`, scoped to the company, with Tagged beside it; Expenses is the
  ledger moved in from `/admin/expenses`; Connections gathers the company's
  Mercury, its own Stripe, its statement cards, its receipt mailboxes and its
  vendor reports (the business page only links there now). Adding an expense
  by hand stays, inside Books, with a company picker (`pm.expense_create`); a
  row a bank line booked shows its amount and date and does not take them,
  and cannot be deleted (settle the line instead). The "Ask Claude" press went
  with the old review page: nothing on the server calls a paid model.
- Every old address lands (301): `/admin/expenses` with its filters,
  `/admin/bank/`, `/admin/books/?tab=...`, `/admin/books/receipts`. The
  endpoints kept their names. `tools/test_finances_books.py`,
  `tools/test_finances_browser.py` (320, 375 and 1600, with a planted fault it
  must catch).
- **Taxes** is five tabs on every tax page (`templates/pm/taxes/_tabs.html`):
  Income tax, Sales tax, Returns, Deadlines, Guide. `income_tax.estimate` is the
  one income-tax figure for Taxes and the top of Books: the Books net per company,
  Built by Bean on Schedule C, EntertainHQ as a partnership with each member's
  share and no self-employment tax at the company, Schedule C companies stacked
  before partnership shares so they add up to his whole return, and the set
  aside on the same basis. `tools/test_taxes_tabs.py`.
- **Invoicing** (`pm/stripe_routes.py`, Invoices until Michael renamed it): the list, New invoice, a one-line Stripe
  strip ("open in Stripe" is the whole account; "Unpaid in this list" follows
  every filter, status included, so the two Outstandings no longer share a
  name), and Time not yet billed (`unbilled_time`, per client, its tab counts
  its rows, each row starting an invoice with that client's time ticked). New
  invoice shows the time step whatever `FEATURE_TIME_TRACKING` says. Setup
  Products and Sync All Clients are gone (their old POSTs answer a 303 to the
  list and make nothing); `/admin/stripe/` answers a 301. CEO only except the
  webhook. `tools/test_invoices_page.py`.
- **Hosting** is four tabs (`templates/pm/hosting/_tabs.html`): Fees, Mappings,
  Railway months (`service_costs.railway_months`; `provider_monthly` for a
  Railway account sends there) and Vendors. `provider_bills.missing_bills` is
  the one missing-bill list: Needs attention, the tab's count and its page read
  it, and `months_missing_manual_costs` is gone. `/admin/service-costs/`
  answers a 301 to Hosting. A save inside a tab does not refresh the tab row's
  counts until the next navigation. `tools/test_hosting_tabs.py`.

**Only the bank line makes an expense** (item 5). Until 2026-11-04 a vendor
sync (Railway, Cloudflare, Claude, AWS) wrote an Expense per cost entry and the
bank line was "covered". Now `service_costs_service.writes_expenses` is true for
Stripe alone (its fees never cross a bank: the Stripe balance is the account),
and the bank line books the charge, split by the vendor's report:
`bank_feed.split_shares` finds one row for the amount, one period's rows adding
up to it, or one period several charges pay between them (Railway's March 2026,
$9.75 and $5.00), and `bank_feed.split` writes one Expense per share
(`Expense.bank_line_id`, `Expense.cost_entry_id`), the shares adding up to the
charge to the cent. A report that lands after its charge splits it again
(`resplit`: after every vendor sync and in the nightly bank read, 75 days back),
and only the split moves, never the total. An expense the old sync wrote for a
period before `SPLIT_FROM` (2026-12-01) is still corrected in place until its
line takes it over, keeping its date, so a month already read does not move.
A charge whose report beside it does not explain it still goes to review or to
the twin company, as before.

The migration `f2a7c9d41e63` carried the old rows over with
`finance_carryover.py`, which is also the read-only dry run behind the door
(`/api/guidance/books/carryover`), so the session could check production's
figures it could not read directly. It refuses to run if any company's yearly
total would move for a reason other than a double count or one of Michael's
`DECISIONS`. On production: 18 covered lines took their vendor rows as shares
unchanged, 92 vendor-written expenses carried over, March shared between its
two charges, no double count found, and the $10.66 Claude charge of 2026-10-17
that nothing had booked went to EntertainHQ (Michael's answer). Built by Bean's
2026 stayed $3,016.95; EntertainHQ's moved $668.15 to $678.81.
`tools/test_only_bank_books.py`.

**A session's `log_expense` is a tag** (item 8, `ExpenseTag`). It makes no
expense; the bank line for that charge takes it (same amount to the cent,
within ten days, `bank_feed.take_tag`) and its expense lands on the client and
project named. One logged after its line is put on it at once (`apply_tag`).
One no line took in ten days is a Needs attention row (`books_upkeep.waiting_tags`),
listed under Books, Bank, Tagged, where Set aside takes it off.

**Recurring expenses retired** (item 6): the toggle and the generator went,
every parent ended in the migration, and every past row stays. A bank rule
catches what they caught.

## The books stand on the bank

Michael, 2026-11-03: "I use an unbelievable amount of services ... I need my
expense tracking automated to like the highest degree ... broken out
specifically by business as well, so that way I'm not accidentally double
counting." Of the 35 playbooks, only Railway, AWS and Google Cloud report
money through an API; Sentry, Resend, Postmark, Claude's own subscription,
Apple's $99, LegalZoom and Cloudflare's renewals report nothing, and the
prepaid ones (Twilio, the Anthropic and OpenAI APIs) report usage while the
money left on a top-up. Every dollar leaves a bank, so the bank is the
record: `bank_feed.py`, one `BankTransaction` per money movement, and that
line is the ONLY thing allowed to make an expense. A vendor's own report is
evidence and a way to split money across projects, never a second expense.

`Expense.business_id` is whose books, filled in for every path by a
`before_insert` listener (the business the board bills from, or a recurring
child's parent's), and a company's books include its DBAs'. A
`BankConnection` is one business's Mercury token, read only, typed on that
business's page by its owner and never shown again; Mercury tokens open one
organisation, so the connection's business is the attribution. Nightly, after
the vendor syncs (`sync_costs._sweep`), every line since `synced_from` (April
2026) is upserted on Mercury's id and the last ten days are read again,
because a pending charge changes amount when it settles.

What a line is (`classify`): void (cancelled, its expense removed), transfer
(Mercury's internal kinds, or a rule), expense (booked only once SETTLED,
Mercury's own fees without a rule, a vendor refund as a negative expense),
split (an expense split across projects by the vendor's own report:
Railway, Cloudflare, Claude, only in Built by Bean's books, because those
reports read only Built by Bean's accounts; it was "covered" until
2026-11-04, see "Finances, consolidated"), income, personal, or review.
`VendorRule` is what a counterparty is, longest pattern wins, written when a
line is settled with "remember" on, and settling one settles every waiting
line like it. Each company's Bank tab in Books is the review list with the
board's own suggestion filled in and one press to accept them all.

`adopt` is the guard against the commonest double count: an expense somebody
already booked for the same charge (the expense form, or a session's
`log_expense` until it became a tag) is ADOPTED by the bank line, not
written twice: same company, same amount to the cent, dated up to seven days
before the bank's date or three after, not standing for another line and not
written by a vendor sync. `tools/test_bank_feed.py`.

## The books

`/admin/books/<id>/` (`pm/books_routes.py`, figures from `books_service.py`) is
each company's books, the board being the books (Michael has no bookkeeping
software and no plans for any). Every reading is one function,
`books_service.summarize`, so the year-end report, the monthly close and the
hub cannot disagree.

- **Income** is cash basis: for the company the board bills from, paid
  invoices less their sales tax and their refunds, and nothing from a catch-up
  invoice (the dashboard's reading); for a company on its own app, the sales
  the app sends; otherwise its bank's money in.
- **Expenses** are the company's and its DBAs' Expense rows, grouped by
  `TAX_LINES` into the lines a return asks for. Schedule C line numbers are
  shown only for a single-owner company.
- **Owner money** is bank lines settled as `contribution` / `draw`, per
  owner. `BusinessOwner` holds the shares, typed from the company's paperwork:
  Built by Bean is Michael's alone, EntertainHQ has three members and files a
  partnership return, so its accountant needs each member's figures. Money in
  from Chase is Michael putting his own money in (the CHASE rule), never
  income.
- **The monthly close** (`MonthClose`) closes only a finished month and keeps
  the totals it closed on, so a later change shows as a difference. Its checks
  are bank lines unsorted, expenses without a receipt, and each Mercury
  account's balance against the sum of every settled line read for it
  (`balances_json`, read with the accounts).
- **Receipts** (`receipts_service.py`, nightly after the bank feed) are read
  from every `ReceiptMailbox` over IMAP, read only, with an app password typed
  on the Books page. Only subjects that read as a receipt, never a renewal
  notice. The amount is the last line that says total or paid, as a whole word
  (Subtotal is not Total), from the PDF and from both the plain and HTML
  parts, because a plain part is often a one-line fallback. A receipt attaches
  to an expense without one for the same amount to the cent, dated three days
  before to ten after. One that matches nothing waits, and `rematch` retries it
  every night.
- **`/api/hub/books`** is the same figures for a company's own app, signed
  with its hub secret. EntertainHQ's admin shows its partners these numbers
  read only, so there is one set of books and never two. The app may send its
  own sales as the income.

`tools/test_books.py`.

**An expense goes and finds its own receipt** (Michael, 2026-11-03: "getting
receipts for the expenses on the books right now, and a way to automate getting
those receipts going forward"). The sweep above starts from the mail, and 31
expenses sat on Missing while their receipts were in the mailbox, for three
reasons: Gmail's search matches whole words, so `subject:charged` never returned
Twilio's "recharged" and the code's own substring test never saw it; Twilio writes
"we charged the card $10.03 to bring the balance to $20.00" and the read took the
last figure on the line (`_without_balances` now takes balances and renewal prices
out first); and a vendor's month is dated its last day, weeks from its bill.

`receipts_service.hunt` starts from the expense instead: for each one without a
receipt, this year and last, it asks the mailbox for that exact amount around that
date, whatever the subject. It takes a message only when the sender or subject
names the vendor (`vendor_names`, `SIGNED_AS` for Claude and ChatGPT, whose mail is
signed Anthropic and OpenAI) and the amount is stated somewhere other than a
balance or a renewal, because a wrong receipt is worse than none. It stores only
mail it uses. It runs inside every mailbox read, so nightly, on Read now, and as
soon as a statement is uploaded.

Oldest first on purpose: of two rows for one charge, the earlier takes the receipt
and the other stays on Missing, and that is how a charge booked twice shows itself.
One message proves one row, and only for what it gives as charged
(`charged_amounts`). A line inside a bill is not a charge: Railway's $60.70 invoice
lists a $20.00 plan and takes $20.00 of included usage off, so $40.70 left the bank.
The first version accepted the line, which attached that invoice to a hand-typed
$20 row and made a duplicate look real. A vendor's month split across rows is the
sweep's to attach, and only when the rows add up to the bill. The sweep no longer
attaches a receipt to a charge that does not name its vendor: Railway's April
invoice, which mentions $20.00, sat on a $20 Twilio row for seven months.

**What a vendor report holds is checked, not assumed** (`bank_feed.booked_by_sync`).
A `covered` rule (now `split`) used to mean any charge from that vendor was already booked. A sync
reads one account, and EntertainHQ's own Claude plan and Railway workspace are on
the same card under the same names, so $261.57 of its real charges sat marked as
booked by a sync that had never heard of them. A charge now counts as covered only
if the sync has it, as one row or as a period's rows adding up. If it does not, it
goes to the company a twin provider or that company's own mailbox says it belongs
to (`other_company_for`), and to review when nothing says, because a guess there
moves money between companies. With nothing from the sync in that window the rule
stands, or a new month would turn every charge into a review.

**A correction leaves a record.** Reviewing receipts on 2026-11-03 found $261.27 of
Built by Bean's expenses entered by hand on top of a charge already booked, a personal
RuneScape subscription on the company's card, and the above. Michael approved each
one, and migration `c3e7a1f90b42` applied them. `ExpenseCorrection` keeps every row
removed, whole, with the reason, and the downgrade puts it back to the cent. Its ids
are production's and each is matched with its amount and words too, so on any other
database it does nothing.

Where no document exists anywhere (a restaurant on a card, a bank's own fee),
`attach_statement_lines` gives a charge under $75, a month old, with a bank line
behind it, a PDF of that line. It is named `STATEMENT_PROOF`, has its own tab
("Statement only") because a stand-in in the same list as a receipt is a guess
wearing a fact's clothes, and a real receipt turning up later replaces it and
removes the file. From $75 up it stays on Missing. Mail that has matched nothing for
45 days is set aside (`set_aside_old_unmatched`), because most of what the sweep
keeps is a mortgage notice or a car payment; the hunt can still use it. That one is
a loop over rows and not `Query.update`: the bulk update left SQLite locked for the
commit after it, on a thread beside a page. `tools/test_receipt_hunt.py`.

**One company, one set of figures** (Michael, 2026-11-03: "does my finances
every page settle with each from a numbers standpoint?"). They did not: the
finance dashboard summed every company's expenses, the Taxes page took
profit from Stripe's payouts (sales tax in, Stripe's fee already off and then
taken off again as the expense the Stripe sync books) less every company's
expenses, and the Books read the local invoice rows while the dashboard read
Stripe live, $5.97 apart. Three profits for one company. Now the dashboard
and Taxes read `books_service.board_business()` and `board_expense_total`,
the Books' board income reads Stripe live (local rows only when Stripe is not
configured), and the Expenses page's "everything" total is the companies'
books added together. `tools/test_one_set_of_figures.py` holds the pages to
the Books page's net, to the cent.

**Sales tax comes off once, and a refund is money that went back** (Michael,
2026-11-03: "the total paid is higher than my income, what gives?"). The gap
was $1,201.20 of sales tax and Books was right to leave it out, but reconciling
it to the cent found two faults underneath, in figures every money page reads.
Together they had the net $990.63 too low.

The first: income leaves sales tax out, and the two payments to the Comptroller
were also expenses, so the tax came off the profit twice. Of $1,193.22 paid,
$996.60 was tax, $169.87 penalties and interest, $26.75 card fees. Only the last
two cost anything. **`Expense.amount` is always the expense**, so every total in
the app is right without knowing any of this; `sales_tax_remitted` is the part
of the charge that was the state's money, and **`Expense.charged` is what left
the bank**. Only the code that matches a charge against something else reads
`charged`, because a bank line and a receipt both state the whole charge:
`adopt`, `book`, the receipt matching, `attach_filings`, and owner money, since
an owner who paid on their own card put in all of it, tax included.
`books_service.settle_sales_tax` is the one thing that writes the split. A
return and its charge can arrive in either order, so it runs where each lands:
recording a return, `bank_feed.fold_duplicates` (every path that brings a charge
in passes through it) and the nightly `rematch` (for one typed on the form).
Taking a return off the board puts the charge back whole
(`unsettle_sales_tax`). A charge has to name the state AND sit within a card fee
of what the return says was paid, so a franchise tax payment is never taken for
one.

Only the company the board bills from is split, because only its income is net
of tax. A company on its own Stripe or its own app counts sales gross, tax and
all, and there the payment to the state IS the deduction that takes the tax back
out. Each is right on its own; one company doing half of each is the fault
(`leaves_sales_tax_out_of_income`). It treats all the tax on a filed return as
passed through. Tax paid over and never collected, a catch-up a client never
pays, is really a cost and does not show as one; "Left to bill" on the sales tax
page is where that would be seen.

The second: Stripe leaves a refunded invoice "paid" with `amount_paid` untouched,
so three refunded $1.99 charges counted as income and as money in. The $5.97 gap
between Books and the dashboard that "One company, one set of figures" closed by
moving Books onto Stripe live was exactly those refunds: the local rows only left
them out because those invoices belong to no client and cannot be stored, and
closing the gap moved Books to the wrong number. `stripe_service._refunds_by_invoice`
reads them beside the invoices. On the API version the stripe library sends
(2026-10-28) a charge no longer says which invoice it paid, so the road from a
refund to its invoice is `stripe.InvoicePayment.list` on the payment intent, not
`charge.invoice`; `_invoice_of_refund` tries both. A refund only shows on
`post_payment_credit_notes_amount` if it went through a credit note, which one of
the three did and two did not. A refund gives back sales tax
in proportion (`earned_share`) and lands on the day it went back, so the sale and
the refund can sit in different months. `Invoice.amount_refunded` and
`Invoice.earned` are the same reading over the local rows. A sale refunded in
full owes no sales tax; a part refund stays whole on the return, erring towards
the state.

So Total Paid on the Invoices page is what stayed, and **Total Paid less the sales
tax shown under it is the Books page's income, to the cent**. The penalties and
interest stay in Taxes and licenses, and whether they can be deducted is a
question for the accountant, which is why the row, its edit page and the year's
CSV spell out the split (`Expense.sales_tax_note`). A return paid with no fee and
no penalty leaves a $0.00 row, which the expense form will not save
(`NumberRange(min=0.01)`); there is nothing on one to edit.
`tools/test_sales_tax_and_refunds.py`.

**A DBA's money in is the company's, under the DBA's name** (Michael,
2026-11-04, of the check deposits on Built by Bean's Chase checking: "that
income would count as built by beans income but show it specifically as kind
of a dba ... under personal training"). Personal Training is a DBA like Data
Dungeon (migration `e5c3a9b17d42`, which moved the CHECK_DEPOSIT income lines
onto it). `books_service.dba_income_between` reads bank lines settled as
income that a DBA of the board company holds, and only those: the company's
own money in is its invoices, already counted from Stripe, so a deposit it
holds itself never counts again. Books, Taxes, the dashboard's Total Revenue
and the Businesses tile all add it, the Books and the year report show
`income_sources`, and the accountant's CSV names the row "d/b/a".

**Income lives where the sale happens.** For a company with its own Stripe
(EntertainHQ), `stripe_books.py` reads every line of its Stripe balance
through a restricted key typed on the company's page (`Business.stripe_key`)
into `StripeActivity`. Income is sales gross on the day the customer paid,
less refunds, whether or not Stripe has paid them out yet; Stripe's fees are
one `bank_fees` Expense per month, corrected in place; and a Stripe payout
landing in any company's Mercury is a transfer (`bank_feed.is_stripe_payout`),
because the sale was already income on the day it was paid. It shipped first
counting EntertainHQ's Mercury deposits as its income, and Michael caught it
the same hour: "what if there's a bunch of money sitting in Stripe that we
haven't transferred over to our Mercury account?" A connected Stripe also
outranks any sales list an app sends. `tools/test_stripe_books.py`.

**Cards with no feed come in as statements** (`statements.py`, Books page,
Card statements). Michael's history since April is on Built by Bean's Chase
debit, his personal debit and his personal credit card. A `BankConnection`
with provider `statement` has no token; its downloaded CSVs (Chase credit,
Chase checking, any Debit/Credit export, `charges_positive` for cards that
export purchases as positive) become `BankTransaction`s and go through the
same `classify`, so rules sort them, `adopt` claims the expenses already
typed (this is how the 108 earlier expenses get checked), and waiting
receipts attach. A row's id is a fingerprint plus its occurrence in the file,
so re-uploads store nothing twice while two identical same-day charges stay
two. On a `kind="personal"` card a business charge is an expense with
`paid_by` its owner, a split vendor charge's shares likewise; card payments are transfers; money in is never income; and a
"personal" rule learned there (`VendorRule.applies_to`) never touches a
company card. A contribution rule only matches money in, a draw only money
out. The nightly Mercury read skips statement accounts.
`tools/test_statements.py`.

## The books keep themselves

Michael, 2026-11-04: everything automated, and nothing on the server calls a
paid model (`docs/automation_gaps.md`, items 2, 13, 14 and 15). Each piece is a
step of the nightly cost-sync (`night.step` in `sync_costs._sweep`), and what
needs him is a `BooksFlag` row written by the night and drawn on Needs
attention (`books_upkeep.attention_rows`). The flag is a table because the
sidebar badge is built on every page and a month's books read Stripe live: a
check that costs seconds belongs to the night, never to the badge.

**The bank review settles itself as far as it can.** `bank_review.suggest_free`
gives every waiting line a suggestion with no model, first answer wins: the same
counterparty settled by hand before (`counterparty_key` drops store numbers and
processors), a receipt for the same amount to the cent, a vendor the board
already pays, then the bank's merchant category (Mercury's, or the Category
column a Chase card export carries). Only the first three carry a `pattern`, so
only they write a rule when accepted; "Food & Drink" is not a vendor. It runs
nightly after the bank feed and after every statement upload, and never
overwrites a suggestion without its own `source`. What is left is the `/bank`
skill (`.claude/skills/bank/SKILL.md`), run in a Claude Code session on his
plan: `bank_review` and `bank_decide` in the bridge, `/api/guidance/bank/review`
and `/bank/decide` behind the door (`pm/bank_door_routes.py`, a blueprint nested
in `guidance_bp` so its bearer gate covers it by construction), settling through
the same `bank_feed.decide` as the review page. `tools/test_bank_review.py`.

**Statements ask for themselves and reconcile.** An upload keeps the balance
before its oldest row and on its newest (`balances_of` reads the file's order
from the balances themselves, and trusts neither order if the arithmetic fails),
and `bank_check` holds the lines in between to the difference, so a month never
uploaded is a disagreement rather than a silence. A card export has no balance:
reaching past the month's end is all it can show. A source with nothing past
last month's end (its newest statement line, or an upload after that day) is one
row, "October statement to upload".

**Chase's alert emails are lines the day the card is used.** With Chase's "a card
transaction is higher than $0.00" alert on (the Chase playbook says where; the
"online, phone or mail" alert it replaced was retired 2026-02-17), each email in
a receipt mailbox becomes a `CardAlert` and then a provisional line, `kind
"alert"`, on the source whose last four digits it names, classified and booked
like any other. A source learns its digits from the first alert whose charge is
already on exactly one source. The CSV folds over an alert's line by amount to
the cent within days (`_fold_alert`), keeping its expense; an alert inside what
the upload covers that it did not confirm was declined or changed by a tip, and
is cancelled with its expense. Only statement lines count as an upload, so the
upload stays the check that closes a month. `tools/test_statement_checks.py`.

**A month closes itself** once nothing is unsorted, EVERY expense has its
receipt (Michael's change: not only those over $75; a statement line stand-in
counts as in) and every account agrees, with `MonthClose.note` "Closed by the
nightly run". Otherwise ONE row per company names the newest finished month and
why ("October will not close: 3 unsorted, 1 receipt") and counts the earlier
ones. Mercury is held against its CURRENT balance, so if its history starts
after the account opened, every month waits on that row until it is explained.
Closing by hand clears the row at once. `tools/test_month_close.py`.

**Vendors follow the bank.** A flat provider (Claude) takes its amount and day
from its last settled line (`follow_flat_from_bank`): for each recent month with
exactly ONE such charge, the entry becomes that charge on its day and the old
guess goes. A month with two is left to review, because EntertainHQ's own Claude
plan is on the same card under the same name and choosing between them moves
money between companies. A prepaid vendor (`PREPAID_PROVIDERS`, Twilio) is the
other way round: its top-up is the expense, even under a split rule
(`bank_feed.is_prepaid`), and its usage rows record and attribute and book no
expense. Recurring expenses retired on 2026-11-04; an old child no bank line
claimed within ten days is still one row. `tools/test_vendors_follow_bank.py`.

**A receipt with no bank line** from a vendor the board already pays (its rules,
providers and known vendors), within five days on any connection, is a card the
board cannot see: one row, listed on `/admin/books/checks`. Only receipts old
enough that every connection's lines reach five days past them, and only the
last 45 days, so it clears itself; Set aside takes one off at once.
`tools/test_receipt_no_line.py`.

## What a month of usage cost

`service_costs_service.py` records a vendor's charges as `ServiceCostEntry` rows.
Until 2026-11-04 each wrote an `Expense` beside it; now only Stripe's fees do,
and the rows split the bank line's charge (see "Finances, consolidated"). What
follows is why the rows are keyed as they are, and it still holds. The entry's key is (provider, resource,
period_start, period_end, mapping), and **period_end being part of that key is
the whole trap**: a month to date figure grows all month, so a nightly sync has
to CORRECT the row it wrote last night rather than stack another beside it, and
it can only do that if the period it writes does not move.

`_month_bounds()` is the answer and its docstring has said so since the first
time this happened. Stripe and Cloudflare used it; Twilio and AWS were written
before it and never picked it up. Twilio's monthly usage record carries an
end_date that tracks today while the month is open, so from 2026-09-01 the
nightly run wrote a NEW row every night holding the whole month to date.
Fifteen nights in, September read **$462.79 of outbound SMS against $59.67 of
real usage**, plus the same in miniature for inbound SMS and Polly. August was
a single correct row, which is the tell: once a month closes its end_date stops
moving and the key settles. Every other provider was clean.

Migration `d4f81c27a3b9` folds what was left behind. The rule it applies, per
(provider, resource, mapping, month): a group is a month to date SERIES only
when its rows start on the first AND at least one ends after that day. Keep the
newest, give it the month's bounds, delete the rest with their expenses. That
test is what protects `_sync_flat`, where a vendor billing twice in one month
legitimately writes two SINGLE DAY entries (Anthropic did, in March and again
in May): every row there starts and ends on its own day, so the group is never
a series and nothing is touched. `tools/test_cost_periods.py` runs fifteen
nights of the real payload through the sync and then folds a ledger built to
look exactly like the one that shipped.

**A period is a key; a date is a fact, and they are not the same field.**
Fixing the above by keying the entry to the whole month put the expense's
date at the end of that month, because `_sync_expense` dated from
`period_end` - so on the 16th the ledger showed September's accruing
Twilio, Cloudflare and Stripe charges dated **Sep 30**, money listed
against a day that had not happened. Cloudflare and Stripe had read that
way since before any of this; the Twilio fix simply made three more rows
do it and the owner spotted it at once. The date is now `min(period_end,
today)`: it lands in the month it belongs to, it is a day that has
happened, and it stops moving once that month closes, because the last
nightly run of a month is the last day of it. The key is untouched, so
nothing goes back to a row a night. `_sync_flat` already held this rule
for subscriptions - "a subscription you have not been charged for yet is
not an expense" - and the month bucket path simply did not honour it.
Migration `e7b2c05d18af` pulls back the rows already written that way,
touching only expenses a cost entry owns: a hand typed expense dated
ahead is somebody's deliberate note and is left alone.

And a date that has happened is still the wrong thing to show. Dated the
16th, $59.67 of Twilio SMS read as a sixty dollar charge that landed that
morning; it accrued over sixteen days and has no single day at all. So the
ledger's first column is **When**, not Date, and a row whose cost entry
spans a month says the MONTH - "Sep 2026", with "to date" under it while
that month is still open - where a charge on a day still says the day.
`Expense.date` is untouched: it sorts the list and decides the month a
figure rolls into, it is just no longer what the row claims. Three steps to
get here, and each one only looked right until somebody read the screen:
the period was the key, then the key became the date, then the date stopped
pretending to be one.

**Whose account is it.** Every cost entry wrote an Expense, which assumes
the account the credentials open is Built by Bean's. The Twilio runbook on
this very board says otherwise in as many words: "get onto the CLIENT'S
Twilio account, then create your own API key on it", and
"TWILIO_ACCOUNT_SID names whose account is BILLED, not a credential". So
the nightly sync was reading an account on somebody else's card and booking
all of it as money this business had spent. `ServiceProvider.account_client_id`
says whose it is, null being ours, which is every provider that came before
it. When it names a client: the cost entry is still written and still
attributed to them, because what it costs to run their app is the number a
hosting conversation needs, and **no Expense is written**, because an
expense is money that left this business. Changing the setting reconciles
on the press rather than waiting for the nightly run, in both directions,
and restates the attribution so a row stops reading "[unallocated]" the
moment it plainly belongs to somebody. `account_label` is what the vendor
calls the account, read back on each Twilio sync, because a SID answers
nobody's question about whose it is and the answer decides whose money it
was. `tools/test_whose_account.py`.

`account_business_id` is the same answer for another of Michael's own
businesses: EntertainHQ LLC pays for its own Railway Pro workspace since
2026-09-16, so "Railway (EntertainHQ)" records and attributes its costs and
writes no Expense here. `is_ours` is both columns null, and every place that
decides whether a cost is this business's money asks `is_ours`, never one
column; the hosting page's all-time Railway figure reads only the provider
that is ours.

**Railway's bills pull themselves.** The board believed from 2026-08-31 that
Railway's API would not report money, because the token it was probed with
was scoped below the account. An ACCOUNT token reads `workspace.customer.invoices`
(each bill, period and total in cents) and `usage` grouped by project. A Railway
provider whose credentials carry `workspace_id` records each finished bill in
`ProviderInvoice` under the month its period starts (the convention the typed
rows used: Aug 1 to Sep 1 is August), and splits the month across projects by
usage priced at `RAILWAY_RATES`, scaled so the projects add up to the bill to
the cent. Never touched: a bill typed by hand (any note not starting "From
Railway") and a month broken down by hand. Never written: a period still
running. A project that moves workspace keeps its Railway id, so the other
account's mapping is copied rather than guessed. EntertainHQ bills 16th to
16th, which is why Needs attention gives a pulled account a month's grace.
Saving a Railway provider with a token pulls at once. The account token is
`PM_RAILWAY_ACCOUNT_TOKEN` on the web service (cost-sync references it), made
2026-11-02 on Railway's Tokens page with no workspace; the CLI's own login can
read bills but Railway refuses it `apiTokenCreate`. A project mapped after a
pull loses its no-mapping row on the next one (`prune_stale_allocations`,
shared with the monthly page), or the month reads double: $54.30 against a
$43.71 bill in the test. `tools/test_railway_billing.py`.

**Which bills are missing is one function** (`provider_bills.bill_months`),
read by Needs attention and by the door's `get_costs`. Each had its own loop
and only Needs attention gave a pulled account its month of grace, so the door
reported Railway (EntertainHQ)'s October as not recorded while its bill could
not exist before November 16 (audit fault 8). The door now lists that month
under `months_not_billed_yet`. `tools/test_bills_months.py` asks both surfaces
and fails on the old code.

Chasing that one found a second, unrelated fault on the same page. The ledger
ordered by `Expense.date.desc()` and nothing else, and every vendor charge for
a month is dated the last day of it, so far more than twenty rows share a date.
A date alone is not a total order: the database may return that block
differently for each query, and page one and page two then cut through it in
different places. Measured live, 75 slots over four pages held 67 distinct
rows - **eight expenses came back on both page one and page two, and eight
others were on no page at all.** Every paginated query in the app now ends its
ordering on a unique column: expenses, time, clients, projects and leads.
`tools/test_stable_paging.py` carries it as a SOURCE check on purpose, because
SQLite returns rows in rowid order when nothing else decides it, so the fault
does not reproduce against the database the suite runs on and a behavioural
test alone would pass on the broken code.

## Sales tax

`/admin/taxes/sales` (`pm/tax_routes.py`, arithmetic in `sales_tax.py`). The
accountant's reading, 2026-10-27: software sold as a service is a data
processing service in Texas, 20% of the charge is exempt, so the tax is 8.25%
on 80% = **6.6% of every dollar billed**. `SalesTaxSetting` keeps the two
facts (rate, taxable share) rather than the 6.6, and `effective_percent`
rounds the product to four places because 8.25 x 0.8 is 6.6000000000000005
in floating point and it becomes a Stripe tax rate.

Most invoices went out without it, and the tax was owed when the sale was
made whether or not it was on the bill. So each sent or paid invoice owes 6.6%
of its pre-tax amount, `short` is that less the tax Stripe charged, and a
client's "to bill" is the sum of their shorts less what a **catch-up invoice**
has already billed back. A catch-up is a draft the board writes in Stripe with
metadata `bbb_sales_tax=catchup`, one line per project, no tax of its own; it
is read and sent from its own page like any other invoice, and paying it is
what clears the balance. Nothing on this page sends anything.

The hole is closed in three places, each a press: invoices raised from the
board carry the rate automatically (`invoice_create`, skipped for an exempt
client); a client's pre-written drafts get it with "Tax N drafts"
(`Invoice.modify(default_tax_rates=...)`, drafts only, since Stripe will not
edit a finalised invoice); and a subscription gets it with "Tax the
subscription", which changes what the client pays next cycle and so asks first.
Stripe will not change a tax rate's percentage, so a change in settings makes a
new rate and archives the old one.

Exemption is a fact about the buyer (`Client.sales_tax_exempt`: out of state,
a certificate on file, Michael's own row) or one invoice the accountant says is
not a sale (`Invoice.sales_tax_exempt`). Both are board-owned and an import
never touches them. With two or more projects an unassigned invoice is NOT
guessed onto one, because that would move tax between builds; with exactly one
it is that project's.

`Invoice.tax` was never filled in by the importer, and `sync_invoice_from_stripe`
read `si.tax`, a field newer Stripe API versions removed - so on those versions
that line raised and the WHOLE sync failed on one attribute. Tax is now
`total - total_excluding_tax` (`stripe_service.invoice_tax_cents`), which every
version since 2022 answers, and the importer no longer copies the total into an
empty subtotal, which counted tax as part of the sale. `issued_on` is the day
Stripe finalised the invoice, because `created_at` on an imported row is the day
of the import and says nothing about which quarter's return it belongs on.
`tools/test_sales_tax.py`.

## Every business, and the returns each one files

Michael, 2026-10-30: "I'm not just Built by Bean anymore. I'm EntertainHQ also
... I need a command center for all of it." So the board is the command
center over every business he owns, and `/admin/businesses` is its front
door (`pm/business_routes.py`, CEO only, first link under Needs attention).
`Business` holds what the state knows a company by: the Texas taxpayer
number, the SOS file number, and TWO WebFile numbers that are not
interchangeable (sales tax is RT and six digits, franchise tax XT; eSystems
"Assign Tax/Fees" refuses the wrong one). `BusinessLocation` is each place a
permit lists, with WebFile's own five digit location number, which is the
Comptroller's and not in opening order: Paris is 00001, Fort Worth 00002.

The front door shows the business, not its tax (Michael, 2026-11-01: "as my
business grows I want these done differently. Where I can see the
business"): a tile per business with its logo, name, start date
(`formed_on`) and lifetime revenue, opening `/admin/businesses/<id>`, where
the tax numbers, the next return and the locations live. The logo is an
uploaded image or a My Apps tile's icon (`logo_file`, `logo_app_id`), one or
the other. Lifetime revenue (`business_routes.lifetime_revenue`) for the
business the board bills from IS the dashboard's Total Revenue, read from the
same `get_stripe_invoice_totals()["revenue"]`. It shipped as the board's
invoice rows while the dashboard read Stripe's cash total, and the owner found
the two pages disagreeing the same evening: one business's takings are one
number.

**Revenue is earned money, never sales tax** (owner, 2026-11-01, "take tax
out"). Every revenue figure is paid less the tax on it and less any refund, with
nothing from a catch-up invoice: `get_stripe_invoice_totals()["revenue"]` (and
`revenue_by_customer`) for the dashboard's Total Revenue, its per-client
column, its Profit before tax and the Businesses tile; `Client.total_revenue`,
the same reading over the local rows, for the client page and its profit.
`paid` stays as cash in, tax and all but after refunds, for the pages that mean
cash, and the guidance API's `paid` key keeps that meaning. A new revenue figure reads one of
those two, never `amount_paid` raw. A business on its own app shows what the app last reported
(`revenue_total`); the list never asks the app, the business's page asks with
a six second wait when the answer is an hour old, and "App not reporting" is
said rather than $0.00. `tools/test_business_pages.py`.

**A DBA is a business with no tax of its own** (Michael, 2026-11-02, of
Data Dungeon: "technically not its own business because it sits under my
Built by Bean LLC, but it effectively is a business"). `Business.parent_id`
names the company it trades under, one level deep; the code says division,
the screen says DBA, and its page header reads the legal way, "Built by Bean
LLC d/b/a Data Dungeon". On Businesses each company is a family: its tile,
with its DBAs hung under it on a connecting line drawn from under the
parent's logo (`data-family`, `data-dba-of`), one column wide so the same
tree reads at 375px. Its page points at the parent instead of a tax card. It is never a row on the
returns pages or the guide: its taxable sales are the LLC's, filed on the
parent's return, and a second set of returns would file them twice. Nor does
it ever read "board" for revenue, which is the parent's takings. Making a
business a division hides its tax fields on the form but keeps what was typed,
so one wrong pick cannot wipe Built by Bean's taxpayer number. Migration
`f3b9d27c4e18` put Data Dungeon on file. `tools/test_business_divisions.py`.

**Three dates, an age, and the papers.** `conceived_on` (first an idea),
`formed_on` (the LLC filed; a DBA has none) and `launched_on` (open for
business). Age is worked out by the `age` filter in whole calendar months, so
a business turns a month older on the day of the month it launched; it runs
from the launch, and before one from the idea ("In the works"). The tile
leads with `Business.milestone`, whose label always names the date shown, so a
formation date never reads as a launch. `BusinessDocument` is the company's
own paperwork, LegalZoom's filings first: a kind from `KINDS` (Texas calls the
articles a Certificate of Formation; a DBA's lawful footing is an Assumed Name
Certificate), stored on the volume under `business_documents/` exactly as a
return's confirmation is. `tools/test_business_papers.py`.

**The map: a network of everything that makes a business run**
(`/admin/businesses/<id>/map`, `business_map.layout`, pure). Three versions
shipped on 2026-11-02 before it was right, and the owner's words on the first
two are the spec: a vendor list in columns is "the weakest version of a map I
have ever seen ... nothing properly shows what we're using for what purpose";
a prettier one "is still just not as comprehensive ... you don't even list on
here that we have a marketing site, that we have an admin portal, that we have
a status site ... you've also just got everything in columns, and it's a
mess". And what belongs on it: "the thing we don't need is anything explaining
how messages get sent to each other inside the app ... but how does this
product let our customers know there's an outage? That is connected to a
system outside the app itself."

So the map is a graph on two tables. `BusinessNode` is every kind of thing:
an AUDIENCE (tenants, talent, partners, Michael, Texas), a SURFACE people
touch (the marketing site, the app, the portals, the phone apps, the status
site at status.entertainhq.com which is a Cloudflare Worker outside Railway,
the admin board, the inbox), a SERVICE (a vendor, with its need on the
business playbook and its runbook), or an OUTCOME (something the product
does that leans on a system outside the app, with a status: delivered, in
progress, missing). `BusinessEdge` is every line, with its why. The layout
is radial: the business in the middle, surfaces evenly round it, every other
node on its own ring at the mean angle of what it connects to, pushed apart
along the ring until nothing overlaps (`_spread`; its first version treated
two identical angles as a full circle apart and stacked a whole sector on one
point). Hover or pin anything and the rest dims to its lines. A hole is an
essential need no service fills, drawn in the admin board's sector. The
playbook's lines between two services (Stripe to the bank) are drawn faint
unless the business wrote its own for the pair. Migration `a2c9e7d14b58`
moved every row of the four earlier tables into nodes and edges and dropped
them; the seed put EntertainHQ's ten surfaces and seven audiences on, with
the lines, and the two outcomes that cross the boundary.

**The tiles are HTML, the lines are SVG.** An SVG `<image>` under the
pan-and-zoom transform is rasterised once and stretched, so every logo
blurred when zoomed. Each node is an `<img>` laid out at its real pixel size
from the same `tx, ty, k` the lines use (`nodeStyle`, `px()`), in an app-icon
tile the logo fills edge to edge; a square logo is never put inside a
circle. A surface or service with a URL and no runbook gets its own mark
fetched off that URL (`fetch_node_mark`, served by `node_icon`, nosniff), on
a press or on save, never on render. A pin is read on pointerup without
movement, never from `click`, because the canvas captures the pointer and a
captured pointer's click lands on the canvas; `touch-action: none`, or a
finger's drag is the browser's scroll. `|tojson` rides in single-quoted
attributes. `tools/test_business_map.py` runs the four migrations in the
order production did.

**Search and focus** (Michael, 2026-11-02: "if I'm in a meeting and someone
says, head of our clients, what is running? I need to be able to filter that
where everything else hides"). The box in the toolbar matches any word of a
node's name, role, need or kind; picking one, or Only this on a pinned card,
hides everything off its TRAIL and fits what is left: the thing, what it
touches, and two steps out only toward answers (a surface's services and
outcomes, an outcome's services), never through the centre and never into a
second person or surface, or one person's trail would be the whole map. The
whole `<g class="edge">` hides, not just the stroke: a hidden line's
invisible 30px hit path kept catching hover and left a stale card up.
A focus RE-LAYS its trail (Michael: "make that where it kind of goes to a
friendly layout"): the picked thing in the middle, what it touches in a ring
round it, the second step in a ring beyond (`localLayout`), tiles gliding
there over 420ms (`animateTo`) with the lines drawn from the live positions
(`pathFor`, `pos`), because five things left where the whole map put them
are five things scattered across a canvas. Show all glides them home.

A return is worked out, typed into WebFile by hand, and recorded from the
confirmation page. `sales_tax.build_return` splits a period's sales by the
location trading THAT DAY (`Business.location_on`) and rounds each line to
the whole dollars WebFile takes; WebFile does every tax figure itself from
the two numbers typed per location, so those two numbers are the whole job.
It reproduces both returns Built by Bean filed on 2026-10-30 to the cent
($339.90; then $165.00 Paris and $491.70 Fort Worth), and
`tools/test_business_returns.py` holds it to that. A sale on a day no
location covers is shown as unplaced, never dropped, because filing without
it leaves a sale off the return. `SalesTaxFiling` is one row per business per
period, written off the confirmation page and never computed: what the state
charged, the three reference numbers, and the card fee on top. The
confirmation PDF goes on the volume under `tax_filings/`, and the board can
print its own record of any return (`record.pdf`) so a filed return is never
here with nothing to print.

Where a business's sales come from is `sales_source`: "board" is this
board's invoices, counted by the ledger's own `invoice_row` (billed back tax
is not a sale); "hub" is the business's app answering
`POST /api/hub/tax/sales` with `{"sales": [{date, total, taxable, ref}]}`;
"manual" is nothing to compute. **One store, two doors.** A business with an
app of its own talks to the same rows over the hub, signed with ITS secret
exactly as a client's tickets are: `/api/hub/tax/returns` (its periods, with
figures for any sales it sends along), `/api/hub/tax/filings` (record one),
`/api/hub/tax/files/put` and `/files/get` (base64, because the signature
covers the body's bytes). The board never calls back into the app from
inside a hub request, because two apps each waiting on the other is how a
page hangs; and a WebFile number never crosses the wire, because it links a
tax account to whoever's eSystems login types it. EntertainHQ's admin is
the first app on the other end, so a partner there sees the return Michael
recorded here and the other way round, with nothing kept twice.

The lesson that cost money: a return that is not filed gets an ESTIMATED
return from the state, set high on purpose ($1,158.93 and $2,202.53 where
the real tax was $339.90 and $656.70), and it shows as a balance due on the
account. Filing the real return replaces it; paying the estimate would have
paid three times the tax. And a quarter with no sales is still a return to
file. `/admin/taxes/sales/guide` is the whole routine in Michael's words,
including how a new business gets registered and linked.

## What the state says, and one deadline list

Audit items 8 and 12 and faults 4 and 5 (2026-11-04). `comptroller.py` runs
nightly as the "Comptroller" step, after the bank, and reads three free public
sources with no key:

- **The franchise tax search** (`comptroller.texas.gov/data-search/franchise-tax/<n>`,
  JSON). Standing (`rightToTransactTX`), SOS status, registered agent and
  office, mailing address and EIN are the STATE'S fields: they are kept on
  `Business` and a change writes a `ComptrollerFlag`, shown once on Needs
  attention with a Seen press. The typed fields (SOS file number, formed on)
  are filled only when empty, and a difference is flagged, never overwritten.
  `reportYear` becomes `franchise_report_year`, which is what marks a May 15
  report done. Standing that is not ACTIVE is a red row that cannot be
  dismissed while it lasts.
- **The permit list** (`jrea-zgmq`). Fills NAICS, permit date and first sale
  when empty (1961-09-01 is the file's "unknown"), matches each outlet to a
  location by its five digit number or, for a location typed before its
  number was known, by town, makes one it has never seen, and flags an outlet
  that drops off. A number with no rows sets `permit_status = "none"` and the
  business page and the returns page say so in words. Built by Bean's
  32093304155 found none on 2026-11-04 while it was filing returns; Michael is
  asking the Comptroller why.
- **The quarterly city rate workbook** (`city-rates.xlsx`), read without a
  library (`read_xlsx`). Its sheet name is the only place it names its quarter,
  so a file still saying last quarter writes nothing and is tried tomorrow. A
  town with more than one rate is not guessed, a location outside city limits
  is left, a rate changed by hand on the form becomes `rate_source = "typed"`
  and is never overwritten, and a change to one the file set is flagged.

**A Comptroller charge drafts its return** (`draft_filings`). A bank or
statement line to the state from the last 120 days, with no return recorded
within the window `books_service.filing_payment` uses, is matched to the
newest unfiled period ended before it whose tax plus estimated penalty (or
less the discount) fits the charge within a card fee, plus interest room when
late; Built by Bean's real Q2 return ($436.79 off the card for $339.90 of tax)
drafts as Apr-Jun 2026. The draft carries everything but the reference number,
reads as "drafted" (`sales_tax.status_of`), asks for its reference on Needs
attention, and opens on its form. A draft is built with `business=`, not
`business_id=`, or a second charge the same night drafts the same period
(the test caught that). Taking a draft off writes `DeadlineDone("nodraft:<line>")`
so the next night does not draft it again. `search_mail` searches every
receipt mailbox for Comptroller mail and fills references when one states
them near the date and amount; nobody had seen whether eSystems mails a
confirmation when this was written, so the night's note says how many it found.

**Periods** (fault 5). A period is `(year, n)`: n 1 to 4 a quarter, 101 to 112
a month, 10 the year, all in `SalesTaxFiling.quarter` and the hub's `quarter`,
so every quarterly row, URL and code is unchanged. A month or year has no
WebFile code: nobody has filed one and a guessed number on the radio button is
worse than none. A return filed under one frequency stays listed after the
Comptroller moves the business to another, and the months inside it are not
owed again (`business_routes.owed_periods`). **Where counting starts** (fault
4) is `sales_tax.owed_from`: first sale, else permit registration, else the
earliest return filed, else the first location; with none the pages say "no
returns are counted" rather than drawing an empty list.

**`deadlines.py`** is one list, `/admin/taxes/deadlines` (CEO only, a tab on
the sales tax pages): sales tax by period, the franchise report and PIR every
May 15 from the year after formation, a 1065 and K-1s for a company with more
than one `BusinessOwner`, the 1040 and Schedule C, the four estimates, and a
DBA's assumed name certificate ten years from `assumed_name_filed_on` (due the
day before it lapses, never rolled past it). Every date rolls with
`sales_tax.working_day`, the Taxes page's estimate dates included. A record
proves done where one exists (a filing, the report year, an IRS line on any
bank or statement within 30 days of an estimate, each line used once);
otherwise Done and Undo write `DeadlineDone`. Federal and estimate dates start
at `LIST_STARTED` (2026-11-01), because the board knew none of them before and
every past one would read as late. Needs attention carries a deadline from
`LEAD_DAYS` (10) out and once late, for the CEO only, cached ten minutes for
the badge. `tools/test_comptroller.py` (`--live` asks the state),
`tools/test_deadlines.py`, `tools/test_tax_periods.py`.

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

## One support board across every business

Michael, 2026-11-04: "each app I have already has its own built in ticket
system ... so just needs to be way more user friendly as an overall customer
support board for all my businesses. but making sure those systems talk to
each other properly ... the health of my clients satisfaction rates at a
glance. quick nav buttons over to those site own portal". He approved each
piece: one inbox with app tiles on top, Waiting on you first; response and
fix times now with a customer rating added in each app later; four quick
links per app; answering from here through each app's own desk; J&D under
EntertainHQ; and a sidebar badge.

`/admin/tickets` (Client support) is `support_service.py`, the ticket routes
in app.py, and `pm/support_routes.py` (each app's links and desk door, CEO
only). Tickets reach it two ways and are owned differently:

- **The hub** (above): a client's app owns the words, the board owns status.
  Unchanged, except that a note may say `is_staff_reply: true` (the app's own
  staff answered in its admin): it counts as a reply and reopens nothing.
- **A desk**: EntertainHQ and Data Dungeon run support desks of their own,
  where their partners triage, and the DESK owns those tickets. The board reads
  EntertainHQ's through its API door (`/support/api/tickets`, Bearer
  `SUPPORT_API_KEY`, `acting_for` on every call; its repo's
  docs/SUPPORT_API.md), and a reply or a status pressed here goes through that
  door exactly as a click on the desk would, then is read back. The board keeps
  no triage of its own for a desk ticket: kind and priority are the desk's,
  status changes only by reading the desk. Only billing, circle back and out of
  scope stay here, and they never travel. Desk writes are CEO only, because the
  desk records them as the login they act for.

A desk ticket is keyed `Ticket.origin_ref = "<company>:<id>"`, because the
desk numbers per company. **The hub's two drains skip anything with an
origin_ref**, which is the whole separation: a desk ticket can never be sent
down the hub. Its client is null and `business_id` says whose it is; a ticket
with neither is Built by Bean's. A reply written here and later read back from
the desk is matched by its words, so the thread never shows it twice. A reply
the desk refused stays on the thread as "not sent to the desk yet" and is
retried for two days (`DESK_REPLY_FRESH`), never sent late after that.

**J&D is shown once.** Talent Booker has sent its tickets to EntertainHQ's desk
since 2026-11-01, so `SupportApp.moved_to` takes it off `hub_clients()` and a
ticket the board already held from it is ADOPTED when the desk's copy arrives
(`hub.talent-booker:<id>` matches `origin_ticket_id`): same row, same marks,
its old note ids cleared because the desk's would collide with them.

`SupportApp` is one row per app on the board, made on first sight from
`support_service.DEFAULTS` (defaults in code, edits in the database): its four
links (an http(s) URL or nothing, since they land in an href), and for a desk
its door, key and login. The key is typed on the app's settings page and never
shown again, or read from a variable on the web service named
`DESK_KEY_<ORIGIN>` (`DESK_KEY_ENTERTAINHQ`), so connecting a desk never waits
on somebody pasting a key. The desk puller runs every ten minutes (`DESK_PULL_INTERVAL_SECONDS`)
in its own thread and skips a desk read in the last eight minutes, so two
gunicorn workers read once; a pass is one list call plus at most 25 threads,
because the door allows 60 calls a minute across every caller, Michael's own
sessions included.

**The health tiles** (`support_service.health`, last 30 days) are made of
timestamps stamped when they were seen to happen, never backdated:
`waiting_on`/`waiting_since` (who speaks next, stored so the badge and the
Waiting on you tab are one query and the same number), `first_reply_at`,
`resolved_at`, `reopen_count`, `verify_requested_at`/`verified_at` (EntertainHQ
asks "did this fix it?") and `said_solved`, the customer's own answer when an
app sends `solved` (none does yet; filed as a gap on each blueprint). A ticket
that arrived already resolved has no resolved_at, because "now" would make every
imported fix look instant. A figure with nothing behind it says "None yet".

**A copy the app no longer feeds is off the board** (Michael, the same
evening, of 31 rows "waiting on you" for 66 days: "I have no tickets pending in
EntertainHQ. So not sure where the hell these are coming from"). They were
Talent Booker tickets copied here by the Aug 29 backfill. After creation the
board owns status, so a close in Talent Booker reaches it only when Talent
Booker sends one, and it sent them to `/admin/pm` (405) and then to
EntertainHQ's desk: none ever arrived. They sat in Open unnoticed until the
waiting-on-you backfill, which reads only this board's own thread, called every
one of them waiting. `support_service.hidden_origins()` is every app that is
not `on_board` (moved to another desk, or `supported` off), and
`support_service.on_board(query)` takes its rows out of every tab, tile, count,
the badge, the pulls and both drains. They are kept, never deleted, and a moved
app's ticket comes back only by adoption, with the desk's status. **A derived
"who must act" over rows copied from another system has to ask whether that
system still feeds them.**

`SupportApp.supported` is "Support this app" on each app's settings, on by
default. Robinson & Co. starts off (migration `d1e7b4a92c05`): it was wired to
the hub while its build tested the link and was never contracted, so its two
rows were build tests. An off-board app is listed under the tiles, linking to
its settings, so the switch is never lost.

**The row is two lines** (Michael: "the layout of each row with the massive
wide expanded dropdowns is just such a waste and looks ugly"): what it is, then
kind, app, who and status on one truncating line, the wait and a chevron on the
right. Status is a row of presses inside the opened row (pressed all day, so
not a picker); priority, kind, billing and minutes apply on the pick or on
leaving the box, with no Save anywhere. Each card is its own `data-live`
region and its forms carry `data-live-scope` plus `data-live-also="tabs tiles
nav-support"` (base.html: a scoped press also swaps the regions it names), so a
pick re-renders that card and the counts it moves, nothing else. `next` carries
`keep=<id>`, which holds a card in the answer when its change took it out of
the tab, so it swaps to what is now true instead of standing stale.
`select_dropdown`'s `measure()` now takes the nearest scrolling box's edges as
the room there is: in a contained list the last row's picker opened downward
into a box that cut its options off.

**A status press that reaches a person asks first** (`tickets/_status.html`,
shared by the open row and the ticket page; catalogue rule "A button that sends
something says what it will do, then waits for a second click"). The desk's
Resolve shipped texting and emailing the reporter on one press with "Tell them"
preselected. Now every status press that leaves the board names the outcome and
the person ("Resolve and tell Kenali", "Resolve quietly"), shows one sentence of
what goes out and to whom, and acts on a second press beside Cancel. The
sentences are what each app's code does (EntertainHQ's `_desk_set_status`:
In progress posts a note to My Tickets, Resolve texts and emails or not; Kuper's
`/api/hub/status` applies and sends nothing); change one when that code
changes. A ticket raised here reaches nobody, so its presses act at once.

A tile's name picks that app in the App filter (`appPick`, shared through a
`display: contents` wrapper and `select_dropdown`'s `model`) and the bar applies
it in place, keeping every other filter.

**Nested live regions.** The cards are regions inside the results region, and
`bbbSwapLive` used to swap each card again after the results had brought it in,
replacing it with itself, which removes it: every filter change emptied the
list (live for an hour, 2026-11-04). It now skips a region that came in with its
parent. In the desktop app's preview pane, while the pane is hidden, Alpine's
x-show waits on an animation frame that never comes; check the board's
interactions in headless Chromium.

Data Dungeon has a full desk (`/admin/support`) and no door yet, so its tile
says "Desk not connected" until it builds EntertainHQ's door (filed as its
gap). `tools/test_support_board.py` runs both round trips, the desk against a
fake EntertainHQ desk served over real HTTP in the door's own shapes.

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

**Mail reads itself every five minutes** (`mail_service.start_background`,
started from `create_app`, audit item 4), not only when Needs attention or
Messages is opened, so the badge is never as old as the last visit. Two traps
it found. `app.py` builds an app on import and gunicorn's `app:create_app()`
builds a second, so a flag on the app gave every worker two timers: the guard
is per process (`_timer`) and the timer serves the newest app. And the two
workers still each run one on the same schedule from the same boot, so a pass
takes `pg_try_advisory_xact_lock` first and steps aside when the other worker
holds it; otherwise both insert the same new mail and the second pass dies on
the unique Message-ID. The hub threads above are still guarded per app, so
each runs twice per worker; harmless because they upsert, but worth folding
into the same guard. `MAIL_SYNC_DISABLED=1` turns it off.
`tools/test_mail_every_five.py`.

## A payment moves the client

Audit item 5 and fault 6, in `stripe_service.py`. The first payment moves a
client to Active through the webhook and the six-hourly importer, not only the
Sync press on one invoice. Only when THIS read saw the payment arrive (the
local `paid_at` was empty) and it is under `RECENT_PAYMENT_DAYS` old
(`newly_paid`): the first import after a client is linked meets every old paid
invoice, and must not pull a client set to Follow up later back to Active.

An invoice whose Stripe customer no client carries finds its client
(`client_for_customer`) by the board's own `metadata.pm_client_id`, then by an
email exactly one client has and that client carries no customer yet; it fills
only an empty `stripe_customer_id`, which is unique, so a second orphan on the
same client stays an orphan rather than raising. A metadata match places the
invoice even when the client carries a different customer, because only the
board writes that id. A new local invoice takes the client's project when
there is exactly one (`only_project_id`, the sales tax ledger's rule).

`create_stripe_customer` and Sync all clients go through
`link_or_create_customer`: Stripe is searched by metadata, then listed by
email, and a customer no other client carries is adopted (oldest first, its
metadata written) before one is made. Making one regardless is how clients got
two customers and invoices with no home. `tools/test_payment_moves_client.py`.

## Clients, and mail as the record of contact

Michael, 2026-11-04: "make them more user friendly and dont have unused
features as I have not been using most of them as a lot of them dont even
properly talk to the rest of the PM". Every piece was checked against the live
board and put to him one by one. The hand-typed contact log (`ClientContact`,
the Log contact box, the Tried and Not tried filters, the channels column) had
no rows on any of the six clients, while their mail was already here; it is
gone from the screens and routes, and the table and its rows stay. Mail is the
record of contact now: the client page lists their mail both ways, and the
list's Last contact column is the newest mail (`Client.last_messages`, one
query for the page). The Stripe "Synced" pill, green on every client, became
an Invoices link. The page also shows their contracts (hidden ones stay
hidden, as on Contracts) and their apps from My Apps. Delete client moved to
the edit page's header, behind the client's name typed in a dialog and checked
again on the server (it takes every project and invoice with it), the app-hub
fields fold away unless filled, Documents is compact,
and on a phone the name sits under the company with no edit pencil so the
table never scrolls sideways. `tools/test_clients_page.py`.

**Who a mail is from** is `pm/contact_matching.py`, kept apart from
`mail_service` so the reading and the matching change separately. A client is
matched on their address, then on their business DOMAIN, so a colleague at
jdentertain.com files under Kenali; a free mail domain, the board's own
domains, and a domain two clients share never match, because a guess files
one client's mail under another. The sync searches `@domain` for those
clients. A reply from a client at Lead or Contacted moves them to In
conversation, a reply sent from the board moves Lead to Contacted, and nothing
walks a stage back. A contact form enquiry from anyone who is not a client
finds their lead (address, a lead person's address, the lead's email domain or
website host) or writes one, with the enquiry as a touch; later mail from that
address is logged on the lead the same way. Mail filed to nobody is filed to a
client added afterwards on the next sync, without moving their stage.

**A converted lead has one stage, the client's.** It was pinned at In
conversation for good. A `before_flush` listener in `models.py` moves the lead
whenever its client's stage changes, whatever moved it, and the stage picker on
a converted lead moves the client. Migration `c6d2e8a41f97` caught up the leads
already converted.

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
touching anything else; the bootstrap runs it.

**Time logs itself** (audit item 3, 2026-11-04). The fourth hook, SessionEnd
(`session_end.py`), reads the transcript's timestamps into stretches with no gap
over 15 minutes, finds the repo with git (a worktree answers with its main
repo), and posts the stretches to `/api/guidance/time` with the session id.
`session_time.py` maps the repo to `Project.repo` or a tile's `github_url`,
skips Michael's own (his own client row, a business, a tile under Personal
projects), picks build or maintenance from the phase and go-live date, rewrites
its own entry on a re-run (`TimeEntry.session_ref`, unique), never touches an
invoiced one, and keeps the stretches (`spans_json`) so sessions open side by
side on one project bill an hour once. It skips a session that called log_time
itself, and the Stop hook no longer asks for time, because two entries for one
session bill the hour twice. What each run did is in
`~/.claude/pm-guidance/session-time.log`. `tools/test_session_time.py` runs the
real script against a live server. Hooks print UTF-8 on
purpose - Windows hands them cp1252 and one minus sign in a rule killed
the injection after its header.

**The issues board is in context too** (2026-11-05). The fifth hook, a second
SessionStart (`session_issues.py`), prints the checkout's GitHub repo, the
issues labelled `in progress` with who holds them, and the open count, so a
session sees what is claimed before its first edit (the section at the top of
this file, and the catalogue rule). It is its own hook rather than more lines
under the brief because Claude Code keeps about 10,000 characters of each
hook's output and the brief is held just under that; `install.py`'s EVENTS
takes a list per event for that reason. It prints nothing outside a GitHub
checkout and one line when gh is missing or the board does not answer.

## The sweeper

`sweep_repos.py` runs after `sync_costs.py` in the same nightly cost-sync
service. It reads the CORE repos, those pushed to in the last `CORE_DAYS`
(120; GITHUB_TOKEN on that service for private ones), splits each
CLAUDE.md into headed sections, and files any section that is new or
whose body changed as a curator candidate (`_propose(..., hold=True)`).
`RepoWatch.seen_json` maps each heading to a fingerprint of its body; a
row from before fingerprints holds a bare list, which is fingerprinted
silently on the next read rather than refiling every section. The first
read of a repo only records, so nothing mined by hand comes back. The
nightly audit reads the same core list.

## Cerebro (page retired)

Retired into Best Practices on 2026-11-02: `cerebro.index` redirects there
and the sidebar link is gone. The nightly audit still runs and still fills
`RuleAudit` and `ProductAudit`; nothing draws them until a page earns its
place. What follows is what the page was, and what the scanners still are.

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

## Org (was Team)

Michael, 2026-11-04: "Team I want this to be renamed to org and place where I
can see all my orgs for each business. steal from the entertain hq admin org
site and ensure that org pages communicate properly between apps."
`/admin/org` (`pm/org_routes.py`, logic in `org_service.py`, CEO only) is one
tab per company, then **Logins**, which is the old Users page
(`users_bp` now under `/admin/org/logins`, endpoint names unchanged;
`/admin/users` answers 301 for a GET and 307 for its four write shapes). Each
business has EntertainHQ's four views (People, Org chart, Responsibilities,
Departments) plus who owns what.

**Only companies have an org** (Michael, the same evening: "orgs should only be
on primary businesses not dba. So built by bean and entertainhq are the only
ones that have actual orgs"). A DBA's people are its company's: no tab, and
`org_service.org_businesses` holds for any DBA added later. A DBA's org
addresses answer 301 to its company's (a save, 307); a DBA's own app's hub
calls read and save its company's org (`org_home`). A business made a DBA on
its edit page carries its org onto its company's in the same save
(`fold_into_parent`: a department by name or a person by email, else name,
that the company already has is the same one) and the flash says what moved.
Nothing had been put on either DBA's org when this landed.

The sidebar link sits after Client support;
the Team section is gone. Icon concept `org` (EntertainHQ's three boxes).

His picks, one per question:
- **The board is the one store** for every business's org (`OrgPerson`,
  `OrgDepartment`, `org_person_depts`, `OrgResponsibility`, `OrgState`), the
  way it is for sales tax. EntertainHQ's admin Organization page is to read and
  save the same rows over the hub: `POST /api/hub/org` (the org, and the app's
  logins if it sends them), `/api/hub/org/save` (one change, the same body the
  board's own form posts) and `/api/hub/org/import` (its rows, once). Signed
  per business like the tax and books doors.
- **A save names the version it read** (`version` on every row). A stale one
  is refused from either door ("changed since you opened it"; the hub answers
  409 with the org as it is), so neither side writes over an edit it did not
  see. The person page and every row sit in live regions so a save brings the
  new version in; two saves in a row is a test.
- **The import** is keyed by the app's ids (`app_ref` "entertainhq:12", per
  table: person 3 and responsibility 3 are different rows) and applies only to
  an empty org or over an earlier import nobody has edited since
  (`can_import`). EntertainHQ's live org (3 people, 9 departments, 114
  responsibilities) came over on 2026-11-04 through the god door
  (`/api/guidance/org/import`), read from its D1 by a session, because this
  repo is public and those rows do not belong in a file here.
- **Shares are the board's** (`BusinessOwner`, now with `person_id`, linked by
  name). A share is typed on the person page or on Books; the hub never takes
  one. A DBA has no owners of its own and shows its company's.
- **Logins are each app's own.** An app reports its list on each call
  (`OrgState.app_logins_json`); a person holding one cannot be taken off the
  chart from either door. The board's own logins are the Logins tab, and each
  person says which board login matches their email.

EntertainHQ's half (switching its D1 page to these doors, then its import) and
Data Dungeon's (a door of its own) are gaps on their blueprints, not code here.
`tools/test_org.py`, and `tools/test_org_browser.py` measures every Org page at
320, 375 and 1600, the kept tab rows, an open picker and saving in place.

## Users

`pm/users_routes.py` (Org's Logins tab since 2026-11-04), CEO only, guarded on the route by `ceo_required`
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

**The trades that sell labour were missing, and the count said so.** On
2026-10-03 the owner spoke to a painter in Powderly and found him absent. The
board listed EIGHT painting businesses for a three county trade area, beside
Trucking at 625 and Health practices at 556 - and those two numbers are the
tell, because they are the two sources that publish a register (FMCSA, CMS).
A painter sells labour: no sales tax, so not on the permit spine; painting is
not licensed in Texas, so no TDLR row; one van, so no map. The franchise file
holds them and was downloaded only to ENRICH, on the rule that "a registration
proves an entity exists and nothing more". True of shells, false of trades.

`trade_in_the_name` is the cheap half of evidence of trading: nobody registers
a holding entity as "SIMMONS PAINTING LLC". A registration whose own NAME
declares a trade creates a lead; one that declares nothing still does not.
Measured against the live board, that is **180 businesses** the list did not
have: 40 concrete and welding, 25 plumbing and electrical, 19 building trades,
15 cleaning and landscaping, 10 painters.

It is kept deliberately narrow, because the same file holds PAINTED WIND
RANCH, PAINTER FIREARMS TRAINING INSTITUTE and NETA PAINTER, CPA. Only the
-ING form and the unmistakable compounds, matched on whole words, with a veto
list of words that name a different business (ranch, cpa, holdings, realty,
minerals). A wrong name on a call sheet is worse than a missing one, because
somebody reads it out. The create pass runs LAST, after the carrier census,
the maps and the licence files, or it would invent eighty hauliers the FMCSA
was about to supply.

**And a sole trader is in no state file at all** - no company, so no franchise
tax either. The painter is one: real, trading, with a website and a telephone,
and in neither Comptroller file. No source change reaches him, so
`leads.lead_add` is the way to type one in. It builds `dedupe_key` with the
import's own `norm` and `street_key`, IMPORTED rather than copied, so a later
import folds into that row instead of writing the business twice; it records
the source as `typed`, which is what stops the loader overwriting it; and a
website typed by hand stamps `website_checked_at`, because somebody has just
looked. A row with no website typed stays NULL and must not read as "no site
found". `tools/test_lead_holes.py`.

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

**The list refreshes itself weekly** (`leads_refresh.py`, a step of the
nightly cost-sync job, audit item 17). It is asked every night and runs when no
night in the last 6.5 days finished it, so a failed week is retried the next
night: the import without its per-site email scrape, then `check_websites` on
rows never checked (the new ones, capped at `CHECK_CAP`), then `enrich_sites`
on the rows that check just stamped (`since`), so a site that failed to read is
not fetched every week. cost-sync has no DuckDB, so it runs without Overture.
That made the import's prune dangerous: it deleted every unworked lead no
source held this run, so a run without Overture would delete every lead only
Overture supplied, which it did once to 4,640 places. `import_leads.run` now
prunes only when every source answered, keeps an unread source's marks on its
rows (`check_websites --reguess` reads the overture mark), and names the unread
sources in the night's record. `LEADS_REFRESH_FORCE=1` runs it now;
`LEADS_REFRESH_DISABLED=1` stops it. `tools/test_leads_refresh.py`.

## Contracts, and clearing the tests off the list

`pm/contract_routes.py`. The overview carries two presses per row and only
ever one at a time. **Void** is the real thing: it reaches the portal, kills
the signing link, and asks first. **Hide** is local tidying: `archived_at` on
`SignatureRequest`, nothing sent, nothing deleted, the row and its sealed PDF
still on their own page, and one press to put it back, so it does not ask.

A contract still OUT for signature cannot be hidden. A live signing link
nobody is watching is the one thing a tidy-up must not leave behind, so those
offer Void and not Hide, and the refusal says to void it first. The tiles
count what is on the screen rather than the table, and the toggle says how
many are hidden.

The one place a failure is allowed to settle a row is a **404 from the
portal**: that envelope does not exist, so nothing is out for signature, and
the row is marked voided here with a flash saying nothing was sent. That
matters because the test rows pointed at envelopes wiped long ago and were
otherwise stuck as "sent" for ever, unhideable. Every other failure changes
nothing, above all a network one - a portal that did not answer has agreed to
nothing - which is why `SignaDocError` now carries the portal's own status
code and `None` when it was never reached. `tools/test_contract_tidy.py`
proves both halves.

## A contract does what it says when it is signed, not sent

Audit item 6, 2026-11-04. The SOW wrote the client's stage and contract revenue,
and the project's fee, budget, dates and phase, as it was SENT; a hosting
agreement wrote its fee the same way. A decline or a void took none of it back,
and the package, its products and the lead were moved by hand once somebody
noticed. `contract_effects.py` is the one place it happens now. The form builds
a proposal (`sow_effects`, `hosting_effects`) and `create_request` keeps it on
the request (`effects_json`). Sent moves the client and their lead to "proposal
sent", forward only. `completed` (`_apply` in `pm/contract_routes.py`) applies
it once: client and lead to contracted, the project made if it does not exist
(with the default runbooks), its fee, budget, delivery date and window, the
package to contracted and its products written as `ProductSale` rows with their
runbooks. A declined or voided one puts back what `undo_json` saved, unless the
record has moved on or another contract for that client is out or signed. A
contract downloaded to sign on paper applies as it is downloaded
(`apply_if_paper`), because there is no envelope to report back.

`_apply` moves the status with a compare-and-set and `apply_signed` claims
`effects_applied_at` the same way, because every gunicorn worker runs the
signature watcher (`start_signature_watcher`, every 15 minutes,
`SIGNATURE_REFRESH_SECONDS`, 0 is off, audit item 4) and two of them see the
same completion. The watcher sleeps first, so a boot asks nothing. Rows sent
before this have no proposal and are left alone. `tools/test_signed_not_sent.py`.

## The revenue share, which is not a partnership

`contract_docs.build_partnership`, the form at `/admin/contracts/new/partnership`,
`kind='partnership'`. The deal it papers: Michael and somebody who knows an
industry take a product to market together and split what it earns. EntertainHQ
with Kenali Kendrick is the first. He calls it a partnership, the board's button
calls it a Revenue share, and the DOCUMENT calls itself a Revenue Share
Agreement, because Texas creates a general partnership out of conduct rather
than intent (TBOC 152.051) and a share of profits is one of the factors. A
general partner is jointly liable for the other's debts, owes fiduciary duties,
and can bind the business by signing something. Section 2 therefore negates
every factor a court weighs - no capital, no losses, no control, no property in
common, no authority to bind - and says the word "partner" is a commercial
description. `PARTNERSHIP_NOT` is that list and it is kept whole: it is only as
good as its completeness.

Two things about the money are chosen before the document exists, because they
are worth thousands of dollars apart on the same revenue and cannot be fixed by
reading afterwards. The basis (`SHARE_BASES`) is a share of Net Profit or a
commission on Gross Receipts, and each document says in terms that it is not the
other. The scope (`SHARE_SCOPES`) is everything the Venture earns or only
customers the Partner introduced. Net Profit names its deductions as a list, and
Built by Bean's own time is NOT among them unless a rate is typed in, because a
deduction list that quietly swallows general overhead makes a 35% share of
nothing.

"She is paid once I am paid, not before" is Section 5 and it is the one callout
on the document: nothing is earned on an invoice, a promise or a signed order
until the money has arrived and cleared, there is no advance or draw, and a
refund that lands after payment comes back out of the next one.

`PARTNERSHIP_PROTECTIONS` is NOT `STANDALONE_PROTECTIONS`, and the comment on it
says why: that list is written for a document where the client pays, so it
carries a $50 per day late fee - which here would run against Michael - and a
liability cap measured on fees the Client paid, which in a document where the
client pays nothing evaluates to zero. `THIRD_PARTY_TERMS` and `GOVERNING_LAW`
are the clauses that genuinely do not care who pays and are shared constants
rather than copies, spliced back into `STANDALONE_PROTECTIONS` at their original
positions so no existing document changed a word. Catalogue rule "Shared
boilerplate carries a direction of payment".
`tools/test_partnership_contract.py` asserts the late fee is absent here and
still present on the SOW, so re-merging the lists fails loudly.

Ownership is its own clause (`PARTNERSHIP_OWNERSHIP`) rather than `IP_TERMS`,
because IP_TERMS is framed around a delivered application, a build fee and a
license to use it, and none of those exist when nobody is buying anything. What
this one has to nail down instead is that a share of the money is not a share of
the thing: the Venture is Built by Bean's outright, what the Partner contributes
is assigned as it is created, and a SALE of the Venture is not a Gross Receipt,
so no share is payable on the proceeds. It also says outright that it does not
replace the Partner's own Statement of Work, because the first partner is
already a client with one.

This is the only document that may wear a look of its own: `accent` (a hex off
the form, parsed by `contract_style.rgb`, which falls back rather than raising)
and `mark_path` (an icon already on the volume for an app on My Apps, drawn
through `ContractPDF.mark`, which returns False rather than raising on an .ico,
an SVG fpdf cannot parse, or a file that is gone). A contract that renders
without a logo is a contract; one that 500s while somebody is waiting to send it
is not. The logo is picked from My Apps rather than uploaded because a file
uploaded into the form would not survive the preview: pressing Send replays the
form, and a browser does not re-send a file it was never given again.

The terms of one of these will change. That is why it is a form: regenerate it,
do not edit a PDF, and `form_json` plus `FORM_ENDPOINTS['partnership']` mean
Revise reopens it filled in as it was sent.

## Hosting fees that raise themselves

`pm/hosting_routes.py` holds every priced project's fee against last
month's cost. Under `MIN_MARGIN` ($25 left over) the page offers "Draft
the increase": one link that opens the hosting agreement form filled in
as a fee update - the fee `RAISE_STEP` ($25/month) higher, the fee it
cancels, the first of next month as the start, the reason - and what is
left is reading it and sending it through the normal signing flow. The
sidebar badge on Hosting is that count, cached ten minutes. The fee only
lands on the project when the agreement is SIGNED (or downloaded to sign on
paper), through the same route as every hosting agreement; until then the
row keeps offering the draft, so check Contracts before drafting a second. `contract_docs.HOSTING_LAPSE` is the clause
that says what the fee is for and what stops when it stops being paid -
read into the SOW, the standalone agreement and every fee update from
that one place, so no two documents can describe it differently.

Hosted free is its own band and NOT a loss. It was a loss once, so Robinson &
Co., hosted free at $0.00 and costing $0.00 to run, was counted on the Needs a
look tile and in the sidebar badge while its own row said "Hosted free" and
offered no press: the page asked to be looked at and had nothing to show. A
free project becomes a loss the moment it actually costs something, because
free to the client never meant paid for out of pocket, and then it offers the
same draft as any other row ("Put it on $25.00/mo"). That press had to move
out of the bar's `{% if %}`, which is gated on there being a fee to measure
against. `tools/test_hosting_bands.py` walks all five bands and asserts the
tile, the sidebar badge and the number of draft links are the same number -
the badge agreeing with the tile proves nothing on its own, because both read
the same wrong function.

## Who owns what

`contract_docs.IP_TERMS` is the one place the ownership words are written,
and the Statement of Work (Section 9), the engagement letter (Section 5)
and the standalone protections on the add-on, hosting and addendum
documents all read it. Before 2026-09-09 each of the three carried its own
copy, and the SOW's said Built by Bean "retains the right to reuse the
underlying code in other work for other clients", which is true and much
narrower than what the business needs: the code is Built by Bean's outright,
and Built by Bean may reuse it, package it, or sell a product built from it
to anyone, owing the client nothing. What the client buys is a perpetual
license to use their application with no renewal and no recurring license
fee. Hosting is the only recurring charge, it is not a license fee, and a
lapse suspends access without ending the license. Their data is theirs and
exportable on request. Two things the terms deliberately leave as they
were, because they are Michael's to decide: the license is non-transferable
(it does not follow a sale of the client's business without his consent),
and the client is not handed the source code.

The website says only what the contract says. It used to promise "pay once,
then use it for as long as you like" with no mention of the hosting fee
that the contract makes a condition of access, which is exactly the
"stop paying and it switches off" the same page was criticising. The one
recurring charge is now named on the page, "full support" became the
maintenance window the SOW actually grants, and the footer names the LLC
that signs the contracts. When the copy on the site or the words in a
contract change, read the other one again.

`scratchpad/contracts_check.py` (in the session scratchpad, worth keeping)
renders all five documents through the routes the board uses and reads the
PDFs back with pymupdf, asserting the sentences that matter appear in every
one, appear once, and that no words from the retired clauses survive.

## The shell does not move

`bbbSwapLive` said the principle for one page in 2026: "Re-rendering a region
that did not change is not a harmless no-op - it destroys all three." It was
applied to actions INSIDE a page and never to the step between two of them, so
pressing Expenses and then My Apps threw away and rebuilt the whole shell: the
sidebar and its scroll position, the drawer on a phone, the banner, the running
timer, and every entry animation played again. The owner's verdict, 2026-09-16:
elements that are not changing do not need to refresh.

`bbbNavigate` (bottom of base.html) swaps instead. What moves between two pages
of this board is `#pm-page-title`, `#pm-page-subtitle`, `#pm-back`,
`#pm-actions`, `#pm-main`, the flash strip and the two sidebar counts. What does
not move is everything else, and the sidebar in particular is NEVER replaced:
one class comes off one link and goes onto another, which is all "you are here"
ever was. The timer sits between `#pm-back` and `#pm-actions` for that reason -
it is counting, and rebuilding a running clock because somebody opened another
page is the complaint in miniature. A GET form is a navigation too and swaps
the same way; POST is left alone, and the forms that must act without a reload
already say so with `data-live-action`.

It falls back to an ordinary navigation at every point it cannot be sure, and
the board works with the script deleted: a response that is not text/html, one
without this shell (the login redirect is the one that matters), a failed
fetch, a modified click, `download`, a `target`, another origin, anything
outside `/admin`, and anything that looks like a file. Verified: a `.pdf` and a
link to `/Bible-Study` both still load as documents.

Two mechanics that are silent when wrong. **A `<script>` inside replaced markup
does not run** - the parser marks nodes created that way as already executed -
so each one in `#pm-main` is re-created, which is what makes the contract
forms' inline `revisionPrefill` survive a swap. And a second press while the
first is in flight would otherwise land last and show the page nobody asked
for, so a token is carried and the newest press wins.

`tools/test_shell_stays_put.py` drives a real browser, because nothing else can
test this: after the dust settles the page is correct either way, and every DOM
assertion, accessibility tree and screenshot samples the settled state. It
stamps a property on the shell elements from JavaScript, navigates, and asserts
the stamp is still there - which a server render cannot reproduce, so it can
only pass if those very elements survived. Catalogue rule "Only the part that
changed is allowed to change", which carries the five reasons this keeps
getting missed.

## The night has no volume

Railway mounts a volume on ONE service, and `/data` is the web service's.
cost-sync runs every nightly step with no volume at all, so until 2026-11-05
whatever it wrote (icons re-fetched by tile upkeep, receipts from the
mailboxes, Stripe fee statements) went onto its own throwaway disk while the
database took the new names, and the website answered 404: ten My Apps icons
blank the morning after tile upkeep first ran, and two receipts gone. Every file
write goes through `volume_files.write`: local where `RAILWAY_VOLUME_MOUNT_PATH`
is set (or off Railway), otherwise a `VolumeInbox` row in the same transaction
as the name it stands for, which the web's timer (`start_background`, web only)
moves onto the volume within a minute. The same timer runs `heal_here`
(`pm/files_door_routes.py`, also `POST /api/guidance/files/heal`) at boot and
daily: a fetched icon whose file is gone is fetched again, an uploaded one
clears to its letter, a receipt row pointing at nothing is let go so the next
mail read takes it in again, and its expense goes back on Missing. A new
`open(..., "wb")` under UPLOAD_FOLDER anywhere a nightly step can reach is the
regression. `tools/test_volume_files.py`.

## House rules

- **Nothing behind the login is cached.** Cloudflare caches by what a URL ends in
  (.csv, .pdf, .zip and so on) and knows nothing about logins, so a route like that
  with no cache header is public from the moment somebody signed in opens it. On
  2026-11-03 the books export for both companies came back 200 to a request with no
  cookies. `nothing_behind_the_login_is_cached` in `app.py` marks everything under
  `/admin` and `/api/` `private, no-store`. A new route ending in a file extension
  outside those prefixes has to say the same. `tools/test_nothing_cached.py`.
- **Phone first.** Design at 375px and let it grow. Nothing scrolls the page
  sideways, nothing overflows its card, every tap target is at least 44px
  (base.html enforces that below 640px on every button, every link styled
  as one, and every icon press; a control that must be smaller has to
  argue with that rule, not merely forget it). A native `<select>` can be
  rendered by WTForms (`form.field()`) as well as typed, and the LM-2 grep
  cannot see that one: a picker in a form template is `select_dropdown`
  fed `form.field.choices`.
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
- **A page fills the screen.** The first element of a page's content block
  carries no `max-w-*` and no `mx-auto`: on 2026-11-04 twenty-nine pages sat in
  a narrow column hugging the left with half the screen empty, and Michael
  asked for them to fill it. Spread wide screens with grids that add columns;
  only a paragraph of running prose may be held to a reading width. Check at
  1600px as well as 375px.
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
  the screen. Never reuse one icon for two things: every icon is
  `icon('concept')` from the Handbook's vocabulary, and a concept that is not
  there is added through the door before it is drawn.
- **Migrations:** name every constraint, guard every create_table on the
  table not existing (create_all runs on boot and wins the race), drop
  children before parents, and run `flask db downgrade <prev>` then
  `flask db upgrade` before pushing. SQLite accepts orderings Postgres
  refuses, and Postgres performs newline string-literal concatenation in SQL
  that SQLite refuses - use bound parameters for any multi-line text. The whole
  chain does not run from an empty SQLite file (it stops on an old `task_id`
  migration), so to do that check let the app build the tables, `flask db stamp
  head`, then go down and up, with `DATABASE_URL` on a temp file.
- **A pushed commit is not a deployed commit.** Check
  `railway deployment list` for SUCCESS on the new deploy, then verify
  against the public URL, never the container.
- **An expression built from `|tojson` goes in a SINGLE-quoted attribute.**
  `|tojson` escapes `<`, `>`, `&` and `'` and leaves `"` alone, so
  `x-show="{{ list|tojson }}.includes(x)"` ends at the first double quote it
  writes. It shipped as `x-show="["`, Alpine threw on every row, and the
  buttons that record how a call went were never once on the screen, and a
  second one hid behind a `!` on the providers form. Grep the whole value:
  `rg -n '="[^"]*\{\{[^"]*tojson' templates/`.
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
