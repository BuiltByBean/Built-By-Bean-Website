"""checklists for the three optional playbooks

GitHub, Railway and Stripe got their steps in e9c15b7a34d0. The other three
runbooks were left as prose, which makes them useless in the picker: adding a
playbook with no steps adds an empty box.

The order here is not arbitrary in any of the three. Resend's is the order that
stops a domain sitting Pending for two days. Cloudflare's puts the two
invisible settings before anything is submitted to a reviewer, because after is
too late. Twilio's is built to fail early and cheaply — every client-blocking
ask happens before the opt-in page is built, because the page takes an
afternoon and the brand details take a week to extract.

Seeded only into a playbook with no steps, so an edited checklist survives a
redeploy.

Revision ID: f7a2c93b16de
Revises: e9c15b7a34d0
Create Date: 2026-09-01 10:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f7a2c93b16de'
down_revision = 'e9c15b7a34d0'
branch_labels = None
depends_on = None


SIGNOFF = "\n\nThanks,\nMichael\nBuilt by Bean LLC"

# (title, detail_md, client_channel, subject, message)

RESEND_STEPS = [
    ("Ask which subdomain sends, and who runs their DNS",
     "Resend wants a subdomain, not the apex, and the choice ends up in every "
     "Return-Path and every bounce. Changing it later means doing the DNS "
     "twice. If their DNS is somewhere you already have access, ask for that "
     "instead of having records read down a phone.",
     "email", "Two quick things before {project} can send email",
     "Hi {client},\n\nBefore the app can send email from your domain I need "
     "two things from you.\n\n1. Who manages your DNS? If it is Cloudflare, "
     "GoDaddy, Squarespace or similar, the fastest path is for you to add me "
     "as a user there and I will add the records myself — there are three of "
     "them and one is a 400-character key, so typing it by hand goes wrong "
     "more often than not. If you would rather add them yourself, that is "
     "fine and I will send them over.\n\n2. What address should email come "
     "from, and where should replies go? Something like "
     "hello@{domain} is normal. If you use a no-reply address, replies "
     "disappear, so it is worth deciding on purpose."
     + SIGNOFF),

    ("Check the domain is not already in another Resend team",
     "The one nobody thinks to ask and the one that stops everything. A "
     "domain lives in exactly one Resend team. If a previous developer or a "
     "marketing tool already added it, adding it yourself **revokes their "
     "access** — find out whose team it is first.",
     None, "", ""),

    ("Add the domain in Resend, spelled exactly",
     "Resend does not check that the domain exists at this point, so a typo "
     "is accepted silently and simply never verifies. Read it back character "
     "by character before saving. `builltbybeans.com` cost two days.",
     None, "", ""),

    ("Put the DKIM key and both CNAMEs in DNS",
     "```\nresend._domainkey   TXT     p=MIGf...\nrsend               CNAME   "
     "rsend.forge.rmta.net\nsend                CNAME   send.forge.rmta.net\n"
     "```\nOn Cloudflare every one of these is **DNS only**. A proxied CNAME "
     "resolves to Cloudflare's addresses and Resend never sees its own "
     "target.",
     "email", "Three DNS records to add for {project}",
     "Hi {client},\n\nHere are the three DNS records that let the app send "
     "email as your domain. They only permit sending — they do not change "
     "where your existing mail goes.\n\n1. Type TXT, name resend._domainkey, "
     "value: [paste the long p=MIG... value from Resend]\n2. Type CNAME, name "
     "rsend, value rsend.forge.rmta.net\n3. Type CNAME, name send, value "
     "send.forge.rmta.net\n\nIf your DNS is on Cloudflare, please set all "
     "three to 'DNS only' (grey cloud, not orange) — an orange cloud breaks "
     "the check.\n\nLet me know once they are in and I will verify from my "
     "side." + SIGNOFF),

    ("Clear anything already sitting on `send`",
     "DNS forbids a CNAME sharing a name with any other record. The older "
     "SES-shaped Resend setup put an MX and a TXT on `send`, and the CNAME "
     "cannot be created until they are gone. Write down what you delete "
     "before deleting it. A domain that half verifies is usually this.",
     None, "", ""),

    ("Verify, then resolve the records yourself before believing the status",
     "Verification is a DNS read: it succeeds when the records resolve "
     "publicly, not when you saved them.\n\n```\ndig +short "
     "resend._domainkey.<domain> TXT\ndig +short rsend.<domain> CNAME\ndig "
     "+short send.<domain> CNAME\n```",
     None, "", ""),

    ("Set RESEND_API_KEY and MAIL_FROM on the service",
     "The key is shown exactly once — into the password manager before the "
     "tab closes. `MAIL_FROM` is `Name <address@the-verified-domain>`, and "
     "the domain has to be the verified one or every send is refused.",
     None, "", ""),

    ("Send a real message and read the From header, not the sender name",
     "Send to an address you can actually open. A rewritten From is the "
     "failure this runbook exists to prevent and it is silent: no bounce, no "
     "error, just the wrong name on the client's screen. Then check Resend's "
     "Logs tab — an accepted API call that never appears there did not go "
     "out.",
     None, "", ""),

    ("Tell the client mail is live and where replies land",
     "Worth doing explicitly, because the first thing they will do is reply "
     "to one and see where it goes.",
     "email", "Email is live for {project}",
     "Hi {client},\n\n{project} is now sending email as your own domain "
     "rather than a generic address, so it lands in inboxes properly and "
     "looks like it came from you.\n\nMessages go out from {from_address}, "
     "and replies come back to {reply_address}.\n\nOne thing to watch: if a "
     "customer says they did not receive something, tell me rather than "
     "resending it a few times — I can see the delivery log and say whether "
     "it was delivered, bounced or filtered." + SIGNOFF),
]


CLOUDFLARE_STEPS = [
    ("Ask which Cloudflare account the zone lives under",
     "A zone can be added to any account, and the wrong one is discovered "
     "late. Ask before assuming it is one of yours.",
     "email", "Access to your DNS for {project}",
     "Hi {client},\n\nTo point {domain} at the new site I need access to "
     "wherever your DNS is managed. If that is Cloudflare, the cleanest way "
     "is to add me as a member of the account:\n\n1. Log in at "
     "https://dash.cloudflare.com\n2. Go to Manage Account, then Members\n3. "
     "Invite michaelbean21@gmail.com\n\nIf you are not sure whether you have "
     "a Cloudflare account, tell me who you bought the domain from and I will "
     "work it out from there." + SIGNOFF),

    ("Get added to the account as a member, not sent screenshots",
     "Both traps below are invisible from outside. Neither shows an error "
     "anywhere in the app, and the only place that records them is "
     "Cloudflare's own Security Events log. Without it you cannot tell 'the "
     "setting is off' from 'the setting is on and eating your traffic'.",
     None, "", ""),

    ("Turn Bot Fight Mode off before anything goes to a reviewer",
     "Security, then Settings. On the free plan it is all or nothing with no "
     "per-path exclusion, and it will challenge a carrier's crawler. Leave it "
     "off while a re-review could still happen — a second failure looks "
     "identical to the first.",
     None, "", ""),

    ("Turn email address obfuscation off if any page carries a contact address",
     "Obfuscation rewrites the address into script the crawler cannot read. "
     "The page looks right in a browser and is empty to anything fetching the "
     "HTML.",
     None, "", ""),

    ("Check every record the app needs is DNS only, not proxied",
     "Orange cloud is right for the site and wrong for mail: a proxied CNAME "
     "resolves to Cloudflare's addresses, so DKIM and domain verification "
     "never see their own target.",
     None, "", ""),

    ("Read Security Events and confirm nothing was challenged",
     "Security, Analytics, Events. Look for `Managed Challenge` rows whose "
     "Service reads `Bot fight mode`, timestamps matching your check runs. "
     "The log records only what it **mitigated**, so once the setting is off, "
     "**no entry is the pass** — an empty log is the result you want.",
     None, "", ""),

    ("Prove an asset change actually shipped past the cache",
     "Static assets go out with `max-age=31536000`, busted by the `?v=` the "
     "templates append. Read the `?v=` off the live page first, fail the "
     "check if it comes back empty, then fetch the asset with that query "
     "string. Fetching it bare tells you what was cached a year ago.",
     None, "", ""),
]


TWILIO_STEPS = [
    ("Collect the brand details in one ask",
     "A wrong value on an approved profile cannot be edited from the console "
     "afterwards — it is a support ticket, and reopening an approved profile "
     "risks the approval the campaign depends on. The EIN goes into a "
     "password manager, never into a repo or a transcript.",
     "email", "What I need from you to get {project} texting customers",
     "Hi {client},\n\nBefore your app can text customers, US carriers require "
     "the business behind the messages to be registered. It is a one-time "
     "identity check, it takes a couple of weeks to clear, and it is the "
     "long pole — so I would like to start it now.\n\nI need all of this "
     "exactly as filed, because it is checked against public records and a "
     "mismatch means starting over:\n\n- Legal business name (not the trading "
     "name)\n- EIN / Tax ID\n- Business type and industry\n- Physical street "
     "address\n- Business phone number\n- An email address on your business "
     "domain (a Gmail address weakens the application)\n- Point of contact: "
     "name, email, mobile\n\nPlease send the EIN separately rather than in "
     "this email thread — a text message is fine.\n\nOne warning worth "
     "having up front: carriers reject applications for boring reasons, "
     "usually a detail that does not match their records. If it comes back "
     "rejected it is almost never anything you did wrong." + SIGNOFF),

    ("Force the two decisions before submitting",
     "**Transactional only, or marketing too?** A promotion to past customers "
     "is a second campaign with a second checkbox, and blurring them is a "
     "documented rejection.\n\n**Does consent stand, or is it per job?** "
     "Consent worded 'about this service request' describes one job, and the "
     "gap only shows the first time you text a returning customer. Three "
     "copies of that sentence have to agree: the checkbox, the stored consent "
     "record, and what the carrier has on file.",
     "email", "Two decisions about text messages for {project}",
     "Hi {client},\n\nTwo questions I need answered before I submit the "
     "registration, because both are baked in afterwards and changing them "
     "means applying again.\n\n1. Will you ever text customers anything "
     "promotional — offers, seasonal reminders, 'we have a slot free this "
     "week'? Or only messages tied to a job they have already booked "
     "(confirmations, 'on my way', invoices)? Promotional messages need a "
     "separate application, so it is cheaper to include it now if there is "
     "any chance you will want it.\n\n2. When someone ticks the consent box, "
     "should that cover future messages too, or only the job they are "
     "enquiring about? Most trades businesses want it to stand, so you can "
     "text a returning customer without asking again. If you would rather it "
     "be per job, that works, but the app has to ask again each time.\n\nNo "
     "wrong answers — I just need them locked before submitting." + SIGNOFF),

    ("Get onto their Twilio account and make your own Standard API key",
     "Console, Account, API keys and tokens, Create API key, type "
     "**Standard**. A key is scoped to one app and revocable on its own. The "
     "account auth token is the account: it can buy numbers, read every "
     "message ever sent, and cannot be rotated without breaking everything "
     "else holding it.",
     "email", "Access to your Twilio account",
     "Hi {client},\n\nPlease add me to your Twilio account so I can wire up "
     "the messaging:\n\n1. Log in at https://console.twilio.com\n2. Go to "
     "Admin, then User management\n3. Invite michaelbean21@gmail.com as an "
     "Administrator\n\nI will create my own scoped key on the account rather "
     "than using your login, so access can be revoked cleanly later without "
     "touching anything else." + SIGNOFF),

    ("Capture all four env values, auth token included",
     "```\nTWILIO_ACCOUNT_SID       names whose account is billed\n"
     "TWILIO_API_KEY_SID       sending\nTWILIO_API_KEY_SECRET    sending\n"
     "TWILIO_AUTH_TOKEN        inbound signature check only\n```\nTwilio "
     "signs inbound webhooks with the account auth token and nothing else. "
     "Skip it because 'we use a key now' and every reply and every STOP is "
     "refused at the door with nothing in the app to show for it.",
     None, "", ""),

    ("Make the opt-in page true before opening the wizard",
     "Registration fails because the reviewer could not reach the page, the "
     "fields did not describe it, or something in front of the site blocked "
     "the crawler. Never for message wording.\n\n- Phone field and consent "
     "checkbox **on the same screen** — the single most cited rejection "
     "reason\n- Checkbox **unchecked by default** and **not required** to "
     "submit\n- The sentence carries all four: what messages, **frequency**, "
     "**'Msg and data rates may apply'**, **STOP/HELP**\n- Terms and Privacy "
     "linked **in that same sentence**, not only a footer\n- Reachable by a "
     "stranger with no login and no redirect, **repeatedly**\n- Nothing calls "
     "itself a preview, demo or example\n- The form exists in the fetched "
     "HTML: `curl -s https://example.com/request | grep -c \"<input\"`\n- "
     "Every URL in every sample message resolves in production right now\n- "
     "Privacy Policy carries the non-sharing sentence about opt-in data",
     None, "", ""),

    ("Check what is in front of the site",
     "Both Cloudflare traps will fail a registration and neither is visible "
     "from your laptop. Run the Cloudflare playbook's checks first — Bot "
     "Fight Mode off, obfuscation off — then come back.",
     None, "", ""),

    ("Submit the brand, then wait",
     "The brand is the legal identity check. Nothing about the campaign can "
     "proceed until it clears, and it is measured in days.",
     None, "", ""),

    ("Fill the campaign form with the links inside message_flow",
     "The `message_flow` field must itself contain the privacy link, the "
     "terms link, the message frequency and the rates statement. Having them "
     "on the page is not enough — the field is what gets read first. Paste "
     "the live consent wording verbatim rather than paraphrasing it.",
     None, "", ""),

    ("Attach a number to the messaging service",
     "`GET messaging.twilio.com/v1/Services/{MG}/PhoneNumbers` lists them. A "
     "campaign can be approved with an empty pool and nothing tells you.",
     None, "", ""),

    ("Set the inbound webhook and prove it refuses forgeries",
     "Read it back from `GET messaging.twilio.com/v1/Services/{MG}` — check "
     "`inbound_request_url`, `inbound_method`, and that "
     "`use_inbound_webhook_on_number` is false. Then post three ways: "
     "correctly signed, unsigned, and signed over a different body. A working "
     "endpoint answers **200, 403, 403**. Use a harmless body, **never "
     "`STOP`** — this is production and STOP clears a real customer's "
     "consent.",
     None, "", ""),

    ("Send one message through the app's own send path",
     "Not a raw API call. What is in question is the deployed code with the "
     "deployed credentials. Then read the message back from the API and check "
     "`status` is `delivered` and `error_code` is empty.",
     None, "", ""),

    ("Tell the client texting is live, and what STOP does to their list",
     "They need to know a reply of STOP is permanent and not something you "
     "can undo for them.",
     "email", "Text messaging is live for {project}",
     "Hi {client},\n\nThe carrier registration cleared and {project} can now "
     "text your customers.\n\nTwo things worth knowing:\n\nIf a customer "
     "replies STOP, the carrier blocks all further messages to that number "
     "immediately. That is a legal requirement and neither of us can undo it "
     "from our side — they have to text START to resume. So if someone says "
     "they have stopped getting messages, that is usually why.\n\nThe "
     "registration covers the kind of messages we agreed. Sending a different "
     "kind — a promotion, if we registered for job updates only — is what "
     "gets numbers filtered by the carriers, and getting un-filtered is "
     "slow. If you want to start sending something new, talk to me first and "
     "I will get it registered properly." + SIGNOFF),
]


SEED = {
    "resend": RESEND_STEPS,
    "cloudflare": CLOUDFLARE_STEPS,
    "twilio": TWILIO_STEPS,
}


def upgrade():
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())
    if "playbooks" not in tables or "playbook_steps" not in tables:
        return

    for slug, steps in SEED.items():
        row = conn.execute(sa.text("SELECT id FROM playbooks WHERE slug = :s"),
                           {"s": slug}).first()
        if not row:
            continue
        already = conn.execute(
            sa.text("SELECT COUNT(*) FROM playbook_steps WHERE playbook_id = :p"),
            {"p": row[0]}).scalar()
        if already:
            continue
        for i, (title, detail, channel, subject, message) in enumerate(steps):
            conn.execute(sa.text(
                "INSERT INTO playbook_steps (playbook_id, position, title, detail_md, "
                "client_channel, client_message_subject, client_message_md) "
                "VALUES (:p, :pos, :t, :d, :c, :s, :m)"),
                {"p": row[0], "pos": i, "t": title, "d": detail,
                 "c": channel, "s": subject, "m": message})


def downgrade():
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())
    if "playbooks" not in tables or "playbook_steps" not in tables:
        return
    for slug in SEED:
        conn.execute(sa.text(
            "DELETE FROM playbook_steps WHERE playbook_id IN "
            "(SELECT id FROM playbooks WHERE slug = :s)"), {"s": slug})
