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
import hashlib
import html
import imaplib
import json
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


def own_addresses(app=None):
    """The addresses that are his, lowercased.

    The mailbox being read is one by definition: a copy of his own mail is
    not a person waiting on him. Anything else he writes from goes in
    OWN_EMAILS, because the board cannot know about it otherwise.

    Kept as one function because two places need the same answer, and a
    sender excluded from the sync but not from the attention page would go
    on showing every row it had already written.
    """
    app = app or current_app
    out = set()
    for key in ("MAIL_USERNAME", "MAIL_DEFAULT_SENDER"):
        addr = (app.config.get(key) or "").strip().lower()
        if addr:
            out.add(addr)
    for addr in (app.config.get("OWN_EMAILS") or "").split(","):
        addr = addr.strip().lower()
        if addr:
            out.add(addr)
    return out


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
    # Last, not first. His address reaches this set two ways: he has a Client
    # row of his own, and the second loop re-adds any address that has ever
    # written in, so taking it off the client list alone would not have held.
    emails -= own_addresses()
    # A client's whole business domain, so a colleague of theirs is heard
    # too. Gmail's FROM search matches "@jdentertain.com" as a substring. An
    # address the domain already covers is dropped rather than searched twice.
    from pm.contact_matching import client_domains, domain_of
    domains = set(client_domains())
    emails = {e for e in emails if domain_of(e) not in domains}
    return sorted(emails | {"@" + d for d in domains})


def match_client(address):
    """The client a mail is from: their address, else their business domain
    (pm/contact_matching.py has the rules)."""
    from pm.contact_matching import match_client as _match
    return _match(address)


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


def _fingerprint(msg, addr):
    """A stable id for a mail that carries no Message-ID of its own.

    Every sync searches a window that reaches two days behind the newest row,
    so the same mail is read again on every pass. Dedupe hung entirely on the
    Message-ID header, and the check was skipped when that header was absent -
    so a mail without one was inserted afresh every five minutes, and archiving
    it did nothing, because the row that came back was a different row. That is
    what "the email I dismissed is back" was.

    Sender, date and subject are what the mail itself supplies and do not change
    between reads. Marked `sha256:` so it cannot collide with a real Message-ID,
    which always carries an @.
    """
    seed = " |> ".join((
        addr,
        (msg.get("Date") or "").strip(),
        (_decode(msg.get("Subject")) or "").strip(),
    ))
    return "sha256:" + hashlib.sha256(seed.encode("utf-8", "replace")).hexdigest()


# ── The inbox: all of Primary (issue #40) ──────────────────

# Michael, 2026-11-06: the board reads his whole Primary inbox and his Sent
# mail, like EntertainHQ's admin Inbox, through the same app password. Gmail's
# IMAP takes Gmail's own search (X-GM-RAW) on All Mail, and hands back its own
# message and conversation ids (X-GM-MSGID, X-GM-THRID), so one search covers
# inbox and sent, the categories he never reads stay out, and a mail read
# twice is still one row.
PRIMARY_DAYS = 60
PRIMARY_QUERY = "(in:inbox OR in:sent) -category:promotions -category:social -category:forums"
MAX_NEW_PER_PASS = 400
_META = re.compile(rb"(X-GM-MSGID|X-GM-THRID|UID) (\d+)")
_FLAGS = re.compile(rb"FLAGS \(([^)]*)\)")


def _imap(app):
    conn = imaplib.IMAP4_SSL(app.config.get("IMAP_SERVER", "imap.gmail.com"), 993)
    conn.login(app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
    return conn


def _all_mail(conn):
    """Select Gmail's All Mail read-only, found by its \\All flag, because its
    name follows the account's language."""
    box = "[Gmail]/All Mail"
    typ, data = conn.list()
    for line in data or []:
        s = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
        if "\\All" in s:
            m = re.search(r'"([^"]+)"\s*$', s) or re.search(r"(\S+)\s*$", s)
            if m:
                box = m.group(1)
            break
    typ, _ = conn.select(f'"{box}"', readonly=True)
    if typ != "OK":
        raise RuntimeError("could not open All Mail")
    return box


def _meta(head):
    out = {k.decode(): v.decode() for k, v in _META.findall(head or b"")}
    f = _FLAGS.search(head or b"")
    out["seen"] = bool(f and b"\\Seen" in f.group(1))
    return out


def _fetch_items(conn, uids, what):
    """[(meta, raw or None)] for one UID FETCH of `what`."""
    out = []
    typ, data = conn.uid("FETCH", ",".join(uids), what)
    if typ != "OK":
        return out
    for item in data or []:
        if isinstance(item, tuple):
            out.append((_meta(item[0]), item[1]))
        elif isinstance(item, bytes) and b"X-GM-MSGID" in item:
            out.append((_meta(item), None))
    return out


def fetch_primary(app, known, days=PRIMARY_DAYS, limit=MAX_NEW_PER_PASS):
    """What Gmail holds in the window: the raw mail of every message not yet
    here (by X-GM-MSGID, oldest first, at most `limit`), and the ids of the
    ones still unread in Gmail. `known(ids)` answers which ids are stored."""
    conn = _imap(app)
    try:
        _all_mail(conn)
        query = f"newer_than:{days}d {PRIMARY_QUERY}"
        typ, data = conn.uid("SEARCH", "X-GM-RAW", '"' + query.replace('"', "") + '"')
        uids = (data[0].split() if typ == "OK" and data and data[0] else [])
        uids = [u.decode() for u in uids]
        metas = []
        for i in range(0, len(uids), 300):
            metas += [m for m, _ in _fetch_items(conn, uids[i:i + 300], "(UID X-GM-MSGID FLAGS)")]
        window = {m["X-GM-MSGID"] for m in metas if m.get("X-GM-MSGID")}
        unread = {m["X-GM-MSGID"] for m in metas if m.get("X-GM-MSGID") and not m["seen"]}
        have = known(window)
        new = [m for m in metas if m.get("X-GM-MSGID") and m["X-GM-MSGID"] not in have and m.get("UID")]
        new.sort(key=lambda m: int(m["UID"]))
        new = new[-limit:]
        items = []
        for i in range(0, len(new), 25):
            for meta, raw in _fetch_items(conn, [m["UID"] for m in new[i:i + 25]],
                                          "(UID X-GM-MSGID X-GM-THRID FLAGS BODY.PEEK[])"):
                if raw:
                    items.append((email.message_from_bytes(raw), meta))
        return {"items": items, "window": window, "unread": unread}
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001 - already leaving
            pass


def fetch_attachment(gm_msgid, n, app=None):
    """(filename, content type, bytes) of the n-th part of a message, read
    from Gmail when it is opened. None when Gmail no longer has it."""
    app = app or current_app
    conn = _imap(app)
    try:
        _all_mail(conn)
        typ, data = conn.uid("SEARCH", "X-GM-MSGID", str(int(gm_msgid)))
        uids = data[0].split() if typ == "OK" and data and data[0] else []
        if not uids:
            return None
        items = _fetch_items(conn, [uids[-1].decode()], "(UID X-GM-MSGID BODY.PEEK[])")
        raw = next((r for _, r in items if r), None)
        if not raw:
            return None
        for i, part in enumerate(email.message_from_bytes(raw).walk()):
            if i == n and not part.is_multipart():
                return (_decode(part.get_filename() or "") or "attachment",
                        part.get_content_type(), part.get_payload(decode=True) or b"")
        return None
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


def _addrs(values):
    from email.utils import getaddresses
    out = []
    for name, addr in getaddresses([_decode(v) for v in (values or [])]):
        addr = (addr or "").strip().lower()
        if addr and "@" in addr:
            out.append([(name or "").strip()[:120], addr[:200]])
    return out


def _attachments(msg):
    out = []
    for i, part in enumerate(msg.walk()):
        if part.is_multipart():
            continue
        name = part.get_filename()
        disp = str(part.get("Content-Disposition") or "").lower()
        if not name and "attachment" not in disp:
            continue
        payload = part.get_payload(decode=True) or b""
        out.append({"n": i, "name": (_decode(name or "") or "attachment")[:200],
                    "type": part.get_content_type(), "size": len(payload)})
    return out


_QUOTE_START = re.compile(
    r"^(On .{4,200}wrote:\s*$|-{2,} ?(Original Message|Forwarded message) ?-{2,}|"
    r"_{10,}\s*$|Sent from my (iPhone|iPad|Android))", re.I)


def clean_text(text):
    """What one person wrote, without the mail they quoted under it or their
    signature, so a thread reads like a conversation (EntertainHQ's
    cleanText). The whole mail stays in `body`; the page can show it."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    out = []
    for i, line in enumerate(lines):
        s = line.strip()
        if _QUOTE_START.match(s) or s == "--" or line.rstrip() == "-- ":
            break
        # "On Tue, Nov 4, 2026 at 9:12 AM Michael Bean <x@y>" broken over two lines.
        if s.startswith("On ") and i + 1 < len(lines) and lines[i + 1].strip().endswith("wrote:"):
            break
        if s.startswith(">"):
            continue
        out.append(line)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(out).strip())
    return cleaned or (text or "").strip()


def _naive(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _mark_replied(row):
    """An answer from him, whether sent here or in Gmail, answers every mail
    in the conversation that came before it."""
    when = _naive(row.received_at)
    for m in Message.query.filter(Message.thread_id == row.thread_id, Message.direction == "in",
                                  Message.status == "new").all():
        if when is None or _naive(m.received_at) is None or _naive(m.received_at) <= when:
            m.status = "replied"
            m.replied_at = m.replied_at or row.received_at


def ingest(msg, meta=None, quiet=False):
    """One parsed mail into one row. Returns the row, or None if it was
    already here.

    `meta` is what Gmail said about it (X-GM-MSGID, X-GM-THRID, seen). `quiet`
    is the first read of the whole inbox: old mail is filed to its client but
    moves nobody's stage and does not wait on Needs attention."""
    meta = meta or {}
    name, addr = parseaddr(_decode(msg.get("From")))
    addr = (addr or "").strip().lower()
    if not addr:
        return None
    gm_id, thrid = meta.get("X-GM-MSGID"), meta.get("X-GM-THRID")
    if gm_id and Message.query.filter_by(gm_msgid=gm_id).first():
        return None
    external_id = (msg.get("Message-ID") or "").strip()[:300]
    if not external_id:
        external_id = _fingerprint(msg, addr)
    recipients = {"to": _addrs(msg.get_all("To")), "cc": _addrs(msg.get_all("Cc"))}
    refs = " ".join((msg.get("References") or "").split())[:4000]
    existing = Message.query.filter_by(external_id=external_id).first()
    if existing:
        # Sent from the board, or read before the inbox: now Gmail has it too.
        if gm_id and not existing.gm_msgid:
            existing.gm_msgid = gm_id
            existing.gm_thrid = existing.gm_thrid or thrid
            if not existing.recipients_json:
                existing.recipients_json = json.dumps(recipients)
            existing.refs = existing.refs or refs
            if existing.attachments_json is None:
                existing.attachments_json = json.dumps(_attachments(msg))
        return None
    out = addr in own_addresses()
    when = _when(msg)
    row = Message(
        source="gmail", direction="out" if out else "in", from_name=_decode(name)[:200],
        from_email=addr[:200],
        to_email=(recipients["to"][0][1] if recipients["to"] else "")[:200],
        subject=_decode(msg.get("Subject"))[:300], body=body_text(msg),
        external_id=external_id, received_at=when, status="sent" if out else "new",
        gm_msgid=gm_id, gm_thrid=thrid, recipients_json=json.dumps(recipients), refs=refs,
        attachments_json=json.dumps(_attachments(msg)),
        seen_at=datetime.now(timezone.utc) if (out or meta.get("seen")) else None,
    )
    # Threaded by Gmail's own conversation id; failing that, to what it
    # answers, when the board holds it; otherwise it starts its own.
    parent = None
    if thrid:
        parent = (Message.query.filter_by(gm_thrid=thrid)
                  .order_by(Message.received_at, Message.id).first())
    if parent is None:
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
    root = db.session.get(Message, row.thread_id) if parent else None
    from pm.contact_matching import file_inbound, match_lead
    if out:
        # His own mail: filed to the client it went to, and an answer to
        # everything before it in the conversation.
        for _, e in recipients["to"] + recipients["cc"]:
            client = match_client(e)
            if client:
                row.client_id = client.id
                break
        row.watched = bool(row.client_id) or bool(root and root.watched)
        _mark_replied(row)
    elif quiet:
        client = match_client(addr)
        row.client_id = client.id if client else None
        row.watched = bool(client) or bool(match_lead(addr)) or bool(root and root.watched)
        # Old mail is history, not a wait: only the last three days ask.
        if _naive(when) < _naive(datetime.now(timezone.utc)) - timedelta(days=3):
            row.status = "archived"
    else:
        # A client's mail is contact: it files the row and moves their stage.
        # A lead's is logged on the lead. Anyone else is the inbox's alone.
        filed = file_inbound(row)
        row.watched = bool(filed) or bool(root and root.watched)
    return row


def _known(ids):
    have = set()
    ids = list(ids)
    for i in range(0, len(ids), 500):
        have |= {g for (g,) in db.session.query(Message.gm_msgid)
                 .filter(Message.gm_msgid.in_(ids[i:i + 500])).all()}
    return have


def sync(app=None, force=False, every=None):
    """Pull what is new. Returns a dict saying what happened."""
    app = app or current_app
    if not configured(app):
        return {"skipped": "mail is not configured"}
    now = time.monotonic()
    every = SYNC_EVERY_SECONDS if every is None else every
    if not force and now - _state["last"] < every:
        return {"skipped": "recent"}
    if _state["running"]:
        return {"skipped": "running"}
    _state["running"] = True
    try:
        if not _our_turn():
            # The other gunicorn worker is reading the same mailbox right
            # now; it will write what this pass would have.
            _state.update(last=now)
            return {"skipped": "another worker"}
        first = not db.session.query(Message.id).filter(Message.gm_msgid.isnot(None)).first()
        got = fetch_primary(app, _known)
        created = 0
        for msg, meta in got["items"]:
            if ingest(msg, meta, quiet=first) is not None:
                created += 1
        # Read in Gmail is read here too.
        cleared = 0
        if got["window"]:
            for row in (Message.query.filter(Message.direction == "in", Message.seen_at.is_(None),
                                             Message.gm_msgid.isnot(None)).all()):
                if row.gm_msgid in got["window"] and row.gm_msgid not in got["unread"]:
                    row.seen_at = datetime.now(timezone.utc)
                    cleared += 1
        from pm.contact_matching import relink_unmatched
        relink_unmatched()
        db.session.commit()
        _state.update(last=now, error=None, new=created)
        return {"new": created, "read_in_gmail": cleared}
    except Exception as err:  # noqa: BLE001 - reported, never raised into a page
        db.session.rollback()
        _state.update(last=now, error=str(err)[:300])
        log.warning("mail sync failed: %s", err)
        return {"error": str(err)[:300]}
    finally:
        _state["running"] = False


# Any constant will do, as long as nothing else in the app takes the same one.
MAIL_LOCK_KEY = 0x6D61696C  # "mail"


def _our_turn():
    """Only one process reads the mailbox at a time.

    The board runs two gunicorn workers, and each starts its own background
    sync on the same schedule from the same boot, so without this they read
    the same new mail at the same moment and the second insert of it fails on
    the unique Message-ID, rolling back that whole pass. On Postgres a
    transaction-level advisory lock settles it and lets go at the commit; on
    SQLite (local and the tests) there is one process and nothing to settle.
    """
    if db.engine.dialect.name != "postgresql":
        return True
    return bool(db.session.execute(
        db.text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": MAIL_LOCK_KEY}).scalar())


_timer = {"started": False, "app": None}


def start_background(app):
    """Read the mail every five minutes whether or not anybody looks.

    It only synced when Needs attention or Messages was opened (`kick`), so the
    sidebar badge and the attention list were as old as the last visit, and a
    client's reply sat unseen until somebody happened to open the page that
    would have shown it (audit item 4). Same shape as the hub's reply sender in
    app.py: one thread per process, guarded on a flag, never allowed to die,
    and not on the boot itself, because a worker spending its first seconds on
    IMAP is not answering Railway's health check. `kick` stays, so opening the
    page still asks when a pass is due.
    """
    import os
    interval = int(os.environ.get("MAIL_SYNC_INTERVAL_SECONDS", str(SYNC_EVERY_SECONDS)))
    if interval <= 0 or os.environ.get("MAIL_SYNC_DISABLED") == "1":
        return False
    # Guarded per PROCESS, not per app: app.py builds an app when it is
    # imported and gunicorn's "app:create_app()" builds a second, so a flag on
    # the app let every worker run two timers. The timer serves the newest.
    _timer["app"] = app
    if _timer["started"]:
        return False
    _timer["started"] = True
    first_delay = int(os.environ.get("MAIL_SYNC_FIRST_DELAY_SECONDS", "90"))

    def loop():
        time.sleep(first_delay)
        while True:
            app = _timer["app"]
            try:
                # Asked every pass rather than once, so mail turned on after
                # the boot starts syncing without a deploy.
                if configured(app):
                    with app.app_context():
                        try:
                            sync(app)
                        finally:
                            db.session.remove()
            except Exception as err:  # noqa: BLE001 - a dead thread is a badge that stops
                log.warning("mail: background sync failed: %s", err)
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True, name="mail-sync-timer").start()
    return True


# While the inbox is open it asks this often, like EntertainHQ's 45 seconds.
INBOX_EVERY_SECONDS = 60


def kick(app, every=None):
    """Sync in the background if one is due, so the page opens now."""
    every = SYNC_EVERY_SECONDS if every is None else every
    if not configured(app) or _state["running"]:
        return False
    if time.monotonic() - _state["last"] < every:
        return False

    def run():
        with app.app_context():
            try:
                sync(app, every=every)
            finally:
                db.session.remove()

    threading.Thread(target=run, daemon=True, name="mail-sync").start()
    return True


# ── Writing ──────────────────────────────────────────────


def _fmt(name, addr):
    from email.utils import formataddr
    return formataddr((name, addr)) if name else addr


def send_mail(to, subject, text, cc=None, reply_to=None, send_key=None, client=None,
              html_body=None, source="board", app=None):
    """Send one mail from Michael's own address and file it. Returns
    (row, sent): `sent` is False when this press (`send_key`) already went,
    and the row is the one it sent then.

    `to` and `cc` are [(name, email)]. `reply_to` is the board's row it
    answers: the reply carries In-Reply-To and the whole References chain, so
    it threads in their mail and in his Gmail, where SMTP files it in Sent."""
    from email.mime.multipart import MIMEMultipart
    app = app or current_app
    if not configured(app):
        raise RuntimeError("mail is not configured")
    if send_key:
        done = Message.query.filter_by(send_key=send_key).first()
        if done:
            return done, False
    to = [(n or "", e.strip().lower()) for n, e in (to or []) if e and "@" in e]
    cc = [(n or "", e.strip().lower()) for n, e in (cc or []) if e and "@" in e]
    if not to:
        raise ValueError("nobody to send it to")
    username = app.config["MAIL_USERNAME"]
    if html_body:
        mime = MIMEMultipart("alternative")
        mime.attach(MIMEText(text, "plain", "utf-8"))
        mime.attach(MIMEText(html_body, "html", "utf-8"))
    else:
        mime = MIMEText(text, "plain", "utf-8")
    mime["From"] = f"Michael Bean <{username}>"
    mime["To"] = ", ".join(_fmt(n, e) for n, e in to)
    if cc:
        mime["Cc"] = ", ".join(_fmt(n, e) for n, e in cc)
    mime["Subject"] = subject
    mime["Date"] = formatdate(localtime=False)
    message_id = make_msgid(domain="builtbybeans.com")
    mime["Message-ID"] = message_id
    refs = ""
    if reply_to is not None and reply_to.external_id and not reply_to.external_id.startswith("sha256:"):
        chain = (reply_to.refs or "").split() + [reply_to.external_id]
        refs = " ".join(chain[-20:])
        mime["In-Reply-To"] = reply_to.external_id
        mime["References"] = refs
    with smtplib.SMTP(app.config.get("MAIL_SERVER", "smtp.gmail.com"),
                      int(app.config.get("MAIL_PORT", 587))) as server:
        server.starttls()
        server.login(username, app.config["MAIL_PASSWORD"])
        server.send_message(mime, from_addr=username, to_addrs=[e for _, e in to + cc])

    now = datetime.now(timezone.utc)
    if client is None and reply_to is not None:
        client = reply_to.client
    if client is None:
        for _, e in to + cc:
            client = match_client(e)
            if client:
                break
    row = Message(
        source=source, direction="out", from_name="Michael Bean", from_email=username,
        to_email=to[0][1], subject=subject[:300], body=text, external_id=message_id,
        client_id=client.id if client is not None else None, status="sent", received_at=now,
        recipients_json=json.dumps({"to": [list(x) for x in to], "cc": [list(x) for x in cc]}),
        refs=refs or None, attachments_json="[]", seen_at=now, send_key=send_key or None,
        watched=bool(client) or bool(reply_to is not None and reply_to.watched),
    )
    db.session.add(row)
    db.session.flush()
    if reply_to is not None:
        row.in_reply_to_id = reply_to.id
        row.thread_id = reply_to.thread_id or reply_to.id
        _mark_replied(row)
    else:
        row.thread_id = row.id
    if client is not None:
        from pm.contact_matching import advance_client
        advance_client(client, "out")
    db.session.commit()
    return row, True


def send_reply(original, text, app=None, cc=None, send_key=None):
    """Answer a message from Michael's own address, threaded to it.
    Returns the outbound row."""
    subject = original.subject or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}".strip()
    row, _ = send_mail([(original.from_name or "", original.from_email)], subject, text,
                       cc=cc, reply_to=original, send_key=send_key,
                       source=original.source if original.source != "contact_form" else "gmail",
                       app=app)
    original.status = "replied"
    original.replied_at = original.replied_at or row.received_at
    db.session.commit()
    return row


def send_new(to_email, to_name, subject, text, html_body=None, client=None, app=None,
             cc=None, send_key=None):
    """A new message from Michael's own address (not a reply), filed in the
    board's mail like one, so the client's page shows it went. Returns the
    outbound row. Raises when mail is not configured or the server refuses."""
    row, _ = send_mail([(to_name or "", to_email)], subject, text, cc=cc, client=client,
                       html_body=html_body, send_key=send_key, app=app)
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
    db.session.add(row)
    db.session.flush()
    row.thread_id = row.id
    # Kept before anything else is tried: the enquiry is the thing that must
    # survive, and filing it is a convenience on top.
    db.session.commit()
    # A client writing in moves on; anybody else becomes, or finds, a lead.
    from pm.contact_matching import file_inbound
    try:
        file_inbound(row)
        db.session.commit()
    except Exception as err:  # noqa: BLE001 - the enquiry is already saved
        db.session.rollback()
        log.warning("filing a contact form enquiry failed: %s", err)
    return row
