"""Every file the board keeps lands on the web service's volume, whoever writes it.

Railway attaches a volume to ONE service. The web service has /data; the
nightly cost-sync job is a second service with no volume at all, and until
2026-11-05 it wrote what it made (app icons it re-fetched, receipts read from
the mailboxes, Stripe fee statements) onto its own throwaway disk while the
database recorded the new names. The website then answered 404 for every one:
ten My Apps icons blank the morning after tile upkeep first ran.

So a write goes through `write`. Where the volume is mounted it writes the file
there. Anywhere else on Railway it leaves the bytes in `VolumeInbox`, because
the database is the one thing both services share, and the web service's timer
(`start_background`) moves them onto the volume under the same name within a
minute. The same timer runs `heal_here` at boot and daily: every stored name
the board points at is checked against the disk, and what points at nothing is
repaired (pm/files_door_routes.py, also behind the door for sessions).
"""
import logging
import os
import threading
import time

log = logging.getLogger(__name__)

DRAIN_EVERY_SECONDS = 60
HEAL_EVERY_SECONDS = 24 * 3600
_timer = {"started": False, "app": None}


def volume_here():
    """True where this process can see the volume: off Railway (a laptop, the
    tests), or a Railway service with a volume mounted, which Railway says by
    setting RAILWAY_VOLUME_MOUNT_PATH."""
    if not os.environ.get("RAILWAY_ENVIRONMENT"):
        return True
    return bool(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"))


def write(folder, name, data):
    """Store `data` as `name` in `folder` (an absolute path under UPLOAD_FOLDER,
    as the callers already build it). Returns `name`."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    if volume_here():
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "wb") as fh:
            fh.write(data)
        return name
    from models import VolumeInbox, db
    sub = os.path.basename(os.path.normpath(folder))
    row = VolumeInbox.query.filter_by(folder=sub, name=name).first()
    if row is None:
        db.session.add(VolumeInbox(folder=sub, name=name, data=data))
    else:
        row.data = data  # the Stripe statement keeps its name and is rewritten
    db.session.flush()
    return name


def drain():
    """Move every waiting file onto the volume. Writing the same bytes under
    the same name twice is harmless, so two workers draining at once only
    repeat each other. Returns how many were moved."""
    from flask import current_app
    from models import VolumeInbox, db
    moved = 0
    for row in VolumeInbox.query.order_by(VolumeInbox.id).limit(200).all():
        folder = os.path.join(current_app.config["UPLOAD_FOLDER"], row.folder)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, row.name), "wb") as fh:
            fh.write(row.data)
        db.session.delete(row)
        moved += 1
    db.session.commit()
    return moved


def heal():
    """The night's step. Where the volume is here it repairs dead names
    itself; on cost-sync it can only say how many files wait for the web."""
    if volume_here():
        from pm.files_door_routes import heal_here
        return heal_here()
    from models import VolumeInbox
    return f"{VolumeInbox.query.count():,} files waiting for the web service to put on the volume"


def start_background(app):
    """On the service that has the volume only: drain the inbox every minute,
    and heal at boot and then daily. Guarded per process, like the mail timer,
    because app.py builds two apps per worker."""
    if not os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or os.environ.get("VOLUME_TIMER_DISABLED") == "1":
        return False
    _timer["app"] = app
    if _timer["started"]:
        return False
    _timer["started"] = True

    def loop():
        time.sleep(45)  # not on the boot itself: the health check comes first
        last_heal = 0.0
        while True:
            app = _timer["app"]
            with app.app_context():
                from models import db
                try:
                    n = drain()
                    if n:
                        log.warning("volume: put %s waiting files on the volume", n)
                    if time.time() - last_heal > HEAL_EVERY_SECONDS:
                        log.warning("volume: %s", heal())
                        last_heal = time.time()
                except Exception as err:  # noqa: BLE001 - a dead timer is files nobody can open
                    db.session.rollback()
                    log.warning("volume: pass failed: %s", err)
                finally:
                    db.session.remove()
            time.sleep(DRAIN_EVERY_SECONDS)

    threading.Thread(target=loop, daemon=True, name="volume-timer").start()
    return True
