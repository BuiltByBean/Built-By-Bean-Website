"""Who a mail is from, as the board knows them: a client, a lead, or nobody.

Lifted out of mail_service so the reading and the matching can change apart.
Every rule here exists because a mail that belonged to somebody was filed as
belonging to nobody, and then nothing moved:

- A client is matched on their address, and failing that on their DOMAIN. One
  address per client meant Kenali's colleague at jdentertain.com wrote in and
  the board had no idea who that was. A domain only counts when it is a
  business's own: gmail.com is millions of people, and the board's own domains
  are Michael. Two clients on one domain is a tie, and a tie is nobody, because
  a guess files one client's mail under another.
- A mail from a client is contact, so it moves the stage: a reply from
  somebody at Lead or Contacted means they are In conversation. Mail the board
  sends moves Lead to Contacted. Nothing ever walks a stage backwards.
- A contact form enquiry from somebody who is not a client finds their lead or
  writes one, and logs the enquiry on it as a touch, so the Leads page hears
  about it without anybody copying it across.
"""
from datetime import date, datetime, timezone

from models import db, Client, Lead, LeadPerson, LeadTouch, Message

# Mail providers people use for themselves. A domain on this list says nothing
# about which business somebody works for.
FREE_MAIL = frozenset("""
gmail.com googlemail.com yahoo.com ymail.com rocketmail.com hotmail.com
outlook.com live.com msn.com icloud.com me.com mac.com aol.com proton.me
protonmail.com pm.me gmx.com gmx.net mail.com zoho.com yandex.com att.net
sbcglobal.net bellsouth.net comcast.net verizon.net cox.net charter.net
spectrum.net earthlink.net windstream.net frontier.com suddenlink.net
""".split())

# A reply moves these forward; anything further along was set on purpose.
EARLY_STAGES = ("lead", "contacted")


def domain_of(address):
    address = (address or "").strip().lower()
    return address.rsplit("@", 1)[1] if "@" in address else ""


def _own():
    """His addresses and domains. Imported late: mail_service imports this."""
    from pm.mail_service import own_addresses
    addrs = own_addresses()
    return addrs, {domain_of(a) for a in addrs if domain_of(a)}


def business_domain(address, own_domains=None):
    """The domain, when it can only be one business's. Otherwise ""."""
    dom = domain_of(address)
    if not dom or dom in FREE_MAIL:
        return ""
    if own_domains is None:
        own_domains = _own()[1]
    return "" if dom in own_domains else dom


def client_domains():
    """Each business domain that belongs to exactly one client.

    His own client row is left out: it carries his address, and every mail
    from his own domain is him, not a client writing in.
    """
    own_addrs, own_doms = _own()
    seen = {}
    for client in Client.query.filter(Client.email.isnot(None)).all():
        addr = (client.email or "").strip().lower()
        if not addr or addr in own_addrs:
            continue
        dom = business_domain(addr, own_doms)
        if dom:
            seen.setdefault(dom, set()).add(client.id)
    return {dom: next(iter(ids)) for dom, ids in seen.items() if len(ids) == 1}


def match_client(address):
    address = (address or "").strip().lower()
    if not address:
        return None
    exact = Client.query.filter(db.func.lower(Client.email) == address).first()
    if exact:
        return exact
    dom = business_domain(address)
    if not dom:
        return None
    client_id = client_domains().get(dom)
    return db.session.get(Client, client_id) if client_id else None


def advance_client(client, direction):
    """Move a client on because mail passed between us. Returns the new stage
    when it moved, else None."""
    if client is None:
        return None
    stage = client.stage or "lead"
    if direction == "in" and stage in EARLY_STAGES:
        client.stage = "in_conversation"
    elif direction == "out" and stage == "lead":
        client.stage = "contacted"
    else:
        return None
    return client.stage


# ── Leads ────────────────────────────────────────────────


def _host(url):
    url = (url or "").strip().lower()
    url = url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    return url[4:] if url.startswith("www.") else url


def match_lead(address):
    """The lead somebody writes from, or None. Leads already converted are
    left out: their mail is the client's."""
    address = (address or "").strip().lower()
    if not address:
        return None
    open_leads = Lead.query.filter(Lead.client_id.is_(None))
    exact = open_leads.filter(db.func.lower(Lead.email) == address).first()
    if exact:
        return exact
    person = (LeadPerson.query.join(Lead)
              .filter(Lead.client_id.is_(None),
                      db.func.lower(LeadPerson.email) == address).first())
    if person:
        return person.lead
    dom = business_domain(address)
    if not dom:
        return None
    found = {lead.id: lead for lead in open_leads.filter(
        db.or_(Lead.email.ilike(f"%@{dom}"), Lead.website.ilike(f"%{dom}%"))).all()
        if domain_of(lead.email) == dom or _host(lead.website) == dom}
    for person in (LeadPerson.query.join(Lead)
                   .filter(Lead.client_id.is_(None), LeadPerson.email.ilike(f"%@{dom}"))):
        found.setdefault(person.lead.id, person.lead)
    return next(iter(found.values())) if len(found) == 1 else None


def _advance_lead(lead):
    if (lead.stage or "lead") in EARLY_STAGES:
        lead.stage = "in_conversation"
        lead.stage_changed_at = datetime.now(timezone.utc)


def log_lead_mail(lead, message, how="Wrote in"):
    """Record a mail from a lead as a touch on it, and move it on."""
    note = f"{how}: {message.subject or 'no subject'}"
    if message.snippet:
        note += f". {message.snippet}"
    db.session.add(LeadTouch(
        lead_id=lead.id, channel="email", outcome="spoke",
        occurred_on=(message.received_at.date() if message.received_at else date.today()),
        note=note[:2000]))
    _advance_lead(lead)
    lead.updated_at = datetime.now(timezone.utc)


def lead_for_enquiry(message):
    """Find or write the lead behind a contact form enquiry, and log it."""
    from import_leads import norm
    lead = match_lead(message.from_email)
    if lead is None:
        name = (message.from_name or "").strip() or message.from_email
        key = f"{norm(name)}|{message.from_email}"[:240]
        lead = Lead.query.filter_by(dedupe_key=key).first()
        if lead is None:
            lead = Lead(dedupe_key=key, name=name[:200], owner_name=name[:160],
                        email=message.from_email, state="", sources="contact_form",
                        industry=(message.project_type or "")[:120], stage="lead")
            db.session.add(lead)
            db.session.flush()
    log_lead_mail(lead, message, how="Website enquiry")
    return lead


def file_inbound(message):
    """Match a new inbound mail to its client, or failing that its lead, and
    let the match move them on. Called once, when the row is first written."""
    client = match_client(message.from_email)
    message.client_id = client.id if client else None
    if client:
        advance_client(client, "in")
        return client
    if message.source == "contact_form":
        return lead_for_enquiry(message)
    lead = match_lead(message.from_email)
    if lead:
        log_lead_mail(lead, message)
    return lead


def relink_unmatched():
    """Give a client to inbound mail that matched nobody when it arrived.

    A client added, or given an email, after their mail came in would
    otherwise never see it on their page. Stages are not moved here: this is
    old mail being filed, not a new reply. Returns how many rows it filed.
    """
    rows = (Message.query.filter(Message.client_id.is_(None),
                                 Message.direction == "in").all())
    filed = 0
    cache = {}
    for row in rows:
        addr = (row.from_email or "").lower()
        if addr not in cache:
            cache[addr] = match_client(addr)
        if cache[addr]:
            row.client_id = cache[addr].id
            filed += 1
    # A reply sent from the board takes its client from the mail it answers.
    if filed:
        db.session.flush()
        for row in Message.query.filter(Message.client_id.is_(None),
                                        Message.direction == "out",
                                        Message.thread_id.isnot(None)).all():
            root = db.session.get(Message, row.thread_id)
            if root is not None and root.client_id:
                row.client_id = root.client_id
    return filed
