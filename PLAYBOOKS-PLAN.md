# Third party playbooks: a tile dashboard in the PM admin

## Where this goes, and where it must not go

Build in this repo, `Built-By-Bean-Website` (GitHub `BuiltByBean/Built-By-Bean-Website`).
It serves builtbybeans.com and contains the live project manager as the `pm`
blueprint at `/admin/pm`.

**Do not build in `~/Documents/Apps/Project-Manager`.** That repo is superseded
and has not deployed since April 2026. Its README says so explicitly, because on
2026-08-29 a whole ticket-board build landed there before anyone checked which
repo served traffic. Read that README first if there is any doubt.

Migration head in this repo is `f3a90d21c8b7`. If you see `c7e1f2a93b40` you are
in the wrong repo.

There is **no CLAUDE.md in this repo**, so the conventions at the bottom of this
plan are not written down anywhere in it yet. Follow them anyway.

## The goal

One screen of vendor tiles with logos. Click a tile, get the operational runbook
for that vendor: what only the client can do, the one-time access grant that ends
the back and forth, what I do once I have access, the traps, and how to verify.
The point is never researching or failing at the same vendor twice.

## What already exists to build on

- `pm` blueprint registered in `app.py` around line 52 with
  `url_prefix="/admin/pm"`, and at line 2737.
- Sub-blueprint pattern to copy: `pm/service_costs_routes.py`, which declares
  `Blueprint("service_costs", __name__, url_prefix="/admin/pm/service-costs")`
  and is registered in `app.py` around line 226 with a local import inside the
  app factory. `pm/stripe_routes.py` is the same shape at line 222.
- `models.py` already has `ServiceProvider` (line 619) and `ServiceMapping`
  (line 642), which joins a provider to a client and a project. `PROVIDER_TYPES`
  in `pm/service_costs_routes.py` already lists aws, railway, twilio, cloudflare.
- Nav lives in `templates/pm/base.html`, lines 259 to 340. Tailwind classes.
- Templates go under `templates/pm/<section>/`, e.g. `templates/pm/service_costs/`.
- `static/pm/` currently holds only fonts.

## Data model

New table, not columns on `ServiceProvider`. `ServiceProvider` rows exist only for
vendors being cost-synced, carry `credentials_json` and sync state, and have
cascade deletes. Stripe is not even in that list. Editorial content does not
belong on it.

Add to `models.py`:

    class Playbook(db.Model):
        __tablename__ = "playbooks"

        id, slug (unique), display_name, logo_path, vendor_url
        is_active, sort_order
        one_liner              # what it is for, one sentence

        client_only_md         # what only the client can do, and why
        access_grant_md        # the one-time grant that ends the back and forth
        your_steps_md          # what I do once I have access
        traps_md               # dated, each from a real failure
        verify_md              # how to prove it works from outside

        service_provider_id    # nullable FK to service_providers.id, SET NULL
        created_at, updated_at

Fixed fields rather than a generic sections table. The consistent five-part shape
across every vendor is the entire value, and fixed fields enforce it without
building a section editor. Markdown in each, rendered on read.

Nullable FK to `ServiceProvider` so Railway and Twilio can link to their
cost-sync rows while Stripe, which has no such row, still gets a playbook.

Migration rules: name every constraint, drop children before parents, and run
`flask db downgrade <prev>` then `flask db upgrade` before pushing. SQLite
accepts a bad ordering that Postgres refuses, so a local pass proves nothing on
its own.

## Routes

New file `pm/playbooks_routes.py`,
`Blueprint("playbooks", __name__, url_prefix="/admin/pm/playbooks")`, registered
in `app.py` alongside the other two. All views `@login_required`.

    GET  /                    tile grid
    GET  /<slug>              the runbook
    GET  /new, POST /new      create
    GET  /<slug>/edit, POST   edit
    POST /<id>/delete         delete

## Templates

`templates/pm/playbooks/index.html`, `detail.html`, `form.html`, extending
`templates/pm/base.html`. Add a nav entry after the service_costs link at line 333.

Index is a responsive grid of tiles: logo, display name, one_liner, and a
"last updated" date so a stale playbook is visible as stale. Detail renders the
five sections as headed blocks in the order above, with an edit action on the
trailing edge.

Logos go in `static/pm/logos/<slug>.svg`. Vendor marks are trademarked but this
is an internal admin tool, which is fine. Fall back to a monogram tile when
`logo_path` is empty, so a new vendor is usable before anyone finds its SVG.

## Seed content, which mostly already exists

The source material is in a **different repo**: `~/Documents/Apps/KuperPlumbing`.
Read it there, do not move it.

**Stripe** from `docs/stripe-setup.md` and the Webhooks section of `CLAUDE.md`.
Add what was learned on 2026-08-31, none of which is written down yet:

- The client invites you as a **Developer** on their Stripe team. After that you
  never need them again for keys, rotations or debugging, and their passkey stops
  being your problem. This is the single highest value line in the whole build.
- Live mode webhooks are a **separate endpoint with a separate signing secret**
  from test mode. Swapping keys and keeping the test `whsec_` charges cards and
  refuses every event, so money lands in Stripe and invoices sit unpaid.
- A restricted key scoped to Checkout Sessions write is enough for a
  hosted-checkout integration, and limits a leaked environment to creating
  checkout pages instead of reaching payouts and refunds. Open question worth
  recording once tested: whether inline `price_data` also needs Products or
  Prices write.

**Twilio** from `docs/twilio-a2p-registration.md` (587 lines) and
`docs/a2p-playbook.md` (415 lines). Two documented successes to generalise from.

**Cloudflare** from the Deploys section of `CLAUDE.md`. The email obfuscation trap
belongs in traps: it rewrites every `mailto:` into a `/cdn-cgi/` link that only
JavaScript decodes, so the page looks right in a browser and carries no readable
address for anything that does not run JavaScript, including a carrier reviewer.

**Railway** from `docs/RAILWAY.md` plus the Deploys and Secrets sections of
`CLAUDE.md`. `railway status` reads Online throughout a deploy, `railway logs`
defaults to the last successful deployment rather than the failed one, and
`railway variables` prints resolved values including the Postgres password inside
`DATABASE_URL`.

The judgement call throughout is which lines are about the vendor and lift out,
versus which are about Kuper Plumbing and stay put.

## Scope

In: the model, the five routes, the three templates, nav, and the four playbooks
above seeded.

Out of v1, worth building next: per-client checklist state, so "which of my
clients have granted me Stripe team access" is answerable. `ServiceMapping`
already joins providers to clients, so the join is half there. Leave it until the
content layer is real.

## Conventions, since this repo does not state them

- Phone first. Design at 375px and let it grow. Nothing scrolls the page
  sideways, nothing overflows its card, every tap target is at least 44px. Verify
  with `getBoundingClientRect()`, not by looking.
- Text alone is never a button. Anything that acts on press gets a border or a
  fill and usually an icon. Actions sit on the trailing edge.
- No em dashes anywhere, product copy and commit messages included.
- Never reuse one icon for two things.
- Stack, do not pair, inside an already indented card.

## Done means

Migration runs down and up cleanly. `/admin/pm/playbooks` renders four tiles, each
opens a runbook with all five sections populated. Nav entry present. Checked at
375 wide with geometry. Pushed to main, then confirm this repo actually redeploys
on push before claiming it is live.
