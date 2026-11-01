"""What the two app stores say an app's live version is.

A phone app on My Apps ships twice - once to the App Store, once to Google
Play - and both store pages show one product, so the two version strings
have to agree. Nothing on the board said whether they did until this module:
it asks each store's PUBLIC page and keeps the answer on the tile.

No credentials, on purpose. Apple's lookup endpoint and the Play listing
page are what any phone sees, so this reads the same truth the customer
reads and never holds a store key. The cost is that an app in review is
simply "not listed" until the store publishes it - which is exactly the
state the tile should show.

    App Store: https://itunes.apple.com/lookup?bundleId=<bundle id>
               (JSON; resultCount 0 while the app is not live)
    Google Play: https://play.google.com/store/apps/details?id=<package>
               (HTML; 404 while not live; the version sits in the page's
               data blob as ]]],"1.2.3",null, right after the icon URL, and
               the "Updated on" date is in the visible markup)

Each lookup is one request with a short timeout, and a failure keeps the
previous answer rather than blanking it: a store that is slow for a minute
is not an app that vanished.
"""
import json
import re
from datetime import datetime, timedelta, timezone

import requests

APP_STORE_LOOKUP = "https://itunes.apple.com/lookup"
PLAY_LISTING = "https://play.google.com/store/apps/details"
TIMEOUT = 6
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 BuiltByBean-PM/1.0")
# How long a store answer is trusted before the board asks again.
FRESH_FOR = timedelta(hours=6)

_PLAY_VERSION_RE = re.compile(r'\]\]\],"(\d+(?:\.\d+){1,3})",null,')
_PLAY_UPDATED_RE = re.compile(r'Updated on</div><div class="[^"]*">([^<]{6,40})</div>')
_PLAY_TITLE_RE = re.compile(r"<title>([^<]*?)(?: - Apps on Google Play)?</title>")


def _get(url, params):
    return requests.get(url, params=params, timeout=TIMEOUT,
                        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})


def lookup_app_store(bundle_id, country="us"):
    """One store's answer: {"status": "live", "version", "name", "url", "released"}
    when the app is on the store, {"status": "not_listed"} when it is not
    (in review, pulled, or the id is wrong), {"status": "error"} when Apple
    did not answer."""
    try:
        resp = _get(APP_STORE_LOOKUP, {"bundleId": bundle_id, "country": country})
        resp.raise_for_status()
        results = (resp.json() or {}).get("results") or []
    except (requests.RequestException, ValueError):
        return {"status": "error"}
    if not results:
        return {"status": "not_listed"}
    row = results[0]
    return {"status": "live", "version": str(row.get("version") or ""),
            "name": row.get("trackName"), "url": row.get("trackViewUrl"),
            "released": row.get("currentVersionReleaseDate")}


def lookup_play(package):
    """Google Play's answer, read off the public listing page."""
    try:
        resp = _get(PLAY_LISTING, {"id": package, "hl": "en", "gl": "US"})
    except requests.RequestException:
        return {"status": "error"}
    if resp.status_code == 404:
        return {"status": "not_listed"}
    if resp.status_code != 200:
        return {"status": "error"}
    html = resp.text
    m = _PLAY_VERSION_RE.search(html)
    if not m:
        # The page exists but the blob moved: say so rather than guess.
        return {"status": "error"}
    updated = _PLAY_UPDATED_RE.search(html)
    title = _PLAY_TITLE_RE.search(html)
    return {"status": "live", "version": m.group(1),
            "name": title.group(1).strip() if title else None,
            "url": f"{PLAY_LISTING}?id={package}",
            "released": updated.group(1).strip() if updated else None}


def refresh(link, now=None):
    """Ask both stores for this tile and keep what they said. A store that
    errored keeps its last answer. Returns the stored dict."""
    now = now or datetime.now(timezone.utc)
    previous = info(link)
    fresh = {}
    if link.app_store_bundle_id:
        got = lookup_app_store(link.app_store_bundle_id)
        fresh["app_store"] = previous.get("app_store") if got["status"] == "error" and previous.get("app_store") else got
    if link.play_package:
        got = lookup_play(link.play_package)
        fresh["play"] = previous.get("play") if got["status"] == "error" and previous.get("play") else got
    link.store_versions = json.dumps(fresh)
    link.store_checked_at = now.replace(tzinfo=None)
    return fresh


def info(link):
    """The stored answer as a dict, {} when nothing has been asked yet."""
    try:
        data = json.loads(link.store_versions or "{}")
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def is_stale(link, now=None):
    if not (link.app_store_bundle_id or link.play_package):
        return False
    if link.store_checked_at is None:
        return True
    now = now or datetime.now(timezone.utc)
    return (now.replace(tzinfo=None) - link.store_checked_at) > FRESH_FOR


def summary(link):
    """What the tile shows: one row per store the app is registered with,
    and a verdict on whether the live versions agree.

    verdict: "match" when every live store shows the same version,
             "differ" when two live stores disagree,
             "waiting" when a registered store does not list the app yet,
             None when the app has no store ids.
    """
    data = info(link)
    rows = []
    if link.app_store_bundle_id:
        rows.append(("App Store", data.get("app_store") or {"status": "unknown"}))
    if link.play_package:
        rows.append(("Google Play", data.get("play") or {"status": "unknown"}))
    if not rows:
        return None
    live = [r[1].get("version") for r in rows if r[1].get("status") == "live"]
    if len(live) == len(rows) and live:
        verdict = "match" if len(set(live)) == 1 else "differ"
    else:
        verdict = "waiting"
    return {"rows": rows, "verdict": verdict, "checked_at": link.store_checked_at}
