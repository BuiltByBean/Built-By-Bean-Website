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
them. The write path appends with attribution and refuses duplicates,
because reporting sessions retry like any other API client.

The catalogue grows itself through the same door, with the policy set by
the SHAPE of a change, not by trust in the sender. Everything a session
sends becomes a `CatalogueProposal` (`pm/guidance_routes.py`, the
`suggest_update` tool): an append or a create applies on arrival and can
be reverted from `/admin/features/inbox` in one press; a replace of
existing words waits there as pending and touches no build prompt until
accepted. `previous` is snapshotted at apply time so revert is exact.
Sessions may also file operational records - `upsert_project`,
`log_expense`, `log_time`, `register_hosting_resource` - and may NOT
contact a client, resolve a ticket or send a contract: those are
Michael's, and the API has no route for them on purpose.

## Needs attention

`pm/attention_routes.py` is the one page that says what the board has
noticed is waiting on Michael - contracts a client sent back, hosting
fees under the floor, invoices past due, catalogue rewrites waiting on a
yes, tickets untriaged or flagged, builds past their promised date with
no go-live - worst first, each row carrying the press that resolves it.
Its own nav section, top of the sidebar, with the total as the badge
(`attention_counts()` in the context processor). A page that learns to
notice something new adds it HERE, not a badge of its own; the inbox
decisions take `next` so a press on this page comes back to it.

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
  `documentElement.scrollWidth <= clientWidth` - and seed the fixtures with
  LONG strings and a long URL first, because short seed data hides all four
  of the causes found this way: a `flex-1` input with no `min-w-0` (its
  min-width is its placeholder's intrinsic width), a `truncate` span with no
  `max-w-full` on the flex parent to ellipsis against, a pill row that
  cannot `flex-wrap`, and a long URL in rendered markdown, which overflows
  as a TEXT node so every element box still measures inside the viewport. A
  wide table is fine inside its own `overflow-auto` container: the table
  scrolls, the page does not.
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
full height of the viewport on a page that is one filtered list.

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
like the MVP builder - keeps page scroll, and its bar uses
`.sticky-filters`: flush under the measured header (`--pm-header-h`, from
the ResizeObserver - never hardcoded, headers wrap), backed SOLID by the
class (`var(--surface)`), with no Tailwind bg utility beside it because
the CDN sheet loads later and wins the cascade back to translucent.

Verify by scrolling, whichever tier: on contained pages
`document.documentElement.scrollHeight <= innerHeight` while the inner
scroller's `scrollHeight` exceeds its height; on sticky pages the bar's
top equals the header's height exactly, and probes behind the bar
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
