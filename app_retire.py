"""Taking an app off the board: the one way, for the door and for the night.

`retire_app` (pm/guidance_routes.py) is a session saying something was torn
down. The nightly Railway read (railway_watch.run) is the board seeing it for
itself: a Railway project that was there last night and is gone tonight takes
its tiles with it (Michael, 2026-11-05: "nothing should be manual"). Both call
`retire`, so a tile leaves the same way whoever noticed.

What goes: every matching tile, its icon file and its nightly site checks.
What is switched off, not deleted: the hosting mappings for that Railway
project, so the months it was billed for keep their split. What is never
touched: a project on the board, which holds money and time.

Flushes, never commits: the caller owns the transaction.
"""
import os
import re
from urllib.parse import urlparse

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _host(url):
    url = (url or "").strip()
    if "//" not in url:
        url = "https://" + url
    return (urlparse(url).hostname or "").lower()


def record(link):
    """A removed tile whole, which is what it takes to register it again."""
    return {"id": link.id, "name": link.name, "url": link.url, "github_url": link.github_url,
            "railway_url": link.railway_url, "description": link.description,
            "project": link.project.name if link.project else None,
            "board_group": link.board_group, "app_store_bundle_id": link.app_store_bundle_id,
            "play_package": link.play_package}


def retire(url=None, name=None, railway_project=None):
    """Take off the board whatever matches any of: `url` (the tile's host),
    `name` (exactly, any case) or `railway_project` (the Railway project id).

    Returns {"removed_apps": [...], "mappings_switched_off": [...],
    "railway_rows_removed": [...]}, all empty when nothing matched."""
    from models import db, AppLink, RailwayService, ServiceMapping, SiteCheck
    import volume_files
    rail = (railway_project or "").strip().lower()

    tiles = {}
    if url:
        host = _host(url)
        for row in AppLink.query.filter(AppLink.url.ilike(f"%{host}%")).all():
            if row.host.lower() == host:
                tiles[row.id] = row
    if name:
        for row in AppLink.query.filter(db.func.lower(AppLink.name) == name.lower()).all():
            tiles[row.id] = row
    if rail:
        for row in AppLink.query.filter(AppLink.railway_url.ilike(f"%{rail}%")).all():
            tiles[row.id] = row
    mappings = (ServiceMapping.query.filter(ServiceMapping.resource_identifier.in_(
        [f"railway:{rail}", rail])).all() if rail else [])
    services = RailwayService.query.filter_by(project_ref=rail).all() if rail else []

    removed = []
    for link in sorted(tiles.values(), key=lambda r: r.id):
        removed.append(record(link))
        prefix = (link.url or "").rstrip("/")
        if prefix:
            for check in SiteCheck.query.filter(SiteCheck.url.ilike(prefix + "%")).all():
                db.session.delete(check)
        # Only where the volume is: the nightly service has none, and its
        # disk never held the file (volume_files).
        if link.icon_file and volume_files.volume_here():
            from flask import current_app
            path = os.path.join(current_app.config["UPLOAD_FOLDER"], "app_icons", link.icon_file)
            try:
                os.remove(path)
            except OSError:
                pass
        db.session.delete(link)
    off = []
    for m in mappings:
        if m.is_active:
            m.is_active = False
            off.append({"id": m.id, "label": m.resource_label})
    gone = [f"{s.project_name}/{s.service_name} ({s.environment})" for s in services]
    for s in services:
        db.session.delete(s)
    db.session.flush()
    return {"removed_apps": removed, "mappings_switched_off": off, "railway_rows_removed": gone}
