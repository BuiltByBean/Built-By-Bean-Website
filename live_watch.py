"""Watch what is live: every site, its certificate, its domain, its deploy.

docs/automation_gaps.md item 9. Until 2026-11-04 nothing checked that a tile's
URL still answered, that its certificate was current, or that a deploy had
worked; Cloudflare's registrar answer (expiry, auto-renew) was fetched for
every domain and thrown away after dating one charge. A client found an
outage first.

Nightly, with no model and no paid call:

  - each tile's URL and each map surface's URL is fetched once: the status,
    where it ended up, and the certificate's notAfter. A failure counts the
    nights in a row it has failed and remembers since when (SiteCheck);
  - each domain those sites live on gets its expiry and auto-renew, from
    Cloudflare's registrar where it is held there, else from public RDAP
    (which says the date and never the setting) (DomainWatch);
  - the deploys are railway_watch's.

`attention_rows` turns all of it into Needs attention rows, reading only the
database, because the sidebar badge asks on every page:

  - a site down two nights running (one bad night is a blip);
  - a certificate with under 14 days left;
  - a domain with under 30 days left that does not renew itself, or whose
    registrar will not say;
  - a production deploy that FAILED or CRASHED;
  - a deployed commit more than a day behind its branch;
  - phone app stores that have shown different versions for over a day;
  - services live on Railway that are not on My Apps (one row for all).
"""
import socket
import ssl
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import requests

from railway_watch import host_of

TIMEOUT = 15
USER_AGENT = "BuiltByBean-Board/1.0 (+https://builtbybeans.com; uptime check)"
CERT_WARN_DAYS = 14
DOMAIN_WARN_DAYS = 30
DOWN_NIGHTS = 2
STORE_DIFFER_GRACE = timedelta(days=1)
# Hosts on somebody else's domain: their expiry is not ours to watch.
PLATFORM_SUFFIXES = (".railway.app", ".up.railway.app", ".vercel.app", ".netlify.app",
                     ".github.io", ".pages.dev", ".workers.dev", ".herokuapp.com",
                     ".onrender.com", ".fly.dev", ".web.app", ".firebaseapp.com")
# Second-level labels under a country code that are not anybody's name.
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu"}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def registrable(host):
    """example.com from app.example.com; None for a platform's own host."""
    host = (host or "").lower().strip(".")
    if not host or "." not in host or host.endswith(PLATFORM_SUFFIXES) or host[0].isdigit():
        return None
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


# ── One site ─────────────────────────────────────────────


def cert_expiry(host, port=443, timeout=TIMEOUT):
    """The certificate's notAfter as a date, or None when it cannot be read."""
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert()
    after = cert.get("notAfter") if cert else None
    if not after:
        return None
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(after), timezone.utc).date()


def probe(url, get=None, cert=None):
    """{status_code, ok, final_url, error, cert_expires_on} for one URL.

    Up is any answer under 400, and a 401 or 403 too: a login wall or a bot
    challenge is a server that answered. A 404 at the address a tile points
    at, a 5xx, a timeout or a bad certificate is down.
    """
    get = get or (lambda u: requests.get(u, timeout=TIMEOUT, allow_redirects=True, stream=True,
                                         headers={"User-Agent": USER_AGENT}))
    cert = cert or cert_expiry
    out = {"status_code": None, "ok": False, "final_url": None, "error": None,
           "cert_expires_on": None}
    try:
        resp = get(url)
        out["status_code"] = resp.status_code
        out["final_url"] = (getattr(resp, "url", None) or url)[:500]
        out["ok"] = resp.status_code < 400 or resp.status_code in (401, 403)
        if not out["ok"]:
            out["error"] = f"HTTP {resp.status_code}"
        close = getattr(resp, "close", None)
        if close:
            close()
    except requests.exceptions.SSLError as err:
        out["error"] = f"certificate: {str(err)[:200]}"
    except requests.RequestException as err:
        out["error"] = f"{type(err).__name__}: {str(err)[:200]}"
    final = urlparse(out["final_url"] or url)
    if final.scheme == "https" and final.hostname:
        try:
            out["cert_expires_on"] = cert(final.hostname)
        except Exception:  # noqa: BLE001 - an unreadable certificate is not a crash
            pass
    return out


def record(url, got, now=None):
    """Write one probe's answer onto its SiteCheck row."""
    from models import db, SiteCheck
    now = now or _now()
    row = SiteCheck.query.filter_by(url=url[:500]).first()
    if row is None:
        row = SiteCheck(url=url[:500])
        db.session.add(row)
    row.host = host_of(url)[:255]
    row.status_code = got["status_code"]
    row.final_url = got["final_url"]
    row.error = (got["error"] or None) and got["error"][:300]
    row.cert_expires_on = got["cert_expires_on"] or row.cert_expires_on
    row.checked_at = now
    if got["ok"]:
        row.ok, row.fail_nights, row.down_since = True, 0, None
    else:
        row.ok = False
        row.fail_nights = (row.fail_nights or 0) + 1
        row.down_since = row.down_since or now
    return row


def urls_to_watch():
    """Every address a tile or a map surface points at, once each."""
    from models import AppLink, BusinessNode
    seen, out = set(), []
    for url in ([a.url for a in AppLink.query.order_by(AppLink.id).all()]
                + [n.url for n in BusinessNode.query.filter_by(kind="surface").all()]):
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        key = url.rstrip("/").lower()
        if key not in seen:
            seen.add(key)
            out.append(url)
    return out


def check_sites(get=None, cert=None):
    from models import db, SiteCheck
    up = down = 0
    watched = urls_to_watch()
    for url in watched:
        row = record(url, probe(url, get, cert))
        db.session.commit()
        up, down = (up + 1, down) if row.ok else (up, down + 1)
    # An address nothing points at any more is not checked again, and its last
    # answer goes with it: a deleted tile's "down two nights" row would
    # otherwise sit on Needs attention for good (2026-11-05).
    keep = {u[:500] for u in watched}
    for stale in SiteCheck.query.all():
        if stale.url not in keep:
            db.session.delete(stale)
    db.session.commit()
    return up, down


# ── Domains ──────────────────────────────────────────────


def cloudflare_registrar(get=None):
    """{domain: (expires_on, auto_renew)} from every Cloudflare provider whose
    token can read the registrar; {} when none can."""
    from models import ServiceProvider
    import service_costs_service
    get = get or (lambda url, headers: requests.get(url, headers=headers, timeout=30).json())
    out = {}
    for p in ServiceProvider.query.filter_by(name="cloudflare", is_active=True).all():
        creds = service_costs_service._get_credentials(p)
        token, account = creds.get("api_token"), creds.get("account_id")
        if not token or not account:
            continue
        try:
            data = get(f"https://api.cloudflare.com/client/v4/accounts/{account}/registrar/domains",
                       {"Authorization": f"Bearer {token}"})
        except Exception:  # noqa: BLE001 - registrar is a separate permission
            continue
        if not data.get("success"):
            continue
        for row in data.get("result") or []:
            name, expires = (row.get("name") or "").lower(), row.get("expires_at")
            if not name:
                continue
            try:
                when = date.fromisoformat(str(expires)[:10]) if expires else None
            except ValueError:
                when = None
            out[name] = (when, bool(row.get("auto_renew")))
    return out


def rdap_expiry(domain, get=None):
    """The expiry date public RDAP gives, or None."""
    get = get or (lambda url: requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT,
                                                                          "Accept": "application/rdap+json"}))
    resp = get(f"https://rdap.org/domain/{domain}")
    if resp.status_code != 200:
        raise ValueError(f"RDAP answered {resp.status_code}")
    for event in (resp.json() or {}).get("events") or []:
        if event.get("eventAction") == "expiration" and event.get("eventDate"):
            return date.fromisoformat(event["eventDate"][:10])
    return None


def check_domains(cf=None, rdap=None):
    from models import db, DomainWatch, SiteCheck
    from urllib.parse import urlparse as _p
    registrar = cloudflare_registrar(cf)
    hosts = {host_of(u) for u in urls_to_watch()}
    hosts |= {(_p(r.final_url).hostname or "").lower() for r in SiteCheck.query.all() if r.final_url}
    domains = sorted({d for d in (registrable(h) for h in hosts) if d})
    now = _now()
    for domain in domains:
        row = DomainWatch.query.filter_by(domain=domain).first()
        if row is None:
            row = DomainWatch(domain=domain)
            db.session.add(row)
        row.checked_at = now
        if domain in registrar:
            row.expires_on, row.auto_renew = registrar[domain]
            row.registrar, row.error = "cloudflare", None
            continue
        try:
            row.expires_on = rdap_expiry(domain, rdap) or row.expires_on
            row.registrar, row.auto_renew, row.error = "elsewhere", None, None
        except Exception as err:  # noqa: BLE001 - some registries have no RDAP
            row.error = str(err)[:300]
        time.sleep(0.2)  # rdap.org is a shared public service
    db.session.commit()
    return len(domains)


# ── Needs attention ──────────────────────────────────────


_CACHE = {"at": 0.0, "rows": None}
CACHE_SECONDS = 300


def attention_rows(force=False, today=None, now=None):
    """[{key, pill, title, detail, href, press}] for Needs attention. Reads the
    database only. Cached five minutes for the sidebar badge."""
    from models import db
    if not force and _CACHE["rows"] is not None and time.monotonic() - _CACHE["at"] < CACHE_SECONDS:
        return _CACHE["rows"]
    try:
        rows = _rows(today or date.today(), now or _now())
    except Exception:  # noqa: BLE001 - a table that is not there yet never takes the board down
        db.session.rollback()
        rows = []
    _CACHE.update(at=time.monotonic(), rows=rows)
    return rows


def _url(endpoint, path):
    """url_for where there is a request, the plain path where there is not
    (the nightly job, a test): a row must never vanish for want of one."""
    from flask import url_for, has_request_context
    if has_request_context():
        try:
            return url_for(endpoint)
        except Exception:  # noqa: BLE001
            pass
    return path


def _rows(today, now):
    from models import AppLink, DomainWatch, SiteCheck
    import railway_watch
    out = []
    for s in SiteCheck.query.filter(SiteCheck.fail_nights >= DOWN_NIGHTS).order_by(SiteCheck.url).all():
        out.append({"key": f"down:{s.id}", "pill": "Down", "tone": "red",
                    "title": s.host or s.url,
                    "detail": (f"Not answering since {s.down_since:%b} {s.down_since.day}"
                               if s.down_since else f"Not answering for {s.fail_nights} nights")
                              + f": {s.error or 'no answer'}",
                    "href": s.url, "press": "Open it"})
    soon = today + timedelta(days=CERT_WARN_DAYS)
    for s in SiteCheck.query.filter(SiteCheck.cert_expires_on.isnot(None),
                                    SiteCheck.cert_expires_on <= soon).order_by(SiteCheck.url).all():
        days = (s.cert_expires_on - today).days
        out.append({"key": f"cert:{s.id}", "pill": "Certificate", "tone": "amber",
                    "title": s.host or s.url,
                    "detail": (f"Certificate ran out {-days} days ago" if days < 0 else
                               f"Certificate runs out in {days} day{'s' if days != 1 else ''}"),
                    "href": s.url, "press": "Open it"})
    horizon = today + timedelta(days=DOMAIN_WARN_DAYS)
    for d in DomainWatch.query.filter(DomainWatch.expires_on.isnot(None),
                                      DomainWatch.expires_on <= horizon).order_by(DomainWatch.domain).all():
        if d.auto_renew:
            continue
        days = (d.expires_on - today).days
        held = "auto-renew is off" if d.registrar == "cloudflare" else "held outside Cloudflare"
        out.append({"key": f"domain:{d.id}", "pill": "Domain", "tone": "amber",
                    "title": d.domain,
                    "detail": (f"Expired {-days} days ago" if days < 0 else
                               f"Expires in {days} day{'s' if days != 1 else ''}, {held}"),
                    "href": (f"https://dash.cloudflare.com/" if d.registrar == "cloudflare"
                             else f"https://lookup.icann.org/en/lookup?name={d.domain}"),
                    "press": "Renew it"})
    for p in railway_watch.deploy_problems(now=now):
        s = p["service"]
        if p["kind"] == "broken":
            detail = f"Latest deploy {s.deploy_status.lower()}"
            pill = "Deploy"
        else:
            detail = (f"Running {s.deploy_commit[:7]}, {s.deploy_branch} is at "
                      f"{s.branch_head[:7]} since {s.branch_head_at:%b} {s.branch_head_at.day}")
            pill = "Behind"
        out.append({"key": f"deploy:{s.id}", "pill": pill, "tone": "red" if p["kind"] == "broken" else "amber",
                    "title": f"{s.project_name} / {s.service_name}", "detail": detail,
                    "href": s.dashboard_url, "press": "Open Railway"})
    for a in AppLink.query.filter(AppLink.store_differ_since.isnot(None)).order_by(AppLink.name).all():
        if now - a.store_differ_since <= STORE_DIFFER_GRACE:
            continue
        import store_versions_service
        rows = (store_versions_service.summary(a) or {}).get("rows") or []
        said = ", ".join(f"{label} {row.get('version')}" for label, row in rows if row.get("version"))
        out.append({"key": f"stores:{a.id}", "pill": "Stores", "tone": "amber",
                    "title": a.name, "detail": f"Versions differ: {said}",
                    "href": _url("apps.index", "/admin/apps/"), "press": "See the tile"})
    loose = railway_watch.unlisted()
    if loose:
        names = ", ".join(f"{s.project_name}" + (f" / {s.service_name}" if s.service_name not in ("web", s.project_name) else "")
                          for s in loose[:4])
        more = f" and {len(loose) - 4} more" if len(loose) > 4 else ""
        out.append({"key": "unlisted", "pill": "My Apps", "tone": "brand",
                    "title": f"{len(loose)} live on Railway, not on My Apps",
                    "detail": names + more,
                    "href": _url("apps.railway_unlisted", "/admin/apps/railway"), "press": "Sort them"})
    return out
