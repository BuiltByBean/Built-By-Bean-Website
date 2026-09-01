"""a runbook for Resend, written from the domain fight it took to learn it

Kuper Plumbing and Data Dungeon both send through Resend, and getting
builtbybeans.com onto it cost most of a session. Almost none of that time went
on the API, which is one POST; it went on domain ownership and DNS, and none
of the failures said what was actually wrong.

Seeded rather than typed into the UI so it ships with the code, and only when
the slug is absent so an edited copy is never overwritten.

Revision ID: c4f7b209ae13
Revises: f3a81b0c5e29
Create Date: 2026-09-01 09:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4f7b209ae13'
down_revision = 'f3a81b0c5e29'
branch_labels = None
depends_on = None


ONE_LINER = (
    "Transactional email from a domain you own. The API is one POST; every "
    "hour you lose goes on domain ownership and DNS."
)

CLIENT_ONLY = """\
**DNS on the sending domain.** Everything Resend needs is a record on their
zone: a DKIM key and two CNAMEs. If they run their own DNS, they add them and
you wait. If their DNS is somewhere you already have access — Cloudflare, in
most of these — ask for that instead and do it yourself, because a DKIM value
read down a phone is a DKIM value typed wrong.

**Which subdomain sends.** Resend wants a subdomain, not the apex, and the
choice sticks: it ends up in every Return-Path and every bounce. Kuper sends
on `mail.kuperplumbing.com`. Pick it before adding the domain, because
changing it later means doing the DNS twice.

**Whether the domain is already in somebody's Resend account.** This is the
one nobody thinks to ask and the one that stops everything. A domain can only
live in one Resend team. If a previous developer, an agency, or the client's
own marketing tool already added it, you cannot add it — and the only way
through is to take it off them. Ask early, in writing.

**The From address, and that it is a real mailbox.** Replies go somewhere.
`noreply@` is a decision, not a default.
"""

ACCESS_GRANT = """\
**An API key on their team, not their login.** Resend, API keys, Create.
Sending permission is enough; full access only if the app manages domains,
which it does not.

    RESEND_API_KEY     the key, shown once — capture it now
    MAIL_FROM          Name <address@the-verified-domain>

The key is shown exactly once. There is no "reveal" later, only "create
another and delete this one", so put it in the password manager before
closing the tab.

**Know the plan before you promise a timeline.** The free plan caps domains,
and the cap is per team. Adding one past the cap does not queue or warn — it
opens an upgrade dialog and stops. If they are at the cap, the fix is usually
deleting a dead entry rather than paying: see the traps.

**SMTP if the app cannot do HTTP.** `smtp.resend.com`, username `resend`,
password the same API key. Same permissions, same verified-domain rule. Worth
knowing because it also satisfies anything that demands SMTP credentials for
a domain, which is otherwise a dead end for a domain with no mail host.
"""

YOUR_STEPS = """\
**Add the domain, and read it back character by character before saving.**
Resend does not check that the domain exists at this point, so a typo is
accepted silently and simply never verifies. See the traps.

**Take the records it gives you and put them in DNS exactly.**

    resend._domainkey    TXT     p=MIGfMA0...        the DKIM key
    rsend                CNAME   rsend.forge.rmta.net
    send                 CNAME   send.forge.rmta.net

On Cloudflare every one of these is **DNS only**. A proxied CNAME resolves to
Cloudflare's addresses and Resend never sees its own target.

**Clear the way for the `send` CNAME.** DNS forbids a CNAME sharing a name
with any other record. If `send` already holds an MX or a TXT — the older
Resend setup put both there — the CNAME cannot be created until they are
deleted. Write down what you delete before you delete it.

**Verify, then wait.** Verification is a DNS read: it succeeds when the
records resolve publicly, not when you saved them. If it stays Pending for
more than a few minutes, resolve the records yourself before touching
anything in Resend.

**Wire the app and send a real message.** `RESEND_API_KEY` and `MAIL_FROM`,
then send to an address you can actually open. The API is a single POST to
`https://api.resend.com/emails` with a Bearer token; Data Dungeon's
`services/mail.py` is the smallest honest example, and degrades to a log line
when the key is absent so local dev does not crash.
"""

TRAPS = """\
**A misspelled domain verifies never and complains never.** `builltbybeans.com`
sat Not Started for two days with perfect DNS on `builtbybeans.com`. Resend
eventually says *"Domain not found: this domain wasn't found in any DNS
servers"*, which reads like a propagation delay and is not one. There is no
rename. Delete the entry and add the correct spelling.

**The domain may belong to another Resend team, and claiming it takes it from
them.** Adding a domain someone else has verified returns *"in use by another
Resend team. Verifying ownership will transfer the domain to your team and
revoke their access."* That is not a warning about your account, it is a
warning about theirs — whatever is currently sending on that domain stops.
Find out whose team it is before clicking. If it is another account of the
client's own, log into that one instead and make the key there.

**The free plan blocks the add with an upgrade dialog.** At the domain cap you
get *"You have reached the domain limit of your plan"* and no way past. If one
of the existing entries is dead — a typo, an abandoned project — delete it and
the slot is free. Deleting requires typing the domain name to confirm, which
is also a last chance to notice the typo.

**Resend changed its DNS shape and the old records block the new ones.** Older
setups used an SES-style `send` MX to `feedback-smtp.*.amazonses.com` plus an
SPF TXT. Current setups want CNAMEs to `*.forge.rmta.net`. They cannot
coexist: same name, and a CNAME may not share a name. A domain that half
verifies is usually this.

**A record you just deleted keeps not existing.** Resolvers cache the absence
too. After clearing the old records the new CNAME can read as missing for a
minute or two. Query it again before concluding the change did not take.

**Nothing sends from an unverified domain.** Not a warning, a refusal. Which
also means Resend cannot rescue an unrelated problem — it will not let you
send as a domain it has not verified, however valid the key.

**A Gmail "send mail as" alias is not a substitute.** Google no longer offers
its own relay for external domains on a consumer account: it demands an SMTP
host and password for that domain, and a receive-only setup such as Cloudflare
Email Routing has neither. Resend's SMTP endpoint does satisfy it — but only
once the domain is verified, which is the thing you were trying to avoid.
"""

VERIFY = """\
Every check answers a question from outside the dashboard, which will happily
show a status it has not re-tested.

**Do the records actually resolve, publicly?** Not "did I save them".

    dig +short resend._domainkey.<domain> TXT
    dig +short rsend.<domain> CNAME
    dig +short send.<domain> CNAME

The CNAMEs must return `*.forge.rmta.net`. If they return Cloudflare
addresses, the record is proxied — turn the cloud grey.

**Does Resend agree the domain is verified?**

    curl -s https://api.resend.com/domains \\
      -H "Authorization: Bearer $RESEND_API_KEY"

Anything other than `"status": "verified"` means it will refuse to send, no
matter what the key can do.

**Does a real message arrive, and from whom?** Send one to an address you can
open and read the actual From header rather than the sender name. A rewritten
From is the failure this whole runbook exists to prevent, and it is silent:
no bounce, no error, just the wrong name on the client's screen.

**Does the log agree?** Resend's Logs tab records every send with its status.
An accepted API call that never appears there did not go out.
"""

FIELDS = {
    "slug": "resend",
    "display_name": "Resend",
    "logo_path": "pm/logos/resend.png",
    "vendor_url": "https://resend.com",
    "is_active": True,
    "sort_order": 25,
    "one_liner": ONE_LINER,
    "client_only_md": CLIENT_ONLY,
    "access_grant_md": ACCESS_GRANT,
    "your_steps_md": YOUR_STEPS,
    "traps_md": TRAPS,
    "verify_md": VERIFY,
}


def upgrade():
    conn = op.get_bind()
    if "playbooks" not in sa.inspect(conn).get_table_names():
        return
    exists = conn.execute(
        sa.text("SELECT 1 FROM playbooks WHERE slug = :s"), {"s": "resend"}
    ).first()
    if exists:
        return
    cols = ", ".join(FIELDS)
    vals = ", ".join(f":{k}" for k in FIELDS)
    conn.execute(sa.text(f"INSERT INTO playbooks ({cols}) VALUES ({vals})"), FIELDS)


def downgrade():
    conn = op.get_bind()
    if "playbooks" in sa.inspect(conn).get_table_names():
        conn.execute(sa.text("DELETE FROM playbooks WHERE slug = :s"), {"s": "resend"})
