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

# What a service does, as a prospect would name it, keyed by the service's
# playbook slug or by its name. Only services whose purpose is plain; the
# rest show as a logo and say nothing more.
CAPABILITIES = {
    "twilio": "Automated texting",
    "stripe": "Online payments",
    "venmo-zelle-cash-app": "Online payments",
    "revenuecat": "In-app subscriptions",
    "resend": "Automated email",
    "postmark": "Automated email",
    "gmail-smtp": "Automated email",
    "sendgrid": "Automated email",
    "mailgun": "Automated email",
    "onesignal": "Push notifications",
    "firebase": "Push notifications",
    "apns": "Push notifications",
    "claude": "AI features",
    "llm-apis": "AI features",
    "openai api": "AI features",
    "anthropic api": "AI features",
    "deepgram": "Speech to text",
    "elevenlabs": "AI voice",
    "mapbox": "Maps",
    "google-maps-platform-places-api-new": "Maps",
    "openstreetmap": "Maps",
    "posthog": "Product analytics",
    "sentry": "Error monitoring",
    "signadoc": "E-signatures",
    "quickbooks-online": "Accounting sync",
    "youtube-api": "Video",
    "google-business-profile": "Google reviews and listings",
    "tripleseat": "Event booking sync",
}

# The name the code reader or the stores use, as the playbook it is. The App
# Store's paid account is the Apple Developer Program; a store id on a tile is
# the listing itself.
ALIASES = {
    "apple developer program": "app-store",
    "app store": "app-store",
    "google play": "google-play",
    "anthropic api": "claude",
    "openai api": "llm-apis",
}

# Built by Bean's own accounts, not services a client's app is built with
# (Michael's bank, his card, his formation and his sales tax). Never shown.
INTERNAL_PLAYBOOKS = {"texas-sales-tax", "mercury", "legalzoom", "chase"}

PLATFORMS = [("web", "Web app"), ("ios", "iPhone app"), ("android", "Android app")]

# Every service as a prospect reads it (Michael, 2026-11-06: "organize by most
# valuable / recognizable to the layman's person ... with each a one liner
# explaining what that service is used for"). In this order: the names
# anybody knows first, the plumbing last. Keyed by playbook slug, or by name
# for a service the code reader knows with no playbook. A service not listed
# here shows after these, by name, with no line.
SERVICE_INFO = [
    ("app-store", "App Store", "Puts the app on iPhones and iPads"),
    ("google-play", "Google Play", "Puts the app on Android phones"),
    ("stripe", "Stripe", "Takes card payments and sends invoices"),
    ("venmo-zelle-cash-app", "Venmo, Zelle and Cash App", "Lets customers pay the way they already do"),
    ("google-maps-platform-places-api-new", "Google Maps", "Finds addresses, places and directions"),
    ("google-business-profile", "Google Business Profile", "Keeps the business on Google Search and Maps, reviews included"),
    ("youtube-api", "YouTube", "Brings a channel's videos onto the site"),
    ("spotify", "Spotify", "Brings the podcast onto the site"),
    ("quickbooks-online", "QuickBooks", "Keeps the books in step with the app"),
    ("google-workspace-the-client-s-business-mailbox", "Google Workspace", "Business email and calendars"),
    ("twilio", "Twilio", "Sends and receives text messages"),
    ("claude", "Claude", "AI that reads, writes and answers inside the app"),
    ("llm-apis", "AI models", "The AI behind smart features, like drafting and summing up"),
    ("anthropic api", "Claude", "AI that reads, writes and answers inside the app"),
    ("openai api", "OpenAI", "AI that reads, writes and answers inside the app"),
    ("squarespace", "Squarespace", "Website builder and domain names"),
    ("godaddy", "GoDaddy", "Domain names"),
    ("aws", "Amazon Web Services", "Amazon's cloud for storage and computing"),
    ("cloudflare", "Cloudflare", "Keeps the site fast and protected from attacks"),
    ("signadoc", "Signadoc", "Contracts signed online, from any phone"),
    ("firebase", "Firebase", "Sends notifications to phones"),
    ("apns", "Apple Push Notifications", "Sends notifications to iPhones"),
    ("onesignal", "OneSignal", "Sends notifications to phones"),
    ("revenuecat", "RevenueCat", "Runs subscriptions inside phone apps"),
    ("resend", "Resend", "Sends the app's emails"),
    ("postmark", "Postmark", "Sends the app's emails, fast and reliably"),
    ("gmail-smtp", "Gmail", "Sends email from the business's own address"),
    ("sendgrid", "SendGrid", "Sends the app's emails"),
    ("mailgun", "Mailgun", "Sends the app's emails"),
    ("tripleseat", "Tripleseat", "Event booking software, kept in sync"),
    ("mydoma-studio", "Mydoma Studio", "Interior design software, kept in sync"),
    ("openstreetmap", "OpenStreetMap", "Free maps"),
    ("mapbox", "Mapbox", "Custom maps"),
    ("esv-api", "ESV Bible", "Shows Bible passages"),
    ("open-states", "Open States", "Public data on state bills and lawmakers"),
    ("u-s-congress-public-data", "U.S. Congress data", "Public data on federal bills and lawmakers"),
    ("texas-legislature-online", "Texas Legislature Online", "Public data on Texas bills"),
    ("deepgram", "Deepgram", "Turns speech into text"),
    ("elevenlabs", "ElevenLabs", "Turns text into natural speech"),
    ("posthog", "PostHog", "Shows how people use the app"),
    ("sentry", "Sentry", "Catches errors before customers report them"),
    ("pwned-passwords", "Pwned Passwords", "Stops people using passwords already leaked"),
    ("railway", "Railway", "Hosts the app and its database"),
    ("postgres", "PostgreSQL", "The database"),
    ("github", "GitHub", "Where the code is kept, with every change saved"),
    ("capacitor", "Capacitor", "Turns a web app into phone apps"),
    ("expo", "Expo", "Builds the phone apps"),
    ("supabase", "Supabase", "Database and sign-in"),
    ("google cloud", "Google Cloud", "Google's cloud services"),
]
_INFO = {k: (i, name, line) for i, (k, name, line) in enumerate(SERVICE_INFO)}
# The same entries by the name they show, for a name that has already been
# turned into its plain form ("AI models").
_BY_NAME = {}
for _i, (_k, _name, _line) in enumerate(SERVICE_INFO):
    _BY_NAME.setdefault(" ".join("".join(ch if ch.isalnum() else " " for ch in _name.lower()).split()),
                        (_i, _name, _line))


# Logos shipped with the site (static/images/services), for the services whose
# playbook had none or the wrong one (Michael, 2026-11-06, of a strip with
# eleven letters where logos belonged: "if you ever fail me again on not
# showing logos"). Simple Icons marks in each brand's colour, each site's own
# icon where Simple Icons has none, and Signadoc's own mark from its code. The
# migration b2d4f6a8c013 puts the same files on the playbooks, so the Handbook
# shows them too; this is what covers a service with no playbook (Spotify).
LOGOS = {
    "youtube-api": "images/services/youtube.svg",
    "spotify": "images/services/spotify.svg",
    "quickbooks-online": "images/services/quickbooks.svg",
    "firebase": "images/services/firebase.svg",
    "apns": "images/services/apple.svg",
    "gmail-smtp": "images/services/gmail.svg",
    "llm-apis": "images/services/openai.svg",
    "openai api": "images/services/openai.svg",
    "mydoma-studio": "images/services/mydoma.png",
    "esv-api": "images/services/esv.png",
    "u-s-congress-public-data": "images/services/congress.png",
    "pwned-passwords": "images/services/pwned.png",
    "signadoc": "images/services/signadoc.svg",
}


def static_logo(name, book=None):
    """A logo shipped with the site for this service, or None."""
    import vendor_discovery
    show, pb = resolve(name, book)
    k0 = vendor_discovery.key(name)
    for k in ((pb.slug if pb is not None else None), ALIASES.get(k0), k0, k0.replace(" ", "-"),
              vendor_discovery.key(show), vendor_discovery.key(show).replace(" ", "-")):
        if k and k in LOGOS:
            return LOGOS[k]
    entry = _BY_NAME.get(vendor_discovery.key(show))
    if entry is not None:
        slug = SERVICE_INFO[entry[0]][0]
        return LOGOS.get(slug)
    return None


def missing_logos(names, book=None):
    """The services that would show a letter instead of a logo. The Catalog
    page names them, so a gap is seen on the board before a prospect sees it."""
    out = []
    for n in names:
        pb = resolve(n, book)[1]
        if static_logo(n, book) or (pb is not None and (pb.logo_path or pb.icon_file)):
            continue
        out.append(n)
    return out


def info(name, book=None):
    """(rank, name to show, one line) for a service. The rank puts the names a
    prospect knows first; an unknown service ranks last with no line."""
    import vendor_discovery
    show, pb = resolve(name, book)
    k0 = vendor_discovery.key(name)
    for k in ((pb.slug if pb is not None else None), ALIASES.get(k0), k0, k0.replace(" ", "-"),
              vendor_discovery.key(show), vendor_discovery.key(show).replace(" ", "-")):
        if k and k in _INFO:
            return _INFO[k]
    return _BY_NAME.get(vendor_discovery.key(show)) or _BY_NAME.get(k0) or (len(SERVICE_INFO), show, "")


def ordered(names, book=None):
    """Service names in the order a prospect should read them."""
    return sorted(names, key=lambda n: (info(n, book)[0], n.lower()))




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


def _lines(text):
    import re
    return [p.strip() for p in re.split(r"[,\n]", text or "") if p.strip()]


def resolve(name, book=None):
    """(the name to show, its playbook or None) for one service name: the
    playbook's own name without its bracketed note, where the Handbook has
    one, else the name as given."""
    import vendor_discovery
    book = book if book is not None else marks()
    k = vendor_discovery.key(name)
    pb = book.get("slug:" + ALIASES[k]) if k in ALIASES else None
    pb = pb or playbook_for(name, book)
    if pb is not None and pb.slug in _INFO:
        return _INFO[pb.slug][1], pb
    if pb is not None:
        return vendor_discovery.bare(pb.display_name) or name, pb
    for cand in (ALIASES.get(k), k, k.replace(" ", "-")):
        if cand and cand in _INFO:
            return _INFO[cand][1], None
    return name, None


def services(tile, book=None):
    """What one app is built with, as names to show: what its code uses, the
    stores it ships to, Railway and GitHub where it has them, and what
    Michael added by hand, less what he hid. The night rewrites only the
    code's reading, so an addition or a hide stays put."""
    import vendor_discovery
    book = book if book is not None else marks()
    raw = list(tile.services)
    if (tile.app_store_bundle_id or "").strip():
        raw.append("App Store")
    if (tile.play_package or "").strip():
        raw.append("Google Play")
    if tile.railway_url:
        raw.append("Railway")
    if tile.github_url:
        raw.append("GitHub")
    raw += _lines(getattr(tile, "catalog_services_extra", ""))
    hidden = {vendor_discovery.key(h) for h in _lines(getattr(tile, "catalog_services_hidden", ""))}
    seen, out = set(), []
    for n in raw:
        show, pb = resolve(n, book)
        if pb is not None and pb.slug in INTERNAL_PLAYBOOKS:
            continue
        if vendor_discovery.key(n) in hidden or vendor_discovery.key(show) in hidden:
            continue
        k = vendor_discovery.key(show)
        if k and k not in seen:
            seen.add(k)
            out.append(show)
    return ordered(out, book)


def capability(name, book=None):
    import vendor_discovery
    show, pb = resolve(name, book)
    if pb is not None and pb.slug in CAPABILITIES:
        return CAPABILITIES[pb.slug]
    return CAPABILITIES.get(vendor_discovery.key(name).replace(" ", "-")) or CAPABILITIES.get(vendor_discovery.key(name))


def capabilities(tile, book=None):
    book = book if book is not None else marks()
    found = []
    for n in services(tile, book):
        cap = capability(n, book)
        if cap and cap not in found:
            found.append(cap)
    return found


def site_url(tile):
    """The app's own web address for a prospect to visit, or None. Never for
    an app renamed for the catalog: its site carries the client's name."""
    if tile.renamed:
        return None
    url = tile.url or ""
    return url if url.startswith(("https://", "http://")) else None


def store_links(tile):
    """[(label, listing url)] for each store the store itself says lists the
    app now: the same answers My Apps shows (store_versions_service)."""
    summary = tile.stores
    if not summary:
        return []
    return [(label, row["url"]) for label, row in summary["rows"]
            if row.get("status") == "live" and row.get("url")]


def highlights(tile, book=None):
    """The short list of what is built into one app, for the front of the
    showcase: Michael's own (catalog_highlights), else what its services and
    stores say it does."""
    own = _lines(tile.catalog_highlights)
    if own:
        return own
    plats = platforms(tile)
    out = []
    if "ios" in plats and "android" in plats:
        out.append("iPhone and Android apps")
    elif "ios" in plats:
        out.append("iPhone app")
    elif "android" in plats:
        out.append("Android app")
    return out + capabilities(tile, book)


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
    """{vendor key: playbook} for every active playbook, by its name, its name
    without the bracketed note, its slug ("slug:<slug>") and the words the
    night already reads vendors by."""
    import map_checks
    import vendor_discovery
    from models import Playbook
    out = {}
    for pb in Playbook.query.filter_by(is_active=True).all():
        out["slug:" + pb.slug] = pb
        out.setdefault(vendor_discovery.key(pb.display_name), pb)
        out.setdefault(vendor_discovery.key(vendor_discovery.bare(pb.display_name)), pb)
        for w in map_checks.vendor_words(pb):
            out.setdefault(vendor_discovery.key(w), pb)
    return out


def playbook_for(name, book=None):
    import vendor_discovery
    book = book if book is not None else marks()
    k = vendor_discovery.key(name)
    return book.get(k) or book.get(vendor_discovery.key(name.replace(" API", "")))


def worked_with(book=None):
    """Every service Michael has a playbook for, as names to show, less his
    own business accounts: the services he has worked with across all his
    work, not only the apps in this catalog."""
    import vendor_discovery
    book = book if book is not None else marks()
    seen, out = set(), []
    for key_, pb in book.items():
        if not key_.startswith("slug:") or pb.slug in INTERNAL_PLAYBOOKS:
            continue
        show = _INFO[pb.slug][1] if pb.slug in _INFO else (vendor_discovery.bare(pb.display_name) or pb.display_name)
        if vendor_discovery.key(show) not in seen:
            seen.add(vendor_discovery.key(show))
            out.append(show)
    return out


def overview(apps, book=None):
    """What the whole set says at a glance: how many products, which
    platforms, what he can build, and every service he has worked with: the
    ones these apps use first (most used first), then the rest of the
    Handbook's."""
    import vendor_discovery
    book = book if book is not None else marks()
    plats, caps, counts = [], [], {}
    for app in apps:
        for p in platforms(app):
            if p not in plats:
                plats.append(p)
        for s in services(app, book):
            counts[s] = counts.get(s, 0) + 1
    seen, every = set(), []
    for s in list(counts) + worked_with(book):
        if vendor_discovery.key(s) not in seen:
            seen.add(vendor_discovery.key(s))
            every.append(s)
    every = ordered(every, book)
    for s in every:
        cap = capability(s, book)
        if cap and cap not in caps:
            caps.append(cap)
    order = [p for p, _ in PLATFORMS if p in plats]
    labels = {"web": "web", "ios": "iPhone", "android": "Android"}
    named = [labels[p] for p in order]
    where = (", ".join(named[:-1]) + " and " + named[-1]) if len(named) > 1 else (named[0] if named else "")
    return {
        "count": len(apps),
        "platforms": order,
        "where": where,
        "capabilities": caps,
        "services": every,
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
