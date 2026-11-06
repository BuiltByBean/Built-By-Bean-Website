# -*- coding: utf-8 -*-
"""The inbox: all of Primary, read and answered on the board (issue #40).

Gmail and SMTP are faked; everything else is the board's own code:

  1. A sync stores inbound and sent mail once, threads by Gmail's conversation
     id, lists attachments, and files a client's mail to the client.
  2. A stranger's mail is the inbox's alone: never on Needs attention.
  3. The first read of the whole inbox is quiet: old mail moves no stage and
     does not wait on Needs attention.
  4. An answer sent in Gmail answers the mail before it.
  5. Read in Gmail is read here; opening a conversation reads it here.
  6. Reply is reply-all, threaded, from his address, and a double press sends once.
  7. New message, archive and back, search, the views, the unread count.
  8. The page draws for the CEO and nobody else; quoted mail is trimmed.

Run: python tools/test_inbox.py
"""
import email
import json
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-inbox-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["MAIL_SYNC_DISABLED"] = "1"
for flag in ("STRIPE_IMPORT_DISABLED", "HUB_PULL_DISABLED", "HUB_PUSH_DISABLED"):
    os.environ[flag] = "1"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from pm import mail_service  # noqa: E402
from app import create_app  # noqa: E402
from models import db, Client, Message, User  # noqa: E402

application = create_app()
application.config.update(WTF_CSRF_ENABLED=False, MAIL_USERNAME="michael@builtbybean.test",
                          MAIL_PASSWORD="app-password", MAIL_DEFAULT_SENDER="michael@builtbybean.test")
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def ago(days=0, hours=0):
    return (datetime.now(timezone.utc) - timedelta(days=days, hours=hours)).strftime("%a, %d %b %Y %H:%M:%S +0000")


def mail(frm, to, subject, body, mid, when, cc=None, refs=None, attach=False):
    if attach:
        raw = (f"From: {frm}\r\nTo: {to}\r\n" + (f"Cc: {cc}\r\n" if cc else "")
               + f"Subject: {subject}\r\nMessage-ID: {mid}\r\nDate: {when}\r\n"
               + (f"In-Reply-To: {refs}\r\nReferences: {refs}\r\n" if refs else "")
               + "MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=XX\r\n\r\n"
               + f"--XX\r\nContent-Type: text/plain\r\n\r\n{body}\r\n"
               + "--XX\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename=\"quote.pdf\"\r\n"
               + "Content-Transfer-Encoding: base64\r\n\r\nJVBERi0xLjQK\r\n--XX--\r\n")
    else:
        raw = (f"From: {frm}\r\nTo: {to}\r\n" + (f"Cc: {cc}\r\n" if cc else "")
               + f"Subject: {subject}\r\nMessage-ID: {mid}\r\nDate: {when}\r\n"
               + (f"In-Reply-To: {refs}\r\nReferences: {refs}\r\n" if refs else "")
               + f"\r\n{body}\r\n")
    return email.message_from_string(raw)


GMAIL = {}      # gm id -> (msg, thrid, seen)


def fake_fetch(app, known, **kw):
    have = known(set(GMAIL))
    items = [(m, {"X-GM-MSGID": g, "X-GM-THRID": t, "seen": s})
             for g, (m, t, s) in sorted(GMAIL.items()) if g not in have]
    return {"items": items, "window": set(GMAIL), "unread": {g for g, (_, _, s) in GMAIL.items() if not s}}


SENT = []


class FakeSMTP:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, *a):
        pass

    def send_message(self, mime, from_addr=None, to_addrs=None):
        SENT.append({"to": mime["To"], "cc": mime["Cc"], "subject": mime["Subject"],
                     "irt": mime["In-Reply-To"], "refs": mime["References"], "rcpt": to_addrs,
                     "mid": mime["Message-ID"], "raw": mime})


mail_service.fetch_primary = fake_fetch
mail_service.smtplib.SMTP = FakeSMTP

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="michael@builtbybean.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    member = User(username="hb", email="hannah@builtbybean.test", first_name="Hannah", role="cmo")
    member.set_password("x")
    kenali = Client(name="J and D", email="kkendrick@jdentertain.test", stage="active_client")
    db.session.add_all([boss, member, kenali])
    db.session.commit()
    boss_id, member_id, kenali_id = boss.id, member.id, kenali.id

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
other = application.test_client()
with other.session_transaction() as s:
    s["_user_id"] = str(member_id)

print("1. The first read: quiet")
GMAIL["1"] = (mail("Kenali <kkendrick@jdentertain.test>", "michael@builtbybean.test", "Old question",
                   "Did the invoice go out?", "<old1@jd>", ago(days=20)), "T1", True)
GMAIL["2"] = (mail("Newsletter Person <hi@stranger.test>", "michael@builtbybean.test", "Hello there",
                   "Just saying hi", "<s1@x>", ago(hours=5)), "T2", False)
with application.app_context():
    r = mail_service.sync(force=True)
    check("the first pass stores both", r.get("new") == 2, r)
    old = Message.query.filter_by(external_id="<old1@jd>").first()
    check("old client mail is filed to the client", old.client_id == kenali_id)
    check("but does not wait on Needs attention", old.status == "archived")
    check("and moved no stage", db.session.get(Client, kenali_id).stage == "active_client")
    s1 = Message.query.filter_by(external_id="<s1@x>").first()
    check("a stranger's mail is stored", s1 is not None and s1.direction == "in")
    check("and is not watched", s1.watched is False)
    check("read in Gmail means read here", old.seen_at is not None and s1.seen_at is None)
    from pm.attention_routes import attention_counts
    check("Needs attention shows neither", attention_counts().get("total", 0) == 0, attention_counts())

print("1b. A later pass reading old mail: still history (2026-11-06)")
with application.app_context():
    from models import Lead, LeadTouch
    early = Client(name="Early Co", email="boss@early.test", stage="lead")
    shop = Lead(name="Cable Co", dedupe_key="cable|1", website="https://cable.test", stage="lead")
    db.session.add_all([early, shop])
    db.session.commit()
    early_id, shop_id = early.id, shop.id
GMAIL["10"] = (mail("Boss <boss@early.test>", "michael@builtbybean.test", "From weeks ago",
                    "Old words", "<e1@early>", ago(days=25)), "T10", False)
GMAIL["11"] = (mail("Billing <bills@cable.test>", "michael@builtbybean.test", "Your bill is ready",
                    "Pay it", "<c1@cable>", ago(hours=2)), "T11", False)
with application.app_context():
    mail_service.sync(force=True)
    e1 = Message.query.filter_by(external_id="<e1@early>").first()
    check("old mail on a later pass is history", e1.status == "archived" and e1.client_id == early_id)
    check("and moves no client", db.session.get(Client, early_id).stage == "lead")
    c1 = Message.query.filter_by(external_id="<c1@cable>").first()
    check("a lead is never matched by its website's domain", c1.watched is False)
    check("so it logs no contact and moves no lead",
          LeadTouch.query.filter_by(lead_id=shop_id).count() == 0 and db.session.get(Lead, shop_id).stage == "lead")
    from pm.attention_routes import attention_counts
    check("Needs attention still shows nothing", attention_counts().get("total", 0) == 0, attention_counts())
for k in ("10", "11"):
    del GMAIL[k]
with application.app_context():
    for ext in ("<e1@early>", "<c1@cable>"):
        db.session.delete(Message.query.filter_by(external_id=ext).first())
    db.session.commit()

print("2. Later passes: threads, sent mail, attachments")
GMAIL["3"] = (mail("Kenali <kkendrick@jdentertain.test>", "michael@builtbybean.test", "Re: Old question",
                   "Also, here is the quote.\n\nOn Tue, Nov 3, 2026 at 9:00 AM Michael wrote:\n> earlier",
                   "<k2@jd>", ago(hours=3), cc="Loui <loui@jdentertain.test>, michael@builtbybean.test",
                   refs="<old1@jd>", attach=True), "T1", False)
GMAIL["4"] = (mail("Michael Bean <michael@builtbybean.test>", "hi@stranger.test", "Re: Hello there",
                   "Hi back", "<m1@bbb>", ago(hours=4), refs="<s1@x>"), "T2", True)
with application.app_context():
    r = mail_service.sync(force=True)
    check("two new", r.get("new") == 2, r)
    k2 = Message.query.filter_by(external_id="<k2@jd>").first()
    check("a reply joins its conversation by Gmail's thread", k2.thread_id == old.id)
    check("a client's new mail waits on Needs attention", k2.status == "new" and k2.watched)
    check("its attachment is listed, the file left in Gmail",
          [a["name"] for a in k2.attachments] == ["quote.pdf"], k2.attachments)
    check("who else was on it is kept", ["Loui", "loui@jdentertain.test"] in k2.recipients["cc"], k2.recipients)
    m1 = Message.query.filter_by(external_id="<m1@bbb>").first()
    check("his own mail from Gmail is sent mail", m1.direction == "out" and m1.status == "sent")
    check("and it answers the mail before it", db.session.get(Message, s1.id).status == "replied")
    check("the quoted mail is trimmed", "earlier" not in k2.short_body and "the quote" in k2.short_body)
    r = mail_service.sync(force=True)
    check("read again, stored once", r.get("new") == 0 and Message.query.count() == 4, r)
    from pm.messages_routes import unread_count
    check("the unread count is the client's new mail and the stranger's", unread_count() == 2, unread_count())
    old_id, k2_id, s1_id = old.id, k2.id, s1.id

print("3. The page")
r = c.get("/admin/messages/")
page = r.get_data(as_text=True)
check("the inbox draws", r.status_code == 200, r.status_code)
check("both conversations are on it", "Old question" in page and "Hello there" in page)
check("the sidebar link carries the count", 'data-live="nav-inbox"' in page)
check("only the CEO opens it", other.get("/admin/messages/").status_code in (302, 403))
c.get(f"/admin/messages/{s1_id}")
unread_page = c.get("/admin/messages/?view=unread").get_data(as_text=True)
check("opened, it leaves the unread view", "Old question" in unread_page and "Hello there" not in unread_page)
check("clients and leads leaves the stranger out",
      "Hello there" not in c.get("/admin/messages/?view=clients").get_data(as_text=True))
check("search finds by words in the body", "Hello there" in c.get("/admin/messages/?q=saying").get_data(as_text=True)
      and "Old question" not in c.get("/admin/messages/?q=saying").get_data(as_text=True))
r = c.get(f"/admin/messages/{old_id}")
page = r.get_data(as_text=True)
check("a conversation opens", r.status_code == 200 and "the quote" in page)
check("with its attachment to open", f"/admin/messages/{k2_id}/file/" in page)
check("reply goes to them and Cc's the rest, never him",
      "To kkendrick@jdentertain.test" in page and "Cc loui@jdentertain.test" in page, page[page.find("To kk") - 50:page.find("To kk") + 120])
with application.app_context():
    check("opening it reads it", db.session.get(Message, k2_id).seen_at is not None)
    from pm.messages_routes import unread_count
    check("and the count goes to nothing", unread_count() == 0)

print("4. Reply, once")
key = "press-1"
r = c.post(f"/admin/messages/{old_id}/reply", data={"body": "Thanks, got it.", "send_key": key, "reply_all": "1"})
check("reply sends", r.status_code in (302, 303) and len(SENT) == 1, (r.status_code, SENT))
check("to them, Cc the colleague",
      SENT and "kkendrick@jdentertain.test" in SENT[0]["to"] and "loui@jdentertain.test" in (SENT[0]["cc"] or ""))
check("threaded to the last mail with the whole chain",
      SENT and SENT[0]["irt"] == "<k2@jd>" and "<old1@jd>" in (SENT[0]["refs"] or ""), SENT and SENT[0])
c.post(f"/admin/messages/{old_id}/reply", data={"body": "Thanks, got it.", "send_key": key, "reply_all": "1"})
check("a double press sends once", len(SENT) == 1, len(SENT))
with application.app_context():
    check("the client's mail is answered", db.session.get(Message, k2_id).status == "replied")
    out = Message.query.filter_by(send_key=key).first()
    check("the reply is in the conversation", out and out.thread_id == old_id)
    mid = out.external_id
GMAIL["5"] = (mail("Michael Bean <michael@builtbybean.test>", "kkendrick@jdentertain.test", "Re: Old question",
                   "Thanks, got it.", mid, ago()), "T1", True)
with application.app_context():
    mail_service.sync(force=True)
    check("Gmail's Sent copy of a board reply is the same row",
          Message.query.filter_by(external_id=mid).count() == 1
          and Message.query.filter_by(external_id=mid).first().gm_msgid == "5")
r = c.post(f"/admin/messages/{old_id}/reply", data={"body": "Just them", "send_key": "press-2", "reply_all": "0"})
check("reply to one leaves Cc empty", len(SENT) == 2 and not SENT[1]["cc"], SENT[-1:])

print("5. New message, archive, read in Gmail")
r = c.post("/admin/messages/send", data={"to": "Pat <pat@paris.test>, sam@paris.test", "cc": "",
                                         "subject": "Catching up", "body": "Coffee?", "send_key": "press-3"})
check("a new message goes to everyone named", len(SENT) == 3 and "pat@paris.test" in SENT[2]["to"]
      and "sam@paris.test" in SENT[2]["to"], SENT[-1:])
check("a new message without a subject is refused",
      c.post("/admin/messages/send", data={"to": "x@y.test", "subject": "", "body": "b"}).status_code in (302, 303)
      and len(SENT) == 3)
r = c.post(f"/admin/messages/{s1_id}/archive", data={})
check("archive takes it off the list",
      "Hello there" not in c.get("/admin/messages/").get_data(as_text=True)
      and "Hello there" in c.get("/admin/messages/?view=archived").get_data(as_text=True))
GMAIL["6"] = (mail("Newsletter Person <hi@stranger.test>", "michael@builtbybean.test", "Re: Hello there",
                   "One more thing", "<s2@x>", ago(hours=1), refs="<m1@bbb>"), "T2", False)
with application.app_context():
    mail_service.sync(force=True)
check("something new brings it back", "Hello there" in c.get("/admin/messages/").get_data(as_text=True))
GMAIL["6"] = (GMAIL["6"][0], "T2", True)
with application.app_context():
    r = mail_service.sync(force=True)
    check("read in Gmail later clears it here", r.get("read_in_gmail") == 1 and
          Message.query.filter_by(external_id="<s2@x>").first().seen_at is not None, r)

print("6. Trimming what was quoted")
t = "Sounds good.\n\nOn Mon, Nov 2, 2026 at 3:14 PM Michael Bean <m@b.test>\nwrote:\n> old words"
check("a two-line 'On ... wrote:' is cut", mail_service.clean_text(t) == "Sounds good.", mail_service.clean_text(t))
check("a signature is cut", mail_service.clean_text("Yes.\n-- \nPat\nCEO") == "Yes.")
check("nothing left means the whole mail", mail_service.clean_text("> all quoted") == "> all quoted")
check("a broken tag's leftovers are trimmed",
      "width=" not in mail_service.clean_text('Optimum 96 &nbsp; alt="" width="1" height="1" />\nYour bill'))
check("a > inside an attribute does not break a tag",
      mail_service._strip_html('<p>Hi<img src="a?b>c" alt="" width="1"/> there</p>') == "Hi there")
check("comments and double-escaped spaces go",
      mail_service._strip_html("<!--[if mso]><x><![endif]--><p>ok&amp;nbsp;</p>") == "ok")
check("the board's pages tell Cloudflare not to hide addresses",
      "<!--email_off-->" in c.get("/admin/messages/").get_data(as_text=True))

print("7. Email templates: the intro")
import email_templates  # noqa: E402
from models import CatalogLink  # noqa: E402
r = c.get("/admin/messages/templates")
check("Templates opens the first one", r.status_code in (301, 302) and "/templates/intro" in r.headers["Location"])
page = c.get("/admin/messages/templates/intro").get_data(as_text=True)
check("the intro draws with its facts", "Higginbotham" in page and "4,500" in page and "senior data analyst" in page)
check("no em dash in it", "—" not in email_templates.DEFAULTS["intro"]["body"])
check("only the CEO opens it", other.get("/admin/messages/templates/intro").status_code in (302, 403))
before = len(SENT)
data = {"name": "Dana Ortiz", "email": "Dana@OrtizFarms.test", "company": "Ortiz Farms",
        "personal_line": "We met at the Paris chamber lunch.", "send_key": "tpl-1",
        "subject": email_templates.DEFAULTS["intro"]["subject"], "body": email_templates.DEFAULTS["intro"]["body"]}
r = c.post("/admin/messages/templates/intro/send", data=data)
check("it sends", r.status_code in (302, 303) and len(SENT) == before + 1, (r.status_code, len(SENT) - before))
sent = SENT[-1]
whole = sent["raw"].as_string()
plain = next(part.get_payload(decode=True).decode() for part in sent["raw"].walk() if part.get_content_type() == "text/plain")
check("to them, with their company in the subject", "dana@ortizfarms.test" in sent["to"] and sent["subject"] == "Custom software for Ortiz Farms", sent)
check("their first name and your line", plain.startswith("Hi Dana,") and "Paris chamber lunch" in plain, plain[:200])
with application.app_context():
    links = CatalogLink.query.filter_by(email="dana@ortizfarms.test").all()
    check("one catalog link made for them, marked sent", len(links) == 1 and links[0].sent_at is not None
          and links[0].label == "Dana Ortiz, Ortiz Farms", [(l.label, l.sent_at) for l in links])
    token = links[0].token
    until = f"{links[0].expires_at.strftime('%B')} {links[0].expires_at.day}"
check("the link in the mail is theirs", f"/work/{token}" in plain and f"/work/{token}" in whole)
check("and says how long it lasts", f"until {until}" in plain, until)
check("the HTML carries it as a button", "See the work" in whole)
c.post("/admin/messages/templates/intro/send", data=data)
with application.app_context():
    check("a double press sends once and makes one link", len(SENT) == before + 1
          and CatalogLink.query.filter_by(email="dana@ortizfarms.test").count() == 1)
    row = Message.query.filter_by(send_key="tpl-1").first()
    check("it is in the inbox's sent mail", row is not None and row.direction == "out")
r = c.post("/admin/messages/templates/intro/send", data={**data, "company": "", "send_key": "tpl-2"})
check("no company, nothing sent", len(SENT) == before + 1)
s, text_out, html_out = email_templates.render(email_templates.DEFAULTS["intro"], {
    "first_name": "Pat", "company": "<Acme & Co>", "personal_line": "", "catalog_link": "https://x/work/t",
    "link_until": "December 6"})
check("no line of your own leaves no gap", "\n\n\n" not in text_out and "Hi Pat,\n\nMy name" in text_out)
check("the HTML escapes what was typed", "&lt;Acme &amp; Co&gt;" in html_out and "<Acme" not in html_out)
c.post("/admin/messages/templates/intro/save", data={"subject": "Hello {company}", "body": "Hi {first_name}.\n\n{catalog_link}"})
with application.app_context():
    check("an edit is kept", email_templates.get("intro")["subject"] == "Hello {company}" and email_templates.get("intro")["edited"])
c.post("/admin/messages/templates/intro/reset")
with application.app_context():
    check("and the original comes back", email_templates.get("intro")["subject"] == "Custom software for {company}")

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
os._exit(1 if FAIL else 0)
