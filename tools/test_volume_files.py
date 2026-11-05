# -*- coding: utf-8 -*-
"""A file the nightly service makes lands on the web service's volume.

2026-11-05: the cost-sync service has no volume, and tile upkeep's first night
re-fetched ten My Apps icons onto its own throwaway disk while the database took
the new names; the website answered 404 for all ten. Proves:

  1. Off Railway, or with a volume mounted, a write is a plain local write.
  2. On Railway with no volume, the write waits in the database, nothing lands on
     the night's own disk, and the web's drain puts it on the volume under the
     same name, where the website serves it. A name written twice (the Stripe
     statement) is one waiting file holding the newer bytes.
  3. The heal door needs the key.
  4. heal: a fetched icon whose file is gone is fetched again, an uploaded one is
     cleared, a receipt whose file is gone is let go and its expense goes back to
     Missing; files that exist are left alone.

Run: python tools/test_volume_files.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-volume-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = os.path.join(TMP, "web")
os.environ.setdefault("SECRET_KEY", "test")
os.environ["GUIDANCE_API_KEY"] = "door-key"
os.environ.pop("AWS_S3_BUCKET", None)
for k in ("RAILWAY_ENVIRONMENT", "RAILWAY_VOLUME_MOUNT_PATH"):
    os.environ.pop(k, None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, AppLink, Expense, Receipt, ReceiptMailbox, Business  # noqa: E402
import app_icon_service  # noqa: E402
import volume_files  # noqa: E402

application = create_app()
FAIL = []
WEB = os.environ["UPLOAD_FOLDER"]
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


client = application.test_client()


with application.app_context():
    db.create_all()

    print("1. With the volume here, a write is local")
    folder = os.path.join(WEB, "app_icons")
    name = app_icon_service.store(PNG, "png", folder)
    check("the file is in the web's folder", os.path.exists(os.path.join(folder, name)))

    print("2. On Railway with no volume, the write waits in the database")
    from models import VolumeInbox
    os.environ["RAILWAY_ENVIRONMENT"] = "production"
    night_folder = os.path.join(TMP, "night-disk", "app_icons")  # what cost-sync would build
    name2 = app_icon_service.store(PNG, "png", night_folder)
    rf = os.path.join(TMP, "night-disk", "receipts")
    volume_files.write(rf, "stripe-fees-acct-2026-10.html", "<p>old</p>")
    volume_files.write(rf, "stripe-fees-acct-2026-10.html", "<p>new</p>")
    db.session.commit()
    check("nothing on the night's own disk", not os.path.exists(os.path.join(night_folder, name2)))
    check("not on the web's volume yet", not os.path.exists(os.path.join(folder, name2)))
    check("two waiting files, the statement once", VolumeInbox.query.count() == 2, VolumeInbox.query.count())
    os.environ.pop("RAILWAY_ENVIRONMENT")
    check("the web's drain moves both", volume_files.drain() == 2 and VolumeInbox.query.count() == 0)
    check("the icon is on the web's volume under the same name", os.path.exists(os.path.join(folder, name2)))
    check("the statement holds the newer bytes",
          pathlib.Path(WEB, "receipts", "stripe-fees-acct-2026-10.html").read_text() == "<p>new</p>")
    link = AppLink(name="Master by Trade", url="https://masterbytrade.com", icon_file=name2,
                   icon_source="https://masterbytrade.com/icon.png")
    db.session.add(link)
    db.session.commit()
    link_id = link.id

from models import User  # noqa: E402
with application.app_context():
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    db.session.add(boss)
    db.session.commit()
    boss_id = boss.id
with client.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True
r = client.get(f"/admin/apps/icon/{link_id}")
check("the website serves the icon the night fetched", r.status_code == 200, r.status_code)

print("3. The heal door needs the key")
check("no key, no heal", client.post("/api/guidance/files/heal").status_code == 401)

print("4. heal repairs names that point at nothing")
with application.app_context():
    fetched = AppLink(name="Kuper", url="https://kuperplumbing.com", icon_file="b" * 32 + ".png",
                      icon_source="https://kuperplumbing.com/favicon.png")
    uploaded = AppLink(name="Signadoc", url="https://signadoc.example", icon_file="c" * 32 + ".png")
    biz = Business(name="Built by Bean LLC", slug="bbb")
    db.session.add_all([fetched, uploaded, biz])
    db.session.flush()
    box = ReceiptMailbox(business_id=biz.id, address="r@example.test")
    db.session.add(box)
    db.session.flush()
    kept = os.path.join(WEB, "receipts")
    os.makedirs(kept, exist_ok=True)
    pathlib.Path(kept, "d" * 32 + ".pdf").write_bytes(b"%PDF")
    lost_e = Expense(amount=10.66, description="Claude", category="software", date=date(2026, 10, 17),
                     business_id=biz.id, receipt_filename="e" * 32 + ".pdf", receipt_original_name="r.pdf")
    kept_e = Expense(amount=5.0, description="Domain", category="domain", date=date(2026, 10, 1),
                     business_id=biz.id, receipt_filename="d" * 32 + ".pdf", receipt_original_name="k.pdf")
    db.session.add_all([lost_e, kept_e])
    db.session.flush()
    db.session.add(Receipt(mailbox_id=box.id, message_key="m1", filename="e" * 32 + ".pdf", status="matched",
                           expense_id=lost_e.id))
    db.session.commit()
    ids = (fetched.id, uploaded.id, lost_e.id, kept_e.id)

    import pm.apps_routes as apps_routes
    apps_routes.app_icon_service.fetch = lambda url: (PNG, "png", url + "/favicon.png")
    summary = volume_files.heal()
    print("     " + summary)
    f, u, le, ke = (db.session.get(AppLink, ids[0]), db.session.get(AppLink, ids[1]),
                    db.session.get(Expense, ids[2]), db.session.get(Expense, ids[3]))
    check("a fetched icon that was gone is fetched again and on disk",
          f.icon_file and f.icon_file != "b" * 32 + ".png" and os.path.exists(os.path.join(WEB, "app_icons", f.icon_file)))
    check("an uploaded icon that was gone goes back to its letter", u.icon_file is None)
    check("the expense whose receipt was gone is back on Missing", le.receipt_filename is None)
    check("the receipt pointing at nothing is let go, to be read again", Receipt.query.count() == 0)
    check("an expense whose receipt is there is untouched", ke.receipt_filename == "d" * 32 + ".pdf")
    check("the night's first icon is untouched", db.session.get(AppLink, link_id).icon_file == name2)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
