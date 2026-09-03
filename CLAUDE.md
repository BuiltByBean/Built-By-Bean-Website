# Built By Bean - website + project manager

This repo serves builtbybeans.com and the live PM at `/admin`. Flask +
SQLAlchemy + Alembic, Jinja + Tailwind + Alpine, Postgres on Railway in
production, SQLite locally. Pushing to `main` deploys.

The feature catalogue at `/admin/features` is the CROSS-REPO lesson store:
when any project teaches a lesson, it goes there (pitfalls_md) as well as
here. This file is for lessons about THIS repo's own code.

## House rules

- **Phone first.** Design at 375px and let it grow. Nothing scrolls the page
  sideways, nothing overflows its card, every tap target is at least 44px.
  Verify with `getBoundingClientRect()`, not by looking.
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

**Grep.**
```
rg -n "<select" templates/pm --glob "!components/*"
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
