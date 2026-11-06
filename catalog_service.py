"""The catalog: a private showcase of the apps Michael approves (issue #23).

Michael, 2026-11-06: "some people are going to want to see my work ... I need
a way where I can pick which products I want them to be able to see ... at a
glance, they can say, okay, this guy's built a lot of stuff. He's worked with a
lot of different services. Oh, he can get iOS and the Google Play Store ... the
overall catalog is only accessible upon me sending someone a link."

Three readings, all from what the board already knows about a tile:

- **Platforms**: a web address is a web app, an App Store bundle id an iPhone
  app, a Play package an Android app.
- **Services**: what its code uses (`AppLink.services`, filled nightly by the
  audit and through the door), plus Railway where the tile has a deploy. Each
  wears its playbook's mark where the Handbook has one.
- **What he can build**: the services read as plain capabilities a prospect
  would ask for ("Automated texting", "Online payments"), never as vendor
  jargon.

A link (`CatalogLink`) is the only way in: it expires, Michael can switch it
off, and it may narrow the catalog to some approved apps.
"""
import json
import secrets
from datetime import datetime, timedelta, timezone

LINK_DAYS = 30

# A vendor, as the capability a prospect would name. Only vendors whose
# purpose is plain; the rest show as a logo and say nothing more.
CAPABILITIES = {
    "Twilio": "Automated texting",
    "Stripe": "Online payments",
    "RevenueCat": "In-app subscriptions",
    "Resend": "Automated email",
    "Postmark": "Automated email",
    "SendGrid": "Automated email",
    "Mailgun": "Automated email",
    "OneSignal": "Push notifications",
    "Firebase": "Push notifications",
    "OpenAI API": "AI features",
    "Anthropic API": "AI features",
    "Deepgram": "Speech to text",
    "ElevenLabs": "AI voice",
    "Mapbox": "Maps",
    "PostHog": "Product analytics",
    "Sentry": "Error monitoring",
}

# Not shown as a service: where the code lives, and the store accounts, which
# show as platforms instead.
NOT_SHOWN = {"github", "apple developer program", "google play", "expo"}

PLATFORMS = [("web", "Web app"), ("ios", "iPhone app"), ("android", "Android app")]


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def platforms(tile):
    out = []
    if (tile.url or "").startswith(("http://", "https://")):
        out.append("web")
    if (tile.app_store_bundle_id or "").strip():
        out.append("ios")
    if (tile.play_package or "").strip():
        out.append("android")
    return out


def services(tile):
    """Vendor names, for showing: the code's, plus Railway where it deploys."""
    import vendor_discovery
    names = [n for n in tile.services if vendor_discovery.key(n) not in NOT_SHOWN]
    if tile.railway_url and "Railway" not in names:
        names.append("Railway")
    seen, out = set(), []
    for n in names:
        k = vendor_discovery.key(n)
        if k not in seen:
            seen.add(k)
            out.append(n)
    return sorted(out, key=str.lower)


def capabilities(tile):
    found = []
    for n in services(tile):
        cap = CAPABILITIES.get(n)
        if cap and cap not in found:
            found.append(cap)
    return found


def points(tile):
    return [l.strip(" -\t") for l in (tile.catalog_points or "").splitlines() if l.strip(" -\t")]


def approved(ids=None):
    """The approved apps, in Michael's order, narrowed to `ids` when given."""
    from models import AppLink
    rows = AppLink.query.filter(AppLink.catalog.is_(True)).all()
    if ids is not None:
        rows = [r for r in rows if r.id in set(ids)]
    return sorted(rows, key=lambda r: (r.catalog_position is None, r.catalog_position or 0, r.id))


def marks():
    """{vendor key: playbook} for every active playbook, by the words the
    night already reads vendors by."""
    import map_checks
    import vendor_discovery
    from models import Playbook
    out = {}
    for pb in Playbook.query.filter_by(is_active=True).all():
        out[vendor_discovery.key(pb.display_name)] = pb
        for w in map_checks.vendor_words(pb):
            out.setdefault(vendor_discovery.key(w), pb)
    return out


def playbook_for(name, book=None):
    import vendor_discovery
    book = book if book is not None else marks()
    k = vendor_discovery.key(name)
    return book.get(k) or book.get(vendor_discovery.key(name.replace(" API", "")))


def overview(apps):
    """What the whole set says at a glance: how many products, which
    platforms, what he can build, and every service, most used first."""
    plats, caps, counts = [], [], {}
    for app in apps:
        for p in platforms(app):
            if p not in plats:
                plats.append(p)
        for c in capabilities(app):
            if c not in caps:
                caps.append(c)
        for s in services(app):
            counts[s] = counts.get(s, 0) + 1
    order = [p for p, _ in PLATFORMS if p in plats]
    return {
        "count": len(apps),
        "platforms": order,
        "capabilities": caps,
        "services": sorted(counts, key=lambda s: (-counts[s], s.lower())),
    }


# ── Links ────────────────────────────────────────────────


def make_link(label, app_ids=None, days=LINK_DAYS, user=None):
    from models import CatalogLink, db
    link = CatalogLink(
        token=secrets.token_urlsafe(18), label=label.strip()[:120],
        app_ids_json=json.dumps(sorted(set(app_ids))) if app_ids else None,
        expires_at=now() + timedelta(days=days),
        created_by_id=getattr(user, "id", None))
    db.session.add(link)
    db.session.commit()
    return link


def live(link):
    return link is not None and link.revoked_at is None and link.expires_at > now()


def by_token(token):
    from models import CatalogLink
    if not token or len(token) > 48:
        return None
    link = CatalogLink.query.filter_by(token=token).first()
    return link if live(link) else None


def apps_for(link):
    """The approved apps a link shows. An app approved after the link was
    made shows on an all-apps link; one taken out of the catalog shows on
    none."""
    return approved(link.app_ids if link is not None else None)


def record_view(link, app=None):
    from models import CatalogView, db
    link.open_count = (link.open_count or 0) + 1
    link.last_opened_at = now()
    db.session.add(CatalogView(link_id=link.id, app_link_id=app.id if app else None, at=now()))
    db.session.commit()


# ── Tour pictures ────────────────────────────────────────

IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_BYTES = 8 * 1024 * 1024


def shots_folder():
    import os
    from flask import current_app
    return os.path.join(current_app.config["UPLOAD_FOLDER"], "catalog")


def sniff(data):
    """The picture's real type from its first bytes, or None. The upload's own
    content type is the browser's guess and is not trusted."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def store_image(data):
    """Keep a picture under catalog/ and return its name, or None when it is
    not a PNG, JPEG or WebP within the size limit."""
    import uuid
    import volume_files
    kind = sniff(data or b"")
    if kind is None or len(data) > MAX_BYTES:
        return None
    name = uuid.uuid4().hex + IMAGE_TYPES[kind]
    volume_files.write(shots_folder(), name, data)
    return name


def add_shot(app, data, caption=""):
    """Store one tour picture. Returns the CatalogShot, or None when it is not
    a picture this accepts."""
    from models import CatalogShot, db
    name = store_image(data)
    if name is None:
        return None
    last = max([s.position for s in app.catalog_shots] or [0])
    shot = CatalogShot(app_link_id=app.id, file=name, caption=(caption or "").strip()[:200],
                       position=last + 1)
    db.session.add(shot)
    db.session.commit()
    return shot


# ── What each app is built with ──────────────────────────


def set_services(tile, names):
    clean = sorted({n.strip()[:60] for n in names if isinstance(n, str) and n.strip()}, key=str.lower)
    tile.services_json = json.dumps(clean)
    tile.services_checked_at = now()


def record_repo_services(full_name, names):
    """The nightly audit's reading of one repo, onto every tile whose GitHub
    address is that repo. Commits. Returns how many tiles it wrote."""
    from models import AppLink, db
    repo = (full_name or "").lower().strip("/")
    n = 0
    for tile in AppLink.query.filter(AppLink.github_url.isnot(None)).all():
        if (tile.github_url or "").lower().rstrip("/").endswith("/" + repo):
            set_services(tile, names)
            n += 1
    if n:
        db.session.commit()
    return n
