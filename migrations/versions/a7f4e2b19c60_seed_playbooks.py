"""the first four runbooks

Stripe, Twilio, Cloudflare and Railway, lifted out of KuperPlumbing's docs and
generalised. What was about Kuper stayed there; what was about the vendor came
here. Client names, real SIDs and one real street address were all left behind
on purpose: this is a runbook, not a record of an engagement.

Seeded as a data migration rather than a script somebody has to remember to
run, because the deploy already runs `flask db upgrade` and a screen of empty
tiles is how a feature gets written off in its first five minutes.

Idempotent by slug, so a re-run adds only what is missing and never overwrites
an edit made in the admin.

Revision ID: a7f4e2b19c60
Revises: e5c8b71d3f92
Create Date: 2026-08-31 10:30:00.000000

"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = 'a7f4e2b19c60'
down_revision = 'e5c8b71d3f92'
branch_labels = None
depends_on = None


# A local, minimal table definition rather than the ORM model. A migration has
# to keep describing the schema as it was on the day it was written, and the
# model will not.
playbooks = sa.table(
    "playbooks",
    sa.column("slug", sa.String),
    sa.column("display_name", sa.String),
    sa.column("logo_path", sa.String),
    sa.column("vendor_url", sa.String),
    sa.column("is_active", sa.Boolean),
    sa.column("sort_order", sa.Integer),
    sa.column("one_liner", sa.String),
    sa.column("client_only_md", sa.Text),
    sa.column("access_grant_md", sa.Text),
    sa.column("your_steps_md", sa.Text),
    sa.column("traps_md", sa.Text),
    sa.column("verify_md", sa.Text),
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
)

SEEDED_SLUGS = ("stripe", "twilio", "cloudflare", "railway")


STRIPE = {
    "slug": "stripe",
    "display_name": "Stripe",
    "logo_path": "pm/logos/stripe.svg",
    "vendor_url": "https://dashboard.stripe.com",
    "sort_order": 10,
    "one_liner": "Card payments taken on the client's own account, with keys you hold and can rotate.",

    "client_only_md": """
Only the client can do these, because it is their business taking the money.
Asking for them early is what keeps the rest of the build from stalling.

1. **Create the Stripe account** in the exact legal entity name. Not a personal
   account, not yours.
2. **Give Stripe the EIN, the business address and the bank account** to pay
   out to.
3. **Complete the identity check.** Stripe will not release live keys until it
   passes.

You cannot do any of this on their behalf and should not try. A tax ID does not
belong in a repo or a transcript either: it goes in a password manager and
nowhere else.

**Stay in test mode until everything below is done.** An app with no keys is
not broken, it just has no pay button, and the invoice can tell the customer to
ring instead. That is an honest state to sit in for as long as it needs to.
""".strip(),

    "access_grant_md": """
**Ask the client to invite you as a Developer on their Stripe team.**
Settings, Team and security, Members, Invite.

This is the single highest value line in this playbook. Once it is done you
never need the client again for a key, a rotation, a webhook or a debugging
session. You read live keys yourself, you add the endpoint yourself, and you
see the actual event log when something fails.

Without it, every one of those is a phone call in which you talk somebody
through a dashboard you cannot see, and their passkey becomes your problem the
first time it does not work.

Ask for it in the same message as the account setup, not after the first time
you get stuck. The grant is one click for them and it is much easier to get
before anybody is frustrated.
""".strip(),

    "your_steps_md": """
**1. Take the keys.** Developers, API keys.

    STRIPE_PUBLISHABLE_KEY   pk_test_... then pk_live_...
    STRIPE_SECRET_KEY        sk_test_... then sk_live_...

**2. Add the webhook**, which is the part that actually records money.
Developers, Webhooks, Add endpoint.

    URL     https://example.com/api/stripe/webhook
    Event   checkout.session.completed

Stripe then shows a signing secret, once:

    STRIPE_WEBHOOK_SECRET    whsec_...

**3. Set all four on the host by hand.** The secret key and the webhook secret
are secrets in the strict sense: they never go through a tool that logs and
they never appear in a transcript.

**4. Gate the pay button on all four being set**, webhook secret included. Not
three of four. See the first trap.

**5. Consider a restricted key.** A key scoped to Checkout Sessions write is
enough for a hosted checkout integration, and it limits a leaked environment to
creating checkout pages instead of reaching payouts and refunds.

**6. Repeat the webhook step for live mode.** It is a different endpoint with a
different secret. See the second trap.
""".strip(),

    "traps_md": """
**Three keys out of four is worse than none.** 2026-08-25. A pay button that
appears without the webhook secret charges the card and then refuses every
event, so the money lands in Stripe and the invoice sits unpaid with nobody
told. Gate the button on all four.

**Live mode webhooks are a separate endpoint with a separate signing secret.**
Swapping the API keys to live and keeping the test `whsec_` is the same failure
as above and looks exactly like a working integration until you reconcile.
Test mode and live mode share nothing.

**Record money on the webhook, never on the customer coming back.** The success
URL is just a page. Someone who closes the tab, loses signal or never returns
has still paid, and a page anyone can type is not evidence: believing it lets a
stranger mark an invoice paid by visiting a URL.

**Make the webhook idempotent.** Stripe retries until it gets a 2xx, so the
same payment arriving twice is normal rather than a fault. Recording it twice
shows the invoice overpaid and sends the customer two receipts. Store the
Stripe event id and refuse one already on file.

**Fail closed when no webhook secret is configured.** With no secret there is
no way to tell Stripe's event from anyone else's, and a forged one marks an
invoice paid for free.

**App-wide CSRF protection eats the webhook.** Stripe is not a browser and
sends no token, so the endpoint answers 400 before the view runs. Money arrives
and the app never hears about it, in production only, because the test suite
runs with CSRF off. Exempt the view and authenticate it by signature instead.
Any test for it has to build its own app with CSRF switched on, or it is
testing nothing.

**Refuse old signatures.** Anything more than five minutes old, so a captured
signature cannot be replayed later.

**Open question, worth recording once tested:** whether inline `price_data`
also needs Products or Prices write on a restricted key, or whether Checkout
Sessions write alone covers it.
""".strip(),

    "verify_md": """
**In test mode, pay a real invoice with a test card.** Open any invoice, press
pay, and use `4242 4242 4242 4242` with any future expiry and any CVC. The
invoice should mark itself paid within a second or two of the card going
through, with nobody touching the admin.

**If it does not, look at the webhook and not the checkout.** The customer
paying and the app hearing about it are two separate events on purpose, and
confusing them costs an afternoon. Developers, Webhooks, your endpoint, and
read the actual delivery attempts and their responses.

**Check the event log, not the code.** A 200 with no state change in your app
is a different bug from a 400 at the door, and the log tells you which one you
have.

**Before going live, confirm the live endpoint exists and its own secret is
set.** Send a test event to it from the Stripe dashboard and watch for a 2xx.
""".strip(),
}


TWILIO = {
    "slug": "twilio",
    "display_name": "Twilio",
    "logo_path": "pm/logos/twilio.svg",
    "vendor_url": "https://console.twilio.com",
    "sort_order": 20,
    "one_liner": "A2P 10DLC registration, so a client's app can text its own customers without being filtered.",

    "client_only_md": """
The brand record is a legal identity check and only the client holds the
answers. Get all of it in one ask, because a wrong value on an approved profile
cannot be edited from the console afterwards.

- **Legal entity name exactly as filed.** Not the trading name.
- **EIN or Tax ID.** Given to Twilio directly, never written into a repo or a
  transcript. It lives in a password manager.
- **Business type and industry.**
- **Physical street address.** A registered address that is also somebody's
  house is a decision to make deliberately, because the carrier wants a real
  street address and the legal pages will carry it.
- **Business phone.**
- **Business email on the business domain.** A free mailbox weakens the record.
- **Point of contact**, name, email and mobile.

Two decisions to force before submitting, rather than discover after:

**Transactional only, or marketing too?** If they will ever text past customers
a promotion, that is a second campaign with a second checkbox. Blurring the two
is a documented rejection.

**Does consent stand, or is it per job?** Consent stored against a customer
never expires, but consent worded "about this service request" describes one
job, and the gap only shows the first time you text a returning customer.
Standing is usually what a trades business needs. Whichever they pick, three
copies of that sentence have to agree: the checkbox, the frozen consent record,
and what the carrier has on file.
""".strip(),

    "access_grant_md": """
**Get onto the client's Twilio account, then create your own API key on it.**
Console, Account, API keys and tokens, Create API key, type **Standard**, named
for the app.

A key is scoped to one app and can be deleted on its own the day a laptop goes
missing. The account auth token is the account: it can buy numbers, read every
message ever sent, and cannot be rotated without breaking everything else
holding it. Never ship the auth token as the sending credential.

**You need both, and nothing in the console says so.**

    TWILIO_ACCOUNT_SID        names whose account is billed, not a credential
    TWILIO_API_KEY_SID        sending
    TWILIO_API_KEY_SECRET     sending
    TWILIO_AUTH_TOKEN         inbound signature check only

Twilio signs inbound webhooks with the account auth token and nothing else.
There is no API key equivalent. Skip it because "we use a key now" and every
reply and every STOP is refused at the door with nothing in the app to show for
it. An hour went to this on 2026-08-26.

**Get the brand details right the first time.** Twilio allows only the friendly
name and notification settings to be edited on an approved profile. Anything
else is a support ticket, and reopening an approved profile risks the approval
that the campaign depends on.
""".strip(),

    "your_steps_md": """
Registration fails for three reasons and never for message wording: the
reviewer could not reach the page, the fields did not describe what the page
actually does, or something in front of the site blocked the crawler. This
order is built to prevent all three.

**Before opening the wizard, make the opt-in page true.**

- Phone field and consent checkbox **on the same screen**. This is the single
  most cited rejection reason.
- Checkbox **unchecked by default** and **not required** to submit.
- The consent sentence carries all four: what messages, **frequency**,
  **"Msg and data rates may apply"**, and **STOP/HELP**.
- Terms and Privacy linked **in that same sentence**, not only in a footer.
- Reachable by a stranger with no login, no token and no redirect, and it works
  **repeatedly**, for more than one reviewer.
- Nothing on the page calls itself a preview, demo or example.
- **The form exists in the fetched HTML.** Test with curl, never a browser:

      curl -s https://example.com/request | grep -c "<input"

- Every URL in every sample message resolves in production right now. Not a
  placeholder, not a token, not "xxxx".
- The Privacy Policy carries the non-sharing sentence carriers look for, about
  opt-in data never being sold, rented or shared with third parties.
- Legal entity name, address and domain match the brand record exactly.

**Then check what is in front of the site.** See the Cloudflare playbook. Both
traps there will fail a registration and neither is visible from your laptop.

**Then fill the campaign form.** The `message_flow` field must itself contain
the privacy link, the terms link, the message frequency and the rates
statement. Having them on the page is not enough, because the field is what
gets read first. Paste the live consent wording verbatim so the field and the
page cannot drift, and describe every way consent is collected, paper forms and
QR codes included.

**Run Check Campaign before submitting, every time.** A green initial
verification is the entire point of it.

**After approval, in this order.** Each step is worth nothing until the one
before it is true.

1. **Buy the number and attach it to the Messaging Service.** A campaign can be
   approved with an empty sender pool and nothing tells you.
2. **Set the sending credentials.** Until they are all set, every text should
   mark itself skipped **with the reason** rather than vanishing.
3. **Set the account auth token as well**, for the inbound signature.
4. **Point the Messaging Service inbound webhook at your STOP handler.** On the
   *service*, not the number, with `use_inbound_webhook_on_number` false, and
   leave Advanced Opt-Out on: Twilio sends the STOP and HELP replies and the
   app only keeps its own database in step.
5. **Send one real message through the app** and read it back from the API.
6. **Post to your own inbound endpoint three ways.**
7. **Delete dead drafts** so nobody submits one by mistake.

**The app side is not optional.** Gate sends at the delivery floor, not on a
queue helper: the one path that skips the helper is the one that texts somebody
who never opted in. Store consent as timestamp, IP and the exact wording shown.
Verify the inbound signature and fail closed. Exempt the webhook from CSRF and
authenticate it by signature instead.
""".strip(),

    "traps_md": """
**Twilio backfills START, YES and UNSTOP whether or not you clear the field.**
Clearing the box does not remove them. If the app does not restore consent on
START, do not declare an opt-in message promising that it does; point them back
at the form instead. Whatever you declare, the Messaging Service's Advanced
Opt-Out reply has to say the same thing: a declared reply that differs from the
sent one is the description-does-not-match-reality mismatch that gets campaigns
rejected. Check the opt-out confirmation too.

**The campaign wizard is a Persona embed in a cross-origin iframe**, hostile to
automation and mildly hostile to people:

- **It paints blank or half drawn.** Resizing the browser window forces a
  repaint and is the only reliable fix.
- **`Back` discards the edits on the step you are leaving. `Next` saves them.**
  An opt-in message was lost this way and had to be retyped.
- **A resumed draft cannot navigate back past Sample messages.** Use case,
  description and message flow are captured when the campaign is created, and
  `Back` does nothing on that step: click, Enter and Space all fail. If any of
  those three is wrong on an existing draft, **the draft cannot be fixed, start
  a new campaign**.
- **The Use case select cannot be driven by automation.** Option clicks, first
  letter jumps, arrow keys and Enter all leave it empty and `Next` never
  advances. Every text area accepts typing fine. A person sets that one field.
- **Ticking a checkbox can expand a help panel and move everything below it.**
  Re-locate the next field after any checkbox, or you type into the panel.
- **Watch field length.** A 534 character campaign description was silently
  rejected with no message against the field. Around 230 advanced first try. A
  field that will not advance and shows no error is usually too long.

**Sending and receiving do not use the same credential.** 2026-08-26. See the
access grant above. Log which credential is missing at the moment you turn a
request away, or the only symptom is customers who never seem to answer.

**A Restricted key 401s on the classic `/2010-04-01/` endpoints for reads**,
which looks alarming and is not necessarily fatal: sending is a create, and a
key that cannot read the account may still be able to create a message. Do not
guess, probe it.

**A host that will not store an empty variable** makes you put a placeholder in
the slot, and anything reading that slot has to be able to tell a placeholder
from a credential. Every Twilio API key SID starts `SK`, so requiring that does
the job and also catches the account SID pasted into the key box. Without the
check the send authenticates as nobody and 401s in a way that reads exactly
like a wrong key rather than an empty box.

**Console buttons drop the account id from the URL.** "Create API key"
navigates to a path with no account in it, falls back to your *default*
account, and renders blank as well. With more than one account under a login
this quietly creates the key on the wrong one. Navigate with the account scoped
URL instead, and check the account name in the header before every save.

**Onboarding tasks linger.** A number can show an outstanding compliance task
from before the campaign was approved. Check its date against the approval date
before chasing it.

**Rejection history worth reading once**, from a program that was rejected five
or six times across several months before anyone wrote this down:

| What happened | The lesson |
|---|---|
| Consent page behind a token URL | The CTA must be reachable with no credentials |
| Email domain typo, no address on legal pages | Brand details, site and legal pages must match exactly |
| Page labelled a "preview" of the real flow | Never signal that the reviewer is looking at a replica |
| Demo URL 404'd in production | Test the exact URL you submit, in production |
| CTA URL single use, second reviewer redirected | It must work repeatedly |
| Consent checkbox pre-checked or required | Unchecked by default, optional to submit |
| Phone field on a different page from consent | Same screen, clearly displayed |
| Description said transactional, form collected marketing | The two must match exactly |
| Opt-in built in JavaScript, fetched page had no field | The field must be in the HTML |
| CDN obfuscated the business email out of the page | The CDN can remove what the app put in |
| CDN challenged the crawler, so it never saw the page | Check the CDN's security log, not your own curl |

**Two-way texting is a separate feature and is none of this.** Receiving STOP is
compliance. Showing the client a customer's reply, and letting them answer, is
a conversation view, a store of inbound messages and a compose box. Do not let
"the webhook works" read as "replies work".
""".strip(),

    "verify_md": """
Every check here answers a question from outside. The console will happily show
you a value it did not save.

**Does the key authenticate on the send endpoint?** Post to the real Messages
endpoint with a destination that cannot exist:

    To=+1555, MessagingServiceSid=MG..., Body=probe

- `21211 The To number is not a valid phone number` means auth is fine and it
  got as far as validating the number. Nothing sent, nothing billed.
- `20003 Authenticate` means the key is not accepted there at all.

That separates the two questions a failed send confuses, and costs nothing.

**Is the sender actually attached?**
`GET messaging.twilio.com/v1/Services/{MG}/PhoneNumbers` lists them. A campaign
can be approved with an empty pool and nothing tells you.

**Is the inbound webhook really set?** Read it back from
`GET messaging.twilio.com/v1/Services/{MG}` and check `inbound_request_url`,
`inbound_method`, and that `use_inbound_webhook_on_number` is false.

**Does the inbound endpoint accept Twilio and refuse everyone else?** Post to it
three ways: correctly signed, unsigned, and signed over a different body. A
working endpoint answers **200, 403, 403**. Use a harmless body, **never
`STOP`**: this is production and STOP clears a real customer's consent.

**Does the app actually send?** Send one message through the app's own send
path, not a raw API call, because what is in question is the deployed code with
the deployed credentials. Then read the message back from the API and check
that `status` is `delivered` and `error_code` is empty.
""".strip(),
}


CLOUDFLARE = {
    "slug": "cloudflare",
    "display_name": "Cloudflare",
    "logo_path": "pm/logos/cloudflare.svg",
    "vendor_url": "https://dash.cloudflare.com",
    "sort_order": 30,
    "one_liner": "DNS and CDN in front of the client's site, and the settings that break things invisibly.",

    "client_only_md": """
- **The domain registration is theirs.** Whoever holds the registrar account is
  the only one who can point the nameservers at Cloudflare, and that is the step
  that actually moves the zone.
- **The Cloudflare account is theirs** when the domain is. Ask which account the
  zone lives under before assuming it is one of yours, because a zone can be
  added to any account and the wrong one is discovered late.
- **Plan level is a billing decision.** It matters here for one reason: on the
  free plan Bot Fight Mode is all or nothing with no per-path exclusion.

Nothing else on this page needs them, provided the access grant below happens.
""".strip(),

    "access_grant_md": """
**Ask to be added to the Cloudflare account as a member**, rather than being
sent screenshots of settings.

Both traps below are invisible from outside. Neither shows up in a curl from
your own machine, neither produces an error anywhere in the app, and the only
place that records them happening is Cloudflare's own Security Events log. If
you cannot open that log you cannot tell "the setting is off" from "the setting
is on and it is eating your traffic", and the difference is a failed carrier
registration you will spend days blaming on your own form.

Being on the account also means you can flip a setting during a review window
instead of scheduling a call to ask somebody else to.
""".strip(),

    "your_steps_md": """
**Check the two settings before anything gets submitted to a carrier or a
reviewer.** Security, then Settings.

1. **Bot fight mode: off**, at least while anything is in review.
2. **Email address obfuscation: off**, if any page needs to carry a readable
   contact address.

**Know the caching behaviour before you verify a deploy.** Static assets go out
with `max-age=31536000` and are busted by the `?v=<hash>` the templates append.
That is fine for browsers and a trap for checks. See the traps.

**Leave Bot Fight Mode off while a re-review could happen.** A re-review would
be challenged again, and the second failure looks identical to the first.
""".strip(),

    "traps_md": """
**Bot Fight Mode will fail an A2P registration.** It issues a Managed Challenge
to datacenter traffic, and Twilio's pre-check runs on AWS. A crawler cannot
solve a JavaScript challenge, so it sees the challenge page and reports only
that it "was unable to verify some of the information you provided", which
names nothing. Turn it off before submitting.

**A curl test does not catch it.** Your home connection is not a datacenter IP,
so Bot Fight Mode ignores you and the page comes back perfect. Testing from
your own machine proves nothing about the crawler. This is the single most
expensive item on this page: it is invisible, it is not mentioned in any Twilio
document, and it looks exactly like a broken form.

**Email Address Obfuscation hides the contact email.** It rewrites every
`mailto:` into a `/cdn-cgi/l/email-protection` link and a span that only
JavaScript decodes. The page looks right in a browser and carries no readable
address for anything that does not run JavaScript, which includes a carrier
reviewer. Same setting screen. Grep the live page for the address itself, never
for `mailto:`.

**Never verify a CSS or JS change by curling the bare asset URL.** With
`max-age=31536000` and cache busting done by query string, `/static/css/app.css`
with no query is a Cloudflare copy that can be a year stale. Read the `?v=` the
page is actually asking for, or append your own cache buster.

**A check that reads the `?v=` off the page must abort when it comes back
empty.** During a deploy the page fetch can fail, leaving `?v=` bare, which is
the year stale copy again and reports a deploy that has not happened.

**Never write a check as `grep -c X || echo 0`.** It prints `0` twice and every
`!= "0"` test passes, which reports a deploy that never happened. Same family
of mistake as the one above.

**The general rule:** anything that makes the site behave differently for a bot
than for you is a liability. Check the CDN before blaming the form.
""".strip(),

    "verify_md": """
**Prove whether Bot Fight Mode is challenging your reviewer.** Cloudflare,
Security, Analytics, Events. Look for `Managed Challenge` rows whose Service
column reads `Bot fight mode`, with timestamps matching your pre-check runs to
the second.

That log records only traffic it **mitigated**, so once the setting is off,
**no entry is the pass**. An empty log is the result you want, which is worth
saying out loud because an empty log usually means "I looked in the wrong
place".

**Prove the contact address is really in the HTML.** Grep the live URL for the
address itself:

    curl -s https://example.com/terms | grep -c "name@example.com"

Never grep for `mailto:`, which survives obfuscation and tells you nothing.

**Prove an asset change actually shipped.** Read the `?v=` off the live page
first, fail the check if it comes back empty, then fetch the asset with that
query string.
""".strip(),
}


RAILWAY = {
    "slug": "railway",
    "display_name": "Railway",
    "logo_path": "pm/logos/railway.svg",
    "vendor_url": "https://railway.app",
    "sort_order": 40,
    "one_liner": "Where the app runs. Push to main and it deploys, which is also how it lies to you.",

    "client_only_md": """
Usually nothing, because the project normally lives in our own workspace and
the client never touches it. Worth confirming rather than assuming, because
when it is not ours these are the parts only they can do:

- **Billing.** Whoever owns the account owns the card, and a suspended project
  is not a bug you can fix.
- **Adding you to the workspace.** See the access grant.
- **Enabling scheduled backups.** There is no CLI command for backups, so it is
  the dashboard or nothing, and only an account holder can do it.

If the client owns the account, get backups turned on in the same sitting as
access. It is the one thing on this list that cannot be fixed retroactively.
""".strip(),

    "access_grant_md": """
**Workspace access plus a CLI logged in on your own machine.** Everything below
assumes both.

Then set the database URL as a **reference variable** rather than a pasted
string:

    DATABASE_URL = ${{Postgres.DATABASE_URL}}

That resolves to the **private network** URL, so the app talks to the database
without touching the public internet, and it keeps resolving after a database
rotation that a pasted string would survive only until the next one.

The Postgres service also exposes a public TCP proxy as `DATABASE_PUBLIC_URL`
for local admin access. Treat that URL as a secret, always fetch it fresh, and
never commit it. If nothing uses it, it can be removed in the Postgres service
settings and re-added when needed.

**Environment variables are in no backup.** Whatever you set here also goes in
a password manager, or a restore brings back the data and not the ability to
boot.
""".strip(),

    "your_steps_md": """
**Provision the shape.** A web service and a Postgres, a volume mounted at
`/data` for anything the app writes and expects to survive a redeploy, and the
database URL as a reference variable.

**Turn on backups, in the dashboard, because the CLI has no backup command.**
For anything holding client logins or invoices this is not optional:

1. Postgres service, Backups tab. Daily, weekly and monthly are stackable
   checkboxes. Take one manual snapshot to seed it.
2. Same for the web service, whose volume holds uploads and PDFs. Daily is
   enough.
3. Restoring **overwrites current data**. To inspect a backup safely, restore
   into a throwaway Postgres service instead.
4. Take an occasional off-site copy, which is the only thing that protects
   against losing the account itself. Use a `pg_dump` client at least as new as
   the server, because Railway is aggressive about major versions.

**Know how deploys are triggered.** Pushing to `main` is the handoff: Railway
picks up every push and deploys it. Setting any variable also triggers a
redeploy.

**Run migrations once per deploy, not once per container start.** A
`preDeployCommand` runs before cutover; a Procfile command runs on every
restart.

**Know which command runs where.** `railway run <cmd>` is your local machine
with production environment variables, so there is no volume and the internal
database URL does not resolve. `railway ssh "<cmd>"` is inside the container,
where the volume and the internal database both work. Backfills go through
`ssh`.
""".strip(),

    "traps_md": """
**`railway status` says `Online` all the way through a deploy.** The line reads
`Online · Deploying (45s)` while the new build is still going, so a check that
matches on `Online` waves itself through and then measures the **old** commit.
Match `Deploying` first and keep waiting.

**`railway logs` defaults to the most recent *successful* deployment.** After a
failure it hands you a clean healthy log from a different deploy and everything
looks fine. Pass the failed deployment's own id: `railway logs <id> -d`, and
try `-b` and `--http` too. All three empty means it failed before it started
building, which is Railway's problem rather than the commit's, and a re-trigger
usually clears it.

**`railway variables` prints resolved values.** 2026-08-26. A mask that looks
for TOKEN, SECRET, KEY or PASSWORD in the *name* sails straight past
`DATABASE_URL`, which carries the Postgres password inside a URL. That put it
in a transcript. Print the names, or one named variable you meant to look at,
and check the shape rather than the value. Never print a whole listing, masked
or not.

**Railway will not store an empty variable**, so a slot waiting to be filled
holds a placeholder. Anything reading such a slot has to be able to tell a
placeholder from a credential, or it authenticates as nobody and the 401 reads
like a wrong key rather than an empty box.

**A pushed commit is not a deployed commit.** From the outside a failed deploy
and a slow one look identical: both keep serving the previous commit.

**Force-pushing while Railway is mid-build pulls the SHA out from under it.**
The deploy fails and the site quietly keeps serving the old commit. An empty
commit re-triggers it.

**Changing the Procfile's web command may not change the running command.**
2026-08-20. The builder kept planning the original one, verified through
`cat /proc/1/cmdline`. If the start command ever needs to change, check PID 1
after the deploy, and if it is stale, clear and set the Start Command in the
dashboard.

**`railway ssh` sessions do not have the venv on PATH.** Call the interpreter
by its full path.

**On Windows Git Bash, MSYS rewrites any argument starting with `/`** into a
`C:/...` path, which breaks every mount path you pass. Prefix the command with
`MSYS_NO_PATHCONV=1`. In PowerShell, do not redirect `2>&1` on railway
commands; the native command error noise is not a real failure.

**Railway prints an "agent tooling not detected" nag to stderr** on every
command. It is harmless and it is not your error.
""".strip(),

    "verify_md": """
**Verify against the public URL, never the container.**

    curl -s https://example.com/ | grep -q "something new"

`railway ssh` can land on a container that is not serving traffic, so a check
run inside it can pass while the site serves the old build.

**Confirm the deploy actually succeeded.** `railway status` and
`railway deployment list`, looking for SUCCESS, and remembering that `Online`
alone means nothing mid-deploy.

**If the start command was changed, check PID 1.**

    railway ssh "cat /proc/1/cmdline"

**After enabling backups, take one manual snapshot and confirm it appears.** An
unconfigured backup schedule and a configured one look the same until the day
you need it.
""".strip(),
}


ALL_PLAYBOOKS = (STRIPE, TWILIO, CLOUDFLARE, RAILWAY)


def upgrade():
    conn = op.get_bind()
    existing = {
        row[0] for row in conn.execute(sa.text("SELECT slug FROM playbooks"))
    }
    now = datetime.now(timezone.utc)
    rows = []
    for pb in ALL_PLAYBOOKS:
        if pb["slug"] in existing:
            continue
        row = dict(pb)
        row["is_active"] = True
        row["created_at"] = now
        row["updated_at"] = now
        rows.append(row)
    if rows:
        op.bulk_insert(playbooks, rows)


def downgrade():
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM playbooks WHERE slug IN (:a, :b, :c, :d)"),
        {"a": "stripe", "b": "twilio", "c": "cloudflare", "d": "railway"},
    )
