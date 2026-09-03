"""Michael's Gmail, read and written from the board.

The board already sent through his Gmail with an app password, and an app
password opens IMAP as well as SMTP. So this needs no Google Cloud
project, no OAuth dance, no token to refresh: the same two settings that
send the contact form's notification read the inbox and send the replies.

Reading is selective on purpose. Only mail from a watched sender comes in:
every client's address on the board, and everyone who has ever written
through the site's form, so a conversation that began there can carry on
by email and still be seen here. Nothing else in the inbox is touched, and
the mailbox is opened read-only - the board never marks, moves or deletes
anything in Gmail.

Sync runs in the background when a page that shows mail is opened, at
most every five minutes, so the page renders at once and the next look
has the new mail. "Check mail" on the messages page is the synchronous
version for when he is waiting on something.

Replies carry a real In-Reply-To, so they thread in the client's mail
client, and go out through Gmail's SMTP, so Gmail keeps them in Sent as
though they had been typed there.
"""
import email
import html
import imaplib
import logging
import re
import smtplib
import threading
import time
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid, parseaddr, parsedate_to_datetime

from flask import current_app

from models import db, Client, Message

log = logging.getLogger(__name__)

SYNC_EVERY_SECONDS = 300
FIRST_SYNC_DAYS = 30
BODY_CAP = 20000

_state = {"last": 0.0, "running": False, "error": None, "new": 0}


def configured(app=None):
    app = app or current_app
    return bool(app.config.get("MAIL_USERNAME") and app.config.get("MAIL_PASSWORD"))


def status():
    return dict(_state)


# ── Who to listen for ────────────────────────────────────


def watched_senders():
    emails = set()
    for (addr,) in db.session.query(Client.email).filter(Client.email.isnot(None)).all():
        addr = (addr or "").strip().lower()
        if addr:
            emails.add(addr)
    for (addr,) in (db.session.query(Message.from_email)
                    .filter(Message.direction == "in").distinct().all()):
        addr = (addr or "").strip().lower()
        if addr:
            emails.add(addr)
    return sorted(emails)


def match_client(address):
    address = (address or "").strip().lower()
    if not address:
        return None
    return Client.query.filter(db.func.lower(Client.email) == address).first()


# ── Reading ──────────────────────────────────────────────


def fetch_recent(app, senders, since, per_sender=50):
    """Raw messages in the inbox from any of `senders`, dated on or after
    `since`. Newest `per_sender` per address, so one chatty client cannot
    make a sync take a minute."""
    out = []
    conn = imaplib.IMAP4_SSL(app.config.get("IMAP_SERVER", "imap.gmail.com"), 993)
    try:
        conn.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
        conn.select("INBOX", readonly=True)
        since_str = since.strftime("%d-%b-%Y")
        for sender in senders:
            typ, data = conn.search(None, "FROM", f'"{sender}"', "SINCE", since_str)
            if typ != "OK" or not data or not data[0]:
                continue
            for num in data[0].split()[-per_sender:]:
                typ, parts = conn.fetch(num, "(RFC822)")
                if typ != "OK" or not parts or not isinstance(parts[0], tuple):
                    continue
                out.append(email.message_from_bytes(parts[0][1]))
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001 - already leaving
            pass
    return out


def _decode(value):
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:  # noqa: BLE001 - a bad header is still a header
        return value or ""


def _payload(part):
    raw = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return raw.decode(charset, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


_TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def _strip_html(text):
    text = _TAGS.sub(" ", text or "")
    text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", text, flags=re.I)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    lines = [" ".join(l.split()) for l in text.splitlines()]
    return "\n".join(l for l in lines if l)


def body_text(msg):
    """The readable part of a mail: text/plain when it has one, otherwise
    the HTML with its tags taken out."""
    if msg.is_multipart():
        plain = html_part = None
        for part in msg.walk():
            if "attachment" in str(part.get("Content-Disposition") or ""):
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain" and plain is None:
                plain = _payload(part)
            elif ctype == "text/html" and html_part is None:
                html_part = _payload(part)
        text = plain if plain is not None else _strip_html(html_part or "")
    elif msg.get_content_type() == "text/html":
        text = _strip_html(_payload(msg))
    else:
        text = _payload(msg)
    return text.strip()[:BODY_CAP]


def _when(msg):
    try:
        when = parsedate_to_datetime(msg.get("Date"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001 - no date is still a mail
        return datetime.now(timezone.utc)


def ingest(msg):
    """One parsed mail into one row. Returns the row, or None if it was
    already here."""
    external_id = (msg.get("Message-ID") or "").strip()[:300]
    if external_id and Message.query.filter_by(external_id=external_id).first():
        return None
    name, addr = parseaddr(_decode(msg.get("From")))
    addr = (addr or "").strip().lower()
    if not addr:
        return None
    row = Message(
        source="gmail", direction="in", from_name=_decode(name)[:200],
        from_email=addr[:200], to_email=parseaddr(_decode(msg.get("To")))[1][:200],
        subject=_decode(msg.get("Subject"))[:300], body=body_text(msg),
        external_id=external_id or None, received_at=_when(msg), status="new",
    )
    client = match_client(addr)
    row.client_id = client.id if client else None

    # Threaded to what it answers, when that is something the board sent
    # or already holds; otherwise it starts a conversation of its own.
    parent = None
    for ref in [msg.get("In-Reply-To") or ""] + (msg.get("References") or "").split():
        ref = ref.strip()
        if ref:
            parent = Message.query.filter_by(external_id=ref).first()
            if parent:
                break
    db.session.add(row)
    db.session.flush()
    if parent:
        row.in_reply_to_id = parent.id
        row.thread_id = parent.thread_id or parent.id
    else:
        row.thread_id = row.id
    return row


def sync(app=None, force=False):
    """Pull what is new. Returns a dict saying what happened."""
    app = app or current_app
    if not configured(app):
        return {"skipped": "mail is not configured"}
    now = time.monotonic()
    if not force and now - _state["last"] < SYNC_EVERY_SECONDS:
        return {"skipped": "recent"}
    if _state["running"]:
        return {"skipped": "running"}
    _state["running"] = True
    try:
        senders = watched_senders()
        if not senders:
            _state.update(last=now, error=None, new=0)
            return {"new": 0, "senders": 0}
        latest = (db.session.query(db.func.max(Message.received_at))
                  .filter(Message.direction == "in", Message.source == "gmail").scalar())
        since = ((latest - timedelta(days=2)) if latest
                 else datetime.now(timezone.utc) - timedelta(days=FIRST_SYNC_DAYS))
        created = 0
        for msg in fetch_recent(app, senders, since):
            if ingest(msg) is not None:
                created += 1
        db.session.commit()
        _state.update(last=now, error=None, new=created)
        return {"new": created, "senders": len(senders)}
    except Exception as err:  # noqa: BLE001 - reported, never raised into a page
        db.session.rollback()
        _state.update(last=now, error=str(err)[:300])
        log.warning("mail sync failed: %s", err)
        return {"error": str(err)[:300]}
    finally:
        _state["running"] = False


def kick(app):
    """Sync in the background if one is due, so the page opens now."""
    if not configured(app) or _state["running"]:
        return False
    if time.monotonic() - _state["last"] < SYNC_EVERY_SECONDS:
        return False

    def run():
        with app.app_context():
            try:
                sync(app)
            finally:
                db.session.remove()

    threading.Thread(target=run, daemon=True, name="mail-sync").start()
    return True


# ── Writing ──────────────────────────────────────────────


def send_reply(original, text, app=None):
    """Answer a message from Michael's own address, threaded to it.
    Returns the outbound row."""
    app = app or current_app
    if not configured(app):
        raise RuntimeError("mail is not configured")
    username = app.config["MAIL_USERNAME"]
    subject = original.subject or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}".strip()

    mime = MIMEText(text, "plain", "utf-8")
    mime["From"] = f"Michael Bean <{username}>"
    to_name = original.from_name or ""
    mime["To"] = f"{to_name} <{original.from_email}>" if to_name else original.from_email
    mime["Subject"] = subject
    mime["Date"] = formatdate(localtime=False)
    message_id = make_msgid(domain="builtbybeans.com")
    mime["Message-ID"] = message_id
    if original.external_id:
        mime["In-Reply-To"] = original.external_id
        mime["References"] = original.external_id

    with smtplib.SMTP(app.config.get("MAIL_SERVER", "smtp.gmail.com"),
                      int(app.config.get("MAIL_PORT", 587))) as server:
        server.starttls()
        server.login(username, app.config["MAIL_PASSWORD"])
        server.send_message(mime)

    now = datetime.now(timezone.utc)
    row = Message(
        source=original.source, direction="out", from_name="Michael Bean",
        from_email=username, to_email=original.from_email, subject=subject,
        body=text, external_id=message_id, in_reply_to_id=original.id,
        thread_id=original.thread_id or original.id, client_id=original.client_id,
        status="sent", received_at=now,
    )
    db.session.add(row)
    original.status = "replied"
    original.replied_at = now
    db.session.commit()
    return row


def record_contact(name, address, project_type, body):
    """The site's form, written straight to the board."""
    address = (address or "").strip().lower()
    row = Message(
        source="contact_form", direction="in", from_name=(name or "")[:200],
        from_email=address[:200], subject=f"{project_type or 'General'} inquiry"[:300],
        body=(body or "")[:BODY_CAP], project_type=(project_type or "")[:80],
        status="new", received_at=datetime.now(timezone.utc),
    )
    client = match_client(address)
    row.client_id = client.id if client else None
    db.session.add(row)
    db.session.flush()
    row.thread_id = row.id
    db.session.commit()
    return row
