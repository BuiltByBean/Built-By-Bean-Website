"""four more runbooks, written from what the repos actually contain

Six playbooks against nine years of integrations. This is the first wave of
closing that: Tripleseat, Gmail's SMTP, AWS, and Squarespace — three of which
Michael named and one which four separate apps depend on without a word
written down about it.

None of this is generic vendor advice. Every trap below is lifted from a
comment, a config default or an incident already recorded in one of the repos:
Tripleseat's three rate caps and the hour being the binding one, the
`/oauth2/token` path that silently serves HTML at `/oauth/token`, four apps
defaulting to `smtp.gmail.com`, the S3-to-volume migration that stayed
reversible, and jdentertain.com being delegated to two nameserver providers at
the same time.

Logos are deliberately left empty rather than hand-drawn. The tiles show
initials until a real mark is dropped in; a wrong logo has already cost three
corrections in this codebase.

Revision ID: b7d4f6a29e01
Revises: e6a3d81b45c9
Create Date: 2026-09-01 15:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7d4f6a29e01'
down_revision = 'e6a3d81b45c9'
branch_labels = None
depends_on = None


# ─────────────────────────────────────────────── Tripleseat

TRIPLESEAT = {
    "slug": "tripleseat",
    "display_name": "Tripleseat",
    "logo_path": "",
    "vendor_url": "https://api.tripleseat.com",
    "is_active": True,
    "is_default": False,
    "sort_order": 60,
    "one_liner": (
        "The venue's event system. Two different auth schemes, three rate caps, "
        "and the one that bites is the one you cannot see."
    ),
    "client_only_md": """\
**A Tripleseat account with API access turned on.** It is not on by default and
it is not self-serve on every plan. The venue's Tripleseat admin has to request
it, and that request goes to Tripleseat rather than to you, so start it early —
it is the long pole and nothing can be built against a sandbox that does not
exist.

**Which Tripleseat account, if they have more than one.** A venue group with
several rooms may run separate accounts, and events live in exactly one of
them. Pulling from the wrong account returns a clean, empty, entirely
believable list.

**The webhook decision.** Tripleseat can push changes to you or you can poll
for them. Pushing is better and needs somebody at their end to configure the
endpoint. Polling works without them and costs you rate budget forever. Ask
which they will support before you build for one.

**Who owns the data if this ends.** Their events are theirs. Be clear from the
start that you hold a copy, not the record.
""",
    "access_grant_md": """\
**Two credential pairs exist and they are not interchangeable.**

    TRIPLE_SEAT_CLIENT_ID       OAuth 2.0, client-credentials grant
    TRIPLE_SEAT_CLIENT_SECRET
    TRIPLE_SEAT_CONSUMER_KEY    legacy OAuth 1.0
    TRIPLE_SEAT_CONSUMER_SECRET
    TRIPLE_SEAT_WEBHOOK_SECRET  signs inbound pushes, unrelated to either

Talent Booker holds both and picks at runtime: OAuth 2.0 when the client pair
is set, falling back to OAuth 1.0 when it is not, so a migration can happen one
environment at a time rather than as a cutover. Take both pairs when they are
offered, even if you only intend to use one.

**The token endpoint is `/oauth2/token`.** Not `/oauth/token`. The second is a
catch-all that answers with an HTML page, so a client posting there gets a 200
and a body it cannot parse, which reads as anything except a wrong URL.

**Ask what plan the account is on before promising a sync interval.** The rate
caps below are the same for everyone, but what is *enabled* is not.
""",
    "your_steps_md": """\
**Throttle to 200ms between requests and nothing faster.** See the traps for
why this exact number. Put it in the client, not in the caller, so a new caller
cannot forget.

**Cache the OAuth 2.0 token and refresh it on expiry, not per request.** The
token lasts long enough that fetching one per call is both slow and a way to
burn the quota on authentication.

**Treat the webhook secret as the only thing standing between you and forged
events.** Verify the signature before the handler runs, and refuse anything
unsigned. An unverified endpoint that creates events is an endpoint anybody can
create events on.

**Store the Tripleseat id on everything you import.** Re-running an import is
normal and re-creating everything is not. The id is what makes the second run
an update.

**Log every non-200 with the endpoint and the hour.** A 429 that only appears
in aggregate is invisible in a single request's log line.
""",
    "traps_md": """\
**There are three rate limits and the hourly one is the killer.** Checked
2026-08-01 against Tripleseat's own API Overview:

    10 requests / second      1,200 / minute      18,000 / hour

18,000/hour is a sustained **5 requests per second**. A 150ms interval is 6.67
req/sec — comfortably inside the per-second and per-minute caps, and 33% over
the hourly budget. So a long enough run exhausts the quota with every single
request looking perfectly well-behaved. This is the likely cause of the
eleven-minute 429 storm recorded as LM-16 in Talent Booker, where individual
event fetches kept failing long after the bulk loop had finished. **A spent
hourly budget is indistinguishable from a strict per-endpoint limit from the
client side.** 200ms = 5 req/sec = 18,000/hour and cannot breach any of the
three however long it runs.

**`/oauth/token` returns HTML, not an error.** It is a catch-all page. You get
a 200 with a body that fails to parse, which sends you hunting for a
credentials problem you do not have.

**The OAuth 1.0 fallback hides an OAuth 2.0 misconfiguration.** If the client
pair is wrong or absent the code quietly uses the consumer pair instead and
keeps working — which is exactly what you want in a migration and exactly what
you do not want when you think you have finished one. Log which scheme is
actually in use.

**An empty list is a valid answer to the wrong account.** No error, no warning.
Confirm the account id against something you know exists before concluding
there are no events.
""",
    "verify_md": """\
**Which auth scheme is actually being used?** Not which one you configured.
Log it at startup and read the log, because the fallback is silent.

**Does the token endpoint return JSON?**

    curl -s -X POST https://api.tripleseat.com/oauth2/token | head -c 200

Anything starting `<` means you are on the catch-all page.

**Is the pace really under 5 req/sec, measured over an hour?** Count requests
in the log for a full hour of steady running, not for a minute of it. The
minute will always look fine.

**Does a replayed webhook get refused?** Post the same signed body twice and
check the second one changes nothing. Tripleseat retries, so duplicates are
routine rather than an attack.

**Does an unsigned webhook get a 403?** Post without a signature. Anything
other than a refusal means the endpoint is open.
""",
    "steps": [
        ("Ask the venue to request API access from Tripleseat",
         "Not on by default, not self-serve on every plan, and the request goes "
         "to Tripleseat rather than to you. It is the long pole — start it "
         "before anything else.",
         "email", "Getting {project} talking to your Tripleseat",
         "Hi {client},\n\nTo pull your events into {project} automatically I "
         "need API access enabled on your Tripleseat account. That has to be "
         "requested by you rather than by me — Tripleseat will not turn it on "
         "for a third party.\n\nContact Tripleseat support and ask them to "
         "enable API access for your account. They will send back a set of "
         "credentials; forward those to me and I will do the rest.\n\nWorth "
         "starting now even if we are weeks away from needing it — this is "
         "usually the slowest part and everything else waits on it.\n\nThanks,"
         "\nMichael\nBuilt by Bean LLC"),

        ("Confirm which account the events actually live in",
         "A venue group with several rooms may run more than one Tripleseat "
         "account. Pulling from the wrong one returns a clean, empty, "
         "believable list.",
         None, "", ""),

        ("Capture both credential pairs, not just the one you plan to use",
         "OAuth 2.0 (`CLIENT_ID`/`CLIENT_SECRET`) and legacy OAuth 1.0 "
         "(`CONSUMER_KEY`/`CONSUMER_SECRET`). Holding both lets the switch "
         "happen one environment at a time instead of as a cutover.",
         None, "", ""),

        ("Point the token request at /oauth2/token",
         "`/oauth/token` is a catch-all that answers with an HTML page, so a "
         "wrong path returns 200 and an unparseable body rather than an error.",
         None, "", ""),

        ("Throttle to 200ms in the client, not in the caller",
         "5 req/sec = 18,000/hour, which is exactly the hourly cap. Anything "
         "faster passes the per-second and per-minute limits and still "
         "exhausts the hour. In the client so a new caller cannot forget.",
         None, "", ""),

        ("Cache the token and refresh on expiry",
         "One token per call is slow and spends quota on authentication.",
         None, "", ""),

        ("Log which auth scheme is in use at startup",
         "The OAuth 1.0 fallback is silent. Without this line, a broken OAuth "
         "2.0 config looks like a working integration.",
         None, "", ""),

        ("Decide push or poll, and get the webhook configured if push",
         "Pushing needs somebody at the venue to set the endpoint. Polling "
         "needs nobody and spends rate budget forever.",
         "email", "One setting in Tripleseat for {project}",
         "Hi {client},\n\nOne more thing in Tripleseat, and this one is a "
         "single setting.\n\nRight now {project} has to keep asking Tripleseat "
         "whether anything changed. If instead Tripleseat tells us when "
         "something changes, updates show up straight away rather than on a "
         "delay, and we stop making thousands of unnecessary requests against "
         "your account's limits.\n\nCould you or whoever administers Tripleseat "
         "add a webhook pointing at the URL I will send over? Happy to jump on "
         "a call and do it together — it takes about two minutes.\n\nThanks,"
         "\nMichael\nBuilt by Bean LLC"),

        ("Verify the signature before the handler runs, and refuse unsigned",
         "An endpoint that creates events without checking the signature is an "
         "endpoint anybody can create events on.",
         None, "", ""),

        ("Store the Tripleseat id on everything imported",
         "Re-running an import is normal. Re-creating everything is not. The id "
         "is what turns the second run into an update.",
         None, "", ""),

        ("Measure the request rate over a full hour before calling it done",
         "A minute of traffic always looks fine. The hour is the cap that "
         "actually binds, and a spent hourly budget looks exactly like a "
         "per-endpoint limit from the client side.",
         None, "", ""),
    ],
}


# ─────────────────────────────────────────────── Gmail SMTP

GMAIL = {
    "slug": "gmail-smtp",
    "display_name": "Gmail SMTP",
    "logo_path": "",
    "vendor_url": "https://myaccount.google.com/apppasswords",
    "is_active": True,
    "is_default": False,
    "sort_order": 26,
    "one_liner": (
        "Sending mail through a Google account. Free, already there, and the "
        "thing most likely to stop working without telling anybody."
    ),
    "client_only_md": """\
**The Google account, and whether it is consumer Gmail or Workspace.** This
decides everything else on this page: app passwords, sending limits, and
whether the address can be an alias on their own domain. Ask which, and get the
answer from a login rather than from what they assume.

**Two-step verification switched on.** App passwords do not exist without it —
the option is simply not in the interface — and turning 2SV on is a change to
their personal account security that only they can make.

**The sending address, and that a person owns the mailbox.** Mail sent this way
comes from a real Google account. Replies land in a real inbox, and somebody
has to be reading it.

**That this is their account doing the sending.** If they change the password,
lose the phone, or leave the company, mail stops. That is worth one sentence up
front rather than a phone call at the worst moment.
""",
    "access_grant_md": """\
**An app password, never their actual password.**
`myaccount.google.com/apppasswords`, with 2-step verification already on.
Sixteen characters, shown once, revocable on its own without touching anything
else the account does.

    MAIL_SERVER     smtp.gmail.com
    MAIL_PORT       587
    MAIL_USE_TLS    true
    MAIL_USERNAME   the full address
    MAIL_PASSWORD   the app password, spaces removed

Four apps here default to `smtp.gmail.com` — Talent Booker, Bible Study,
Jakob's Crucible and this one — so the shape above is the house standard rather
than a one-off.

**Never the account password.** Google stopped accepting it for SMTP when
"less secure app access" was retired, and the failure is an authentication
error that reads like a wrong password because it is one, just not in the way
it looks.

**Workspace can do a domain alias; consumer Gmail cannot, usefully.** See the
traps — this is the single biggest reason to find out which account it is
before promising an address.
""",
    "your_steps_md": """\
**Strip the spaces out of the app password.** Google displays it in four
groups of four for readability. Some libraries accept it with spaces and some
do not, and the ones that do not fail as an auth error.

**Use port 587 with STARTTLS, not 465.** Both work against Google; 587 is what
every library defaults to and what every host allows outbound. 465 is implicit
TLS and needs different settings, which is a second thing to get wrong.

**Send one real message to an address you can open, and read the From header.**
Not the display name. The From header is where an alias that did not take shows
itself.

**Put the credentials in the host's environment, never in the repo.** An app
password in a public repo is a Google account somebody else can send as, and
this org has eleven public repos.

**Expect to outgrow it.** Gmail SMTP is right for low volume from a real
person's mailbox. The moment mail becomes transactional and per-customer, move
to Resend — Kuper and Data Dungeon both did, and Talent Booker holds both
`MAIL_*` and `RESEND_API_KEY` for exactly that reason.
""",
    "traps_md": """\
**The limits are per day and they are not generous.** Consumer Gmail is around
500 recipients a day; Workspace around 2,000. Cross it and Google blocks
sending for **24 hours**, with a bounce that says the daily limit was exceeded.
A batch job that sends one message per customer will find this on the day the
customer list grows, not on the day it was written.

**Changing the account password revokes every app password.** All of them,
silently, across every app using that account. This is the most likely reason
mail that has worked for a year stops on a Tuesday, and nothing in any app's
logs will say so — the app just gets an auth failure it has never seen before.

**A consumer Gmail "send mail as" alias on a custom domain is a dead end for
this.** Google no longer offers its own relay for external domains on a
consumer account: the setup screen demands an SMTP host, username and password
*for that domain*, which a receive-only arrangement such as Cloudflare Email
Routing does not have. That cost most of a session on `builtbybeans.com`. The
way through is a real SMTP endpoint for the domain — Resend's satisfies it —
which is the thing you were trying to avoid setting up.

**Google rewrites the From to the authenticated account.** If the alias is not
properly verified, the message goes out under the Gmail address instead, and
there is no error — just the wrong name on the recipient's screen.

**2-step verification is required and turning it off removes app passwords.**
If a client "simplifies" their account security later, sending stops.

**Mail lands in spam more readily than from a verified domain.** There is no
DKIM on your client's domain here, because the mail is not coming from their
domain. For anything a customer must act on, this matters.
""",
    "verify_md": """\
**Does the app password authenticate at all?** Test the credential itself
before testing the app:

    python -c "import smtplib; s=smtplib.SMTP('smtp.gmail.com',587); \\
      s.starttls(); s.login('address@gmail.com','sixteencharpassword'); \\
      print('ok')"

`535` means the credential is refused. `ok` means the problem is in the app.

**Does a real message arrive, and what does the From actually say?** Send to an
address you can open and read the header, not the display name.

**How much has it sent today?** Nothing reports this. If sending suddenly fails
across every app on the same account, assume the daily cap before assuming
anything else, and wait it out rather than debugging it.

**Is the password in the environment and not in the repo?**

    git log -p --all | grep -iE "MAIL_PASSWORD|smtp"

**Is 2-step verification still on?** If mail stopped and nothing changed on
your side, this and a password change are the two candidates, in that order.
""",
    "steps": [
        ("Find out whether it is consumer Gmail or Workspace",
         "Decides app passwords, the daily sending cap, and whether a domain "
         "alias is possible at all. Get it from a login, not from what they "
         "assume.",
         None, "", ""),

        ("Have them switch on 2-step verification",
         "App passwords do not exist without it — the option is not in the "
         "interface. Only they can turn it on.",
         "email", "Two things on your Google account for {project}",
         "Hi {client},\n\nTo let {project} send email from your address I need "
         "two things set up on your Google account. Both are on your side "
         "because they are account security settings.\n\n1. Turn on 2-step "
         "verification, if it is not already: "
         "https://myaccount.google.com/security\n\n2. Then create an app "
         "password at https://myaccount.google.com/apppasswords — name it "
         "something like \"{project}\" so you can recognise it later.\n\n"
         "Google will show you a 16-character password once. Send me that "
         "rather than your actual password. It only permits sending email, it "
         "cannot read your inbox, and you can revoke it on its own at any time "
         "without changing anything else.\n\nThanks,\nMichael\n"
         "Built by Bean LLC"),

        ("Get an app password, never the account password",
         "Google stopped accepting account passwords for SMTP when \"less "
         "secure app access\" was retired. The failure looks exactly like a "
         "wrong password.",
         None, "", ""),

        ("Set the four values, with the spaces stripped from the password",
         "```\nMAIL_SERVER    smtp.gmail.com\nMAIL_PORT      587\n"
         "MAIL_USE_TLS   true\nMAIL_USERNAME  the full address\n"
         "MAIL_PASSWORD  16 chars, no spaces\n```\nGoogle shows it in groups "
         "of four for readability. Some libraries reject it that way and fail "
         "as an auth error.",
         None, "", ""),

        ("Test the credential on its own before testing the app",
         "`smtplib` login in one line. A 535 is the credential; anything else "
         "is your code. Testing both at once means debugging both at once.",
         None, "", ""),

        ("Send a real message and read the From header",
         "Not the display name. An alias that did not take shows itself only "
         "in the header, and Google rewrites silently.",
         None, "", ""),

        ("Warn the client that a password change kills it",
         "Changing the account password revokes every app password on that "
         "account, silently, across every app. This is the most common reason "
         "mail that worked for a year stops.",
         "text", "",
         "Hi {client}, one thing worth knowing now that email is working: if "
         "you ever change your Google account password, it automatically "
         "cancels the app password {project} uses and email will stop going "
         "out. Nothing will warn either of us. If that happens just make a new "
         "app password and send it over and I will have it back in five "
         "minutes. — Michael"),

        ("Check the credential is in the environment and not the repo",
         "An app password in a public repo is a Google account anybody can "
         "send as. Eleven repos in this org are public.",
         None, "", ""),

        ("Know the daily cap before the customer list grows into it",
         "Roughly 500 recipients a day on consumer, 2,000 on Workspace. "
         "Crossing it blocks sending for 24 hours. A per-customer batch job "
         "finds this on the day the list grows, not the day it was written.",
         None, "", ""),

        ("Decide whether this should be Resend instead",
         "Gmail SMTP is right for low volume from a real person's mailbox. "
         "For transactional, per-customer mail from the client's own domain, "
         "it is the wrong tool and there is no DKIM on their domain to help "
         "deliverability. Kuper and Data Dungeon both moved.",
         None, "", ""),
    ],
}


# ─────────────────────────────────────────────── AWS

AWS = {
    "slug": "aws",
    "display_name": "AWS",
    "logo_path": "",
    "vendor_url": "https://console.aws.amazon.com",
    "is_active": True,
    "is_default": False,
    "sort_order": 35,
    "one_liner": (
        "S3 for uploads, and the bill that arrives because nothing here ever "
        "tells you a key is too powerful."
    ),
    "client_only_md": """\
**Whose AWS account it is.** If it is theirs, it is their card and their bill,
and you need an IAM user on it. If it is yours, the storage cost is yours to
price into the engagement and the data sits in your account, which is a
conversation to have deliberately rather than by default.

**A card on the account, and a billing alarm on it.** S3 is cheap and egress is
not. An account with no budget alarm is an account nobody looks at until the
statement.

**Where the data may legally live.** Region is a decision, not a default, for
anything holding customer records. It is also permanent — a bucket cannot
change region, only be copied to a new one.

Almost nothing else needs them, provided the IAM grant below happens properly.
""",
    "access_grant_md": """\
**An IAM user with a policy scoped to one bucket. Never root, never an admin
key.**

    AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY
    AWS_S3_BUCKET
    AWS_S3_REGION

The secret is shown exactly once at creation. There is no reveal later, only
"create another and delete this one."

**The policy should name the bucket and the actions, and nothing else:**
`s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on
`arn:aws:s3:::bucket-name/*`, plus `s3:ListBucket` on the bucket itself if the
app lists. An app that only ever uploads does not need delete.

**Root account keys should not exist at all.** If the client hands you one,
that is the finding — say so, and ask for an IAM user instead. A root key can
close the account.

**Turn on MFA for the console login and a billing alarm at the same time.**
Both are free, both take two minutes, and the moment to do it is while you
already have the console open.
""",
    "your_steps_md": """\
**Put a storage abstraction in front of it on day one.** Talent Booker's
`storage.py` is the model: reads and writes go through helpers, never directly
to `boto3`, and the active backend is chosen by an env var. That one decision
is what later made moving off S3 a config change instead of a rewrite.

**Store bare relative paths in the database, not full URLs.**
`talent/abc.jpg`, not `https://bucket.s3.amazonaws.com/uploads/talent/abc.jpg`.
A full URL in a database row is a hosting decision written permanently into
your data, and it is the reason most storage migrations turn into a data
migration.

**Block public access on the bucket and serve through the app.** A bucket left
open is the single most common AWS incident and it never announces itself.

**Set a lifecycle rule if anything is temporary.** Nothing deletes itself.

**Know what it actually costs before recommending it.** For most of these apps
a Railway volume is cheaper, simpler and has no egress line. S3 earns its place
when files are large, numerous, or need to outlive the host.
""",
    "traps_md": """\
**A Railway volume is usually the better answer, and this org has already
made that move.** Talent Booker migrated from S3 to a volume at
`MEDIA_ROOT` (`/data/uploads`) and kept the rollback: set `MEDIA_BACKEND=s3`
and redeploy, and bare-path rows resolve back to S3 URLs automatically. That
reversibility only existed because of the abstraction and the bare paths. Do
both, or the migration is one-way.

**Legacy rows with full URLs outlive the migration.** Talent Booker's
`media_url()` still renders old absolute-URL rows correctly, years later,
because deleting them was never worth the risk. Write the compatibility path
when you write the migration; you will not go back for it.

**Container filesystems are wiped on every deploy, and a volume is not
automatic.** This is the failure S3 is often reached for as a fix. On Railway
the fix is attaching a volume, which is cheaper and simpler — reach for S3 for
a reason, not as a reflex.

**Egress is the bill, not storage.** Storing images costs almost nothing.
Serving them costs per gigabyte out, forever, and a page that loads twenty
photos pays twenty times.

**`s3:*` on `*` is what a hurried policy looks like** and it grants every
bucket in the account, including whatever else the client keeps there.

**Deleting an IAM user does not delete its keys' effects.** Anything already
uploaded stays. Anything already downloaded is gone.

**A bucket name is global across all of AWS.** Somebody has already taken the
obvious one, and the name is permanent.
""",
    "verify_md": """\
**Is the bucket actually private?** From a machine with no credentials:

    curl -sI https://<bucket>.s3.amazonaws.com/uploads/<a-real-key>

A 200 means the world can read it. `403` is the pass.

**Can the key do more than it should?** Try something the app never does and
confirm it is refused:

    aws s3 ls --profile <profile>

Listing every bucket in the account means the policy is not scoped.

**Which backend is the app actually using right now?** Read `MEDIA_BACKEND` off
the running service rather than the repo. The env var is the truth and the
default in `config.py` is not.

**Do old absolute-URL rows still render?** Open a record created before the
migration. This is the check that fails quietly and only for the oldest data,
which nobody looks at.

**Is there a billing alarm?** Console, Billing, Budgets. No alarm means the
first signal is the statement.
""",
    "steps": [
        ("Decide whose account it is, and say so out loud",
         "Their account means their bill and an IAM user for you. Your account "
         "means the storage cost is yours to price in and their data lives with "
         "you. Both are fine; discovering which one it was later is not.",
         None, "", ""),

        ("Get an IAM user scoped to one bucket, never a root key",
         "`s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on "
         "`arn:aws:s3:::bucket/*`, plus `s3:ListBucket` if the app lists. If "
         "the client offers a root key, that is the finding — ask for an IAM "
         "user instead. A root key can close the account.",
         "email", "Storage access for {project}",
         "Hi {client},\n\nFor file storage on {project} I need a limited AWS "
         "key. Please do not send me your main login details — what I need is "
         "a scoped user that can only touch the one storage bucket and nothing "
         "else on your account.\n\nIn the AWS console: IAM, Users, Create "
         "user. Skip console access, and attach a policy limited to the bucket "
         "we are using. If that is more than you want to work through, I am "
         "happy to sit on a call and walk it with you — it is about ten "
         "minutes and it is worth doing properly, because a key with full "
         "access is a key that can shut the account down.\n\nAWS shows the "
         "secret once. Send it over and I will store it securely.\n\nThanks,"
         "\nMichael\nBuilt by Bean LLC"),

        ("Block all public access on the bucket",
         "A bucket left open is the most common AWS incident there is and it "
         "never announces itself. Serve files through the app instead.",
         None, "", ""),

        ("Set a billing alarm before uploading anything",
         "Free, two minutes, and the moment to do it is while the console is "
         "already open. Without it, the first signal is the statement.",
         None, "", ""),

        ("Put a storage abstraction in front of boto3 on day one",
         "Talent Booker's `storage.py` is the model: every read and write goes "
         "through helpers and the backend is chosen by an env var. That one "
         "decision is why moving off S3 later was a config change rather than "
         "a rewrite.",
         None, "", ""),

        ("Store bare relative paths in the database, never full URLs",
         "`talent/abc.jpg`, not `https://bucket.s3.amazonaws.com/...`. A full "
         "URL in a row is a hosting decision written permanently into your "
         "data, and it is why most storage migrations become data migrations.",
         None, "", ""),

        ("Ask whether a Railway volume would be better before committing",
         "For most of these apps it is cheaper, simpler and has no egress "
         "line. S3 earns its place when files are large, numerous, or need to "
         "outlive the host — not as a reflex against container filesystems "
         "being wiped, which a volume already fixes.",
         None, "", ""),

        ("Prove the bucket is private from an unauthenticated machine",
         "`curl -sI https://<bucket>.s3.amazonaws.com/<key>` — 403 is the "
         "pass, 200 means the world can read it.",
         None, "", ""),

        ("Prove the key cannot list the whole account",
         "`aws s3 ls` with that profile. If it returns every bucket, the "
         "policy is not scoped and it can reach whatever else the client keeps "
         "there.",
         None, "", ""),

        ("Set a lifecycle rule on anything temporary",
         "Nothing in S3 deletes itself, and storage you forgot about bills "
         "forever.",
         None, "", ""),
    ],
}


# ─────────────────────────────────────────────── Squarespace

SQUARESPACE = {
    "slug": "squarespace",
    "display_name": "Squarespace",
    "logo_path": "",
    "vendor_url": "https://account.squarespace.com",
    "is_active": True,
    "is_default": False,
    "sort_order": 65,
    "one_liner": (
        "The site the client already has. You are not replacing it, you are "
        "living beside it — and the DNS is where that goes wrong."
    ),
    "client_only_md": """\
**The Squarespace login, or a contributor invite on it.** Settings, Permissions,
Invite Contributor. Administrator if DNS or domain settings need touching,
Website Editor if not. Ask for the narrower one and say why.

**Where the domain is actually registered.** Squarespace may be the registrar,
or it may only be the host with the domain registered elsewhere. These are
different accounts with different logins and the client frequently believes
there is only one.

**Whether the Squarespace site is staying.** Three outcomes and they need
different DNS: it stays and your app lives on a subdomain; it goes and your app
takes the apex; or it stays for marketing while your app takes over a path,
which Squarespace cannot do and which therefore means a subdomain anyway.

**Who wrote the content, and whether you may reuse it.** Copy, photography and
video on a Squarespace site were often produced by somebody else. Porting a
hero video and a page of copy is a rights question, not a technical one.
""",
    "access_grant_md": """\
**A contributor invite, not their password.** Settings, Permissions, Invite
Contributor. There is no API worth using here — Squarespace's developer surface
is for template building, not for reading a site — so most of what you need is
done in the interface with your own login.

**Find out who holds the nameservers before touching anything.** This is the
whole job. Run it yourself rather than asking:

    dig +short NS <domain>

If the answer includes Squarespace nameservers *and* somebody else's, stop and
read the traps — that is the split-brain case and it is already live on one
domain here.

**Access to whatever the answer above points at**, which may be Cloudflare,
NS1, GoDaddy or Squarespace itself. That is where records get added, and it is
frequently not where the client thinks.
""",
    "your_steps_md": """\
**Resolve the domain against every authoritative nameserver individually
before you change one record.** Not one public resolver. See the traps.

**Take the subdomain, do not fight for the apex.** `staff.example.com` or
`app.example.com` pointed at Railway leaves the marketing site untouched and
makes the change reversible by deleting one record. Talent Booker lives at
`staff.jdentertain.com` for exactly this reason.

**Add the CNAME wherever the nameservers actually point**, which may not be
Squarespace. Then verify by resolving it, not by looking at the interface that
accepted it.

**Port assets rather than hotlinking them.** Talent Booker pulled the original
Squarespace hero video down to `static/hero.mp4` instead of embedding from
YouTube. A hotlinked asset breaks when the client edits their site, and you
will not be told.

**Mirror the URL structure the old site used where anything links to it.**
Talent Booker's public pages map onto the live Squarespace sub-pages —
`/aerial-1`, `/dancer`, `/photo-booths` — because printed material, saved links
and search results all point at those paths.

**Leave their site alone.** Editing a Squarespace page you were given access to
in order to "fix" something is how a small integration becomes responsibility
for their marketing site.
""",
    "traps_md": """\
**A domain can be delegated to two nameserver providers at once, and it
already is here.** `jdentertain.com` is delegated to **NS1 and Squarespace
simultaneously**. Every one of the eight nameservers happened to agree when
this was checked, so nothing was broken — but if the two zones ever disagree,
the result is works-for-me/fails-for-you depending on which nameserver a given
resolver happened to ask. It is intermittent, unreproducible, and it looks
exactly like a bad deploy.

**Resolve against each authoritative nameserver individually.** One public
resolver answers from one of them and tells you nothing about the others:

    for ns in $(dig +short NS example.com); do
      echo "$ns"; dig +short @"$ns" staff.example.com
    done

**The SOA serial tells you whether the zone has changed at all.** On
jdentertain.com it read `1721422032` — a Unix timestamp, over a year old, which
is what ruled a deploy out as the cause of an outage. A serial that has not
moved means nobody has touched DNS, whatever anyone says.

**`DNS_PROBE_*` in a screenshot means the request never arrived.** Before
blaming your deploy, check whether the app ever saw it. `railway logs --http`
proves an outage did or did not happen far faster than reasoning about it.

**Squarespace cannot hand a path to another host.** No reverse proxy, no path
routing. If the client wants `example.com/booking` to be your app, the answer
is a subdomain and a link, and it is better to say so in the first conversation
than after building for it.

**Squarespace's own DNS interface hides records it manages.** Records it
created for its own site may not appear alongside yours, so a conflict shows up
as your record simply not resolving.

**Cookie domains bite when the app is on a subdomain.** A session cookie scoped
to the apex is sent to the Squarespace site too; one scoped too narrowly breaks
the login. Talent Booker carries `SESSION_COOKIE_DOMAIN` for this, and getting
it wrong produced a real login outage.
""",
    "verify_md": """\
**Do all the authoritative nameservers agree?** Ask each one directly, not a
public resolver. Disagreement is the split-brain and it is intermittent by
nature.

**Has the zone changed at all?**

    dig +short SOA <domain>

A serial that has not moved means nobody has touched DNS since it last did,
which rules out a whole class of theory in one command.

**Does the subdomain resolve to the host you think?**

    dig +short staff.example.com

Compare against what Railway reports for the service. The interface accepting a
record is not the record resolving.

**Does the marketing site still work?** Load the Squarespace apex and one deep
page after every DNS change. It is the thing you were not touching and
therefore the thing you will not check.

**Does a login on the subdomain actually issue a cookie?** Not "does the login
page load". Log in for real and confirm the session survives a navigation —
cookie-domain bugs pass every test that stops at the form.
""",
    "steps": [
        ("Find out where the domain is registered and where DNS is hosted",
         "Two different accounts with two different logins, and clients "
         "routinely believe there is only one. `dig +short NS <domain>` "
         "answers the second half before you have to ask.",
         "email", "Where is {domain} managed?",
         "Hi {client},\n\nBefore I can put {project} on your domain I need to "
         "know where two things live, and they are often in different "
         "places:\n\n1. Where you bought the domain — Squarespace, GoDaddy, "
         "Google, somewhere else\n2. Where its DNS settings are managed, which "
         "is sometimes the same place and sometimes not\n\nIf you are not "
         "sure, the login you use to edit your website is a good starting "
         "point and I can work it out from there. Adding me as a contributor "
         "on the Squarespace account would let me check without going back and "
         "forth.\n\nThanks,\nMichael\nBuilt by Bean LLC"),

        ("Resolve against every authoritative nameserver individually",
         "```\nfor ns in $(dig +short NS example.com); do\n  echo \"$ns\"; "
         "dig +short @\"$ns\" staff.example.com\ndone\n```\nOne public "
         "resolver answers from one nameserver and tells you nothing about the "
         "others. jdentertain.com is delegated to NS1 and Squarespace at the "
         "same time.",
         None, "", ""),

        ("Agree the subdomain rather than fighting for the apex",
         "`staff.example.com` leaves the marketing site untouched and makes "
         "the whole change reversible by deleting one record. Squarespace "
         "cannot hand a path to another host, so a subdomain is the answer "
         "whether or not anyone likes it.",
         None, "", ""),

        ("Get a contributor invite, not their password",
         "Settings, Permissions, Invite Contributor. Administrator only if DNS "
         "needs touching; Website Editor otherwise. Ask for the narrower one "
         "and say why.",
         "email", "Adding me to your Squarespace",
         "Hi {client},\n\nCould you add me as a contributor on your "
         "Squarespace site? It lets me check settings without needing your "
         "login.\n\nIn Squarespace: Settings, then Permissions, then Invite "
         "Contributor. My email is michaelbean21@gmail.com.\n\nIf it offers "
         "you a choice of permission level, Administrator is what I need if we "
         "are changing anything to do with the domain. If we are not, Website "
         "Editor is enough and I would rather have the smaller one.\n\nI will "
         "not change anything on your site without asking.\n\nThanks,\n"
         "Michael\nBuilt by Bean LLC"),

        ("Add the record where the nameservers actually point",
         "Which may not be Squarespace. Then verify by resolving it, not by "
         "looking at the interface that accepted it.",
         None, "", ""),

        ("Set the cookie domain deliberately",
         "A session cookie scoped to the apex is sent to the Squarespace site "
         "too. One scoped too narrowly breaks the login. Talent Booker carries "
         "`SESSION_COOKIE_DOMAIN` because getting this wrong produced a real "
         "login outage.",
         None, "", ""),

        ("Port assets down rather than hotlinking them",
         "Talent Booker pulled the Squarespace hero video to `static/hero.mp4` "
         "instead of embedding it. A hotlinked asset breaks when the client "
         "edits their site, and nobody tells you.",
         None, "", ""),

        ("Mirror the old URL structure where anything links to it",
         "Printed material, saved links and search results all point at the "
         "Squarespace paths. Talent Booker's public pages map onto "
         "`/aerial-1`, `/dancer`, `/photo-booths` for that reason.",
         None, "", ""),

        ("Check the rights on any copy, photography or video you reuse",
         "It was often produced by somebody else. Porting a hero video is a "
         "rights question before it is a technical one.",
         None, "", ""),

        ("Load the marketing site after every DNS change",
         "The apex and one deep page. It is the thing you were not touching, "
         "and therefore the thing you will not check.",
         None, "", ""),

        ("Log in for real on the subdomain and navigate",
         "Not \"does the login page load\". Cookie-domain bugs pass every test "
         "that stops at the form.",
         None, "", ""),
    ],
}


PLAYBOOKS = [AWS, GMAIL, TRIPLESEAT, SQUARESPACE]

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
        # Steps first, explicitly. The foreign key says CASCADE but SQLite
        # does not enforce one unless `PRAGMA foreign_keys` is on, and it is
        # not during a migration — so deleting the playbook alone leaves its
        # steps orphaned. They then reattach on the next upgrade, because
        # SQLite hands the new playbook the id the old one just freed, and
        # every count silently doubles.
        if "playbook_steps" in tables:
            conn.execute(sa.text(
                "DELETE FROM playbook_steps WHERE playbook_id IN "
                "(SELECT id FROM playbooks WHERE slug = :s)"), {"s": pb["slug"]})
        conn.execute(sa.text("DELETE FROM playbooks WHERE slug = :s"),
                     {"s": pb["slug"]})
