# -*- coding: utf-8 -*-
"""Mail is read on a timer, not only when a page is opened.

docs/automation_gaps.md item 4 (the mail part). Proves, with IMAP faked:

  1. create_app starts the background sync, and a client's mail lands as a
     Message with no page opened and nobody pressing anything.
  2. Mail switched on after the boot is picked up without a restart.
  3. One thread per app however often it is asked, and none when switched off.
  4. The pass reads the same mail again and stores it once.

Run: python tools/test_mail_every_five.py
"""
import email
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-mail-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)
for flag in ("STRIPE_IMPORT_DISABLED", "HUB_PULL_DISABLED", "HUB_PUSH_DISABLED"):
    os.environ[flag] = "1"
os.environ.pop("MAIL_SYNC_DISABLED", None)
os.environ["MAIL_SYNC_FIRST_DELAY_SECONDS"] = "0"
os.environ["MAIL_SYNC_INTERVAL_SECONDS"] = "1"
os.environ.pop("MAIL_USERNAME", None)
os.environ.pop("MAIL_PASSWORD", None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from pm import mail_service  # noqa: E402

# A mailbox with one message from a client in it. Patched before the app
# exists, so the very first pass of the app's own thread reads it.
MAIL = email.message_from_string(
    "From: Cason <cason@kuper.test>\r\nTo: michael@builtbybean.test\r\n"
    "Subject: Invoice question\r\nMessage-ID: <abc123@kuper.test>\r\n"
    "Date: Tue, 03 Nov 2026 10:00:00 -0600\r\n\r\nWhen is the next one due?\r\n")
READS = []


def fake_fetch(app, senders, since):
    READS.append(sorted(senders))
    return [MAIL]


mail_service.fetch_recent = fake_fetch
mail_service.SYNC_EVERY_SECONDS = 0  # every pass is due, so the test is quick

from app import create_app  # noqa: E402
from models import db, Client, Message  # noqa: E402

application = create_app()
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def wait_for(cond, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


with application.app_context():
    db.create_all()
    db.session.add(Client(name="Kuper Plumbing", email="cason@kuper.test"))
    db.session.commit()

print("1. Off until mail is configured, then on with no restart")
check("the app started its own mail thread", mail_service._timer["started"])
check("and it serves the newest app", mail_service._timer["app"] is application)
time.sleep(2.5)
check("nothing is read while mail is not configured", READS == [], READS)

application.config["MAIL_USERNAME"] = "michael@builtbybean.test"
application.config["MAIL_PASSWORD"] = "app-password"


def stored():
    with application.app_context():
        return Message.query.filter_by(external_id="<abc123@kuper.test>").count()


check("a client's mail lands with no page opened", wait_for(lambda: stored() == 1))
with application.app_context():
    row = Message.query.filter_by(external_id="<abc123@kuper.test>").first()
    client = Client.query.filter_by(email="cason@kuper.test").first()
    check("and it is matched to the client", row is not None and row.client_id == client.id)
check("the client's address is a watched sender", READS and "cason@kuper.test" in READS[0])

print("2. Read again, stored once")
before = len(READS)
wait_for(lambda: len(READS) >= before + 2, seconds=8)
check("the timer keeps reading", len(READS) >= before + 2, len(READS))
check("and the same mail is still one row", stored() == 1)

print("3. One thread, and none when switched off")
check("a second start in the same process does nothing", mail_service.start_background(application) is False)
names = [t.name for t in __import__("threading").enumerate()]
# app.py builds one app on import and create_app() a second: still one timer.
check("exactly one mail timer thread", names.count("mail-sync-timer") == 1, names)


class Fake:
    pass


os.environ["MAIL_SYNC_DISABLED"] = "1"
check("switched off, no thread starts", mail_service.start_background(Fake()) is False)
os.environ.pop("MAIL_SYNC_DISABLED")
os.environ["MAIL_SYNC_INTERVAL_SECONDS"] = "0"
check("an interval of 0 is off too", mail_service.start_background(Fake()) is False)

print("4. The two workers")
with application.app_context():
    check("on SQLite there is one process, so the turn is always ours", mail_service._our_turn())

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
os._exit(1 if FAIL else 0)
