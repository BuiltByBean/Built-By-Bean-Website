"""Fetch an app's own icon, so a tile can wear the thing the app already has.

Every app worth putting on the board already ships a picture of itself: a PWA
manifest icon, an apple-touch-icon, a favicon. Picking one off a stock list
would be choosing a worse image than the one sitting at the other end of the
URL, so this goes and gets it.

Preference order is by usable size, not by tag. A manifest's 512px icon beats
a 180px apple-touch-icon beats a 32px favicon, and an SVG beats all of them
because it is the only one that stays sharp on a retina tile. The last resort
is /favicon.ico, which nearly everything has and nearly nothing declares.

Everything here is best effort. A site that is down, slow, or offers nothing
returns None and the tile falls back to initials — a board that renders
without pictures is fine, a board that hangs waiting for one is not.
"""

import base64
import io
import os
import re
import uuid
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse

import requests

USER_AGENT = "BuiltByBean-PM/1.0 (icon fetch)"
TIMEOUT = 8
MAX_BYTES = 2 * 1024 * 1024

# What we will store, and what each is called on disk.
TYPES = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
    "image/svg+xml": "svg", "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico",
    "image/gif": "gif",
}


class _Links(HTMLParser):
    """Collect <link> tags and stop at </head>, which is all we need."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.done = False

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if tag == "link":
            self.links.append({k.lower(): (v or "") for k, v in attrs})
        elif tag == "body":
            self.done = True

    def handle_endtag(self, tag):
        if tag == "head":
            self.done = True


def _largest(sizes):
    """The biggest edge in a sizes attribute like "192x192 512x512"."""
    best = 0
    for chunk in (sizes or "").lower().split():
        m = re.match(r"(\d+)x(\d+)$", chunk)
        if m:
            best = max(best, int(m.group(1)), int(m.group(2)))
    return best


def _get(url, **kw):
    return requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT},
                        allow_redirects=True, **kw)


def _candidates(page_url, html):
    """Every icon the page declares, scored so the best sorts first."""
    parser = _Links()
    try:
        parser.feed(html)
    except Exception:
        pass  # malformed markup still yields whatever was parsed before it

    found = []
    for link in parser.links:
        rels = link.get("rel", "").lower().split()
        href = link.get("href", "").strip()
        if not href:
            continue
        if "manifest" in rels:
            found += _from_manifest(urljoin(page_url, href))
        elif "apple-touch-icon" in rels or "apple-touch-icon-precomposed" in rels:
            # Apple's is a real square logo, never a 16px glyph, so it beats a
            # favicon of the same declared size.
            found.append((_largest(link.get("sizes")) or 180, urljoin(page_url, href)))
        elif "icon" in rels or "shortcut" in rels:
            size = _largest(link.get("sizes"))
            if href.lower().endswith(".svg") or link.get("type") == "image/svg+xml":
                size = max(size, 1024)  # scales to any tile
            found.append((size or 32, urljoin(page_url, href)))
    return found


def _from_manifest(manifest_url):
    try:
        resp = _get(manifest_url)
        if not resp.ok:
            return []
        data = resp.json()
    except Exception:
        return []
    out = []
    for icon in (data.get("icons") or []):
        src = (icon.get("src") or "").strip()
        if src:
            out.append((_largest(icon.get("sizes")) or 128, urljoin(manifest_url, src)))
    return out


def _data_uri(url):
    """An inline data: icon, which is where a bundler often puts a small SVG."""
    head, _, payload = url[5:].partition(",")
    ctype = head.split(";")[0].strip().lower()
    ext = TYPES.get(ctype)
    if not ext or not payload:
        return None
    try:
        raw = (base64.b64decode(payload) if ";base64" in head.lower()
               else unquote(payload).encode("utf-8"))
    except Exception:
        return None
    return (raw, ext) if len(raw) >= 64 else None


def _download(url):
    """Fetch one image, or None if it is not one or is too big."""
    if url.startswith("data:"):
        return _data_uri(url)
    if not url.startswith(("http://", "https://")):
        return None
    try:
        resp = _get(url, stream=True)
        if not resp.ok:
            return None
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        ext = TYPES.get(ctype)
        if not ext:
            # A single-page app answers every unknown path with its index.html,
            # so /favicon.ico comes back 200 with a page in it. Trusting the
            # extension there stores an HTML document as an icon.
            if ctype.startswith("text/") or ctype == "application/json":
                return None
            guess = os.path.splitext(urlparse(url).path)[1].lstrip(".").lower()
            ext = guess if guess in set(TYPES.values()) else None
        if not ext:
            return None
        buf = io.BytesIO()
        for chunk in resp.iter_content(8192):
            buf.write(chunk)
            if buf.tell() > MAX_BYTES:
                return None
        data = buf.getvalue()
        # A one-pixel spacer or an HTML error page dressed as an image.
        if len(data) < 64:
            return None
        return data, ext
    except Exception:
        return None


def fetch(page_url):
    """The best icon for a page, as (bytes, extension, source_url), or None."""
    if not page_url.startswith(("http://", "https://")):
        return None
    try:
        page = _get(page_url)
        html = page.text if page.ok else ""
        base = page.url or page_url
    except Exception:
        html, base = "", page_url

    tries = sorted(_candidates(base, html), key=lambda c: -c[0])
    # Declared or not, nearly every site answers this one.
    tries.append((0, urljoin(base, "/favicon.ico")))

    seen = set()
    for _score, url in tries:
        if url in seen:
            continue
        seen.add(url)
        got = _download(url)
        if got:
            data, ext = got
            return data, ext, url
    return None


def store(data, ext, folder):
    """Write the icon and return the filename it was stored under."""
    os.makedirs(folder, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(folder, name), "wb") as fh:
        fh.write(data)
    return name
