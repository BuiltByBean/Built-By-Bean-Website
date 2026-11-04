"""Keep the My Apps tiles' words and pictures current, nightly. No model.

docs/automation_gaps.md, smaller ones. A tile's description was typed and
its icon fetched once on save, so a tile made in a hurry stayed blank and an
icon stayed whatever the site wore that day.

  - An EMPTY description is filled from the repo's own description on
    GitHub, else the site's <meta name="description"> (or og:description).
    A typed one is never touched.
  - A FETCHED icon is fetched again once it is a month old. An uploaded one
    (icon_file with no icon_source) was chosen, not found, and is never
    replaced. A tile with no icon is asked again monthly too, because a site
    that offered none in March may offer one now.
"""
import html
import re
from datetime import datetime, timedelta, timezone

import requests

ICON_EVERY = timedelta(days=30)
MAX_DESCRIPTION = 300
_META = re.compile(r"""<meta\s+[^>]*(?:name|property)\s*=\s*["'](?:description|og:description)["'][^>]*>""", re.I)
_CONTENT = re.compile(r"""content\s*=\s*(["'])(.*?)\1""", re.I | re.S)


def meta_description(page):
    """The page's own one-line description, or None."""
    for tag in _META.findall(page or ""):
        m = _CONTENT.search(tag)
        if m:
            text = " ".join(html.unescape(m.group(2)).split())
            if text:
                return text[:MAX_DESCRIPTION]
    return None


def site_description(url, get=None):
    import app_icon_service
    get = get or (lambda u: requests.get(u, timeout=10, headers={"User-Agent": app_icon_service.USER_AGENT}))
    resp = get(url)
    if resp.status_code >= 400:
        return None
    return meta_description(resp.text[:200_000])


def repo_description(link, get=None):
    import store_ids_service
    import sweep_repos
    full = store_ids_service.repo_of(link)
    if not full:
        return None
    got = (get or sweep_repos._get)(f"/repos/{full}")
    text = " ".join((got.get("description") or "").split())
    return text[:MAX_DESCRIPTION] or None


def wants_icon(link, now=None):
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if link.icon_file and link.icon_source is None:
        return False  # uploaded by hand
    if not (link.url or "").startswith(("http://", "https://")):
        return False
    fetched = link.icon_fetched_at
    if fetched is not None and fetched.tzinfo is not None:
        fetched = fetched.astimezone(timezone.utc).replace(tzinfo=None)
    return fetched is None or now - fetched > ICON_EVERY


def run(site=None, repo=None, refresh_icon=None):
    from models import db, AppLink
    if refresh_icon is None:
        from pm.apps_routes import _refresh_icon as refresh_icon
    described = iconed = 0
    for link in AppLink.query.order_by(AppLink.id).all():
        if not (link.description or "").strip():
            text = None
            try:
                text = repo_description(link, repo)
            except Exception as err:  # noqa: BLE001
                print(f"tiles: {link.name} repo: {str(err)[:120]}", flush=True)
            if not text and (link.url or "").startswith(("http://", "https://")):
                try:
                    text = site_description(link.url, site)
                except Exception as err:  # noqa: BLE001
                    print(f"tiles: {link.name} site: {str(err)[:120]}", flush=True)
            if text:
                link.description = text
                described += 1
        if wants_icon(link):
            try:
                iconed += 1 if refresh_icon(link) else 0
            except Exception as err:  # noqa: BLE001
                print(f"tiles: {link.name} icon: {str(err)[:120]}", flush=True)
        db.session.commit()
    return f"{described} descriptions filled, {iconed} icons fetched"
