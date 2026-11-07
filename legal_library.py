"""The Legal library: the laws behind each product's decisions, with proof copies (issue #42).

Michael, 2026-11-07: "best practices make our app function well, legal keeps us not
in jail or sued"; buttoned up as much as we can without a lawyer; kept apart from
Best Practices "because it needs extra care and attention". A sibling of Best
Practices, never inside it: its own tables (models.Legal*), its own pages
(pm/legal_routes.py, /admin/legal), its own door (pm/legal_door_routes.py under
/api/guidance/legal) and its own bridge tools (get_legal, file_legal,
legal_recheck). This module is the work the three share.

  upsert      a product's register arrives through the door (EntertainHQ's
              scripts/legal_library.py export is the shape) and lands as entries,
              the sources they cite (kept once however many entries cite them)
              and the apps each touches, matched to My Apps tiles by name or host.
  copies      the board fetches its own copy of each source onto the volume
              (volume_files), so the proof is on the board as well as in the
              product's repo: URL, date fetched, sha256. Only official hosts.
  recheck     every source fetched again and compared with the copy by its
              substance (the page's text with volatile chrome taken out), each
              source and entry stamped with the result, the run kept as a
              LegalCheck. On demand through the bridge now; the overnight job
              calls recheck() later.
  gaps        per product (every tile in Live and earning and Building to earn,
              never Personal projects): the entries that are a gap, need a
              lawyer or whose law moved; a product with no entries at all is
              "not yet reviewed", which is a gap of its own.

Nothing here is legal advice, and every page and every answer says so
(DISCLAIMER). No model is called from here. The judgement is the session's and
the lawyer's.
"""
from __future__ import annotations

import gzip
import hashlib
import html as _html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DISCLAIMER = ("Nothing in the Legal library is legal advice. It records what the law says, what each "
              "product decided and where, and what a lawyer must settle.")

USER_AGENT = "builtbybeans-legal-library/1.0 (+https://builtbybeans.com; the board's legal records keeper)"
TIMEOUT_S = 45
RETRIES = 2
COPY_FOLDER = "legal"
MAX_COPY_BYTES = 25 * 1024 * 1024

# The hosts a copy may come from: government sites only. A redirect anywhere
# else is refused, so a copy is never a mirror's.
OFFICIAL_HOSTS = (
    "statutes.capitol.texas.gov", "tcss.legis.texas.gov", "capitol.texas.gov", "texreg.sos.state.tx.us",
    "texas-sos.appianportalsgov.com", "comptroller.texas.gov", "texasattorneygeneral.gov",
    "www.texasattorneygeneral.gov", "uscode.house.gov", "www.ecfr.gov", "www.govinfo.gov",
    "www.federalregister.gov", "www.ftc.gov", "www.fcc.gov", "docs.fcc.gov", "www.irs.gov", "www.copyright.gov",
    "www.supremecourt.gov", "ecf.ca8.uscourts.gov", "www.ca5.uscourts.gov", "leg.colorado.gov",
    "content.leg.colorado.gov", "docs.legis.wisconsin.gov", "www.nysenate.gov", "law.lis.virginia.gov",
    "lis.virginia.gov", "leginfo.legislature.ca.gov", "www.leg.state.nv.us", "delcode.delaware.gov",
    "www.sba.gov", "www.ada.gov", "www.sos.state.tx.us", "www.sos.texas.gov", "www.sll.texas.gov",
    "tile.loc.gov", "www.loc.gov",
)

_runs = {"lock": threading.Lock(), "running": None}


def _now():
    return datetime.now(timezone.utc)


def _when(value):
    """An ISO string from a register, or None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")[:120]


# Official sites that are not .gov or .us: a state's own code publisher or court system.
OFFICIAL_EXTRA = ("nmonesource.com", "www.nmonesource.com", "oscn.net", "www.oscn.net", "malegislature.gov",
                  "lis.njleg.state.nj.us", "pub.njleg.state.nj.us")


def host_ok(url):
    """A government host: .gov, a state's .us, or one of the few official publishers that are neither."""
    host = (urllib.parse.urlsplit(url or "").hostname or "").lower()
    return bool(host) and (host.endswith(".gov") or host.endswith(".us") or host in OFFICIAL_HOSTS
                           or host in OFFICIAL_EXTRA)


# ── Fetching ──────────────────────────────────────────


class _NoOffHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not host_ok(newurl):
            raise urllib.error.HTTPError(newurl, code, f"redirect off the official host refused: {newurl}",
                                         headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_NoOffHostRedirect())


def fetch_bytes(url):
    """(body, content_type, final_url). Official hosts only; raises on a refusal.
    Replaced in tests."""
    if not host_ok(url):
        raise ValueError(f"not an official host: {url}")
    last = None
    for attempt in range(RETRIES):
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml,application/pdf,*/*;q=0.8",
            "Accept-Encoding": "gzip",
        })
        try:
            with _opener.open(req, timeout=TIMEOUT_S) as resp:
                body = resp.read(MAX_COPY_BYTES + 1)
                if len(body) > MAX_COPY_BYTES:
                    raise RuntimeError("the document is larger than the library keeps")
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    body = gzip.decompress(body)
                ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                return body, ctype, resp.geturl()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as err:
            last = err
            if isinstance(err, urllib.error.HTTPError) and err.code in (403, 404, 410):
                break
            time.sleep(1 + attempt)
    raise RuntimeError(f"{url}: {last}")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


_VOLATILE = [
    re.compile(rb"<input[^>]+name=\"?__(?:VIEWSTATE|EVENTVALIDATION)[^>]*>", re.I),
    re.compile(rb"(?i)(nonce|csrf[-_]?token|__RequestVerificationToken)=\"[^\"]*\""),
    re.compile(rb"(?i)<meta[^>]+(?:generated|last-modified|date)[^>]*>"),
    re.compile(rb"(?i)page generated[^<]*"),
    re.compile(rb"(?i)<!--.*?-->", re.S),
    # Cloudflare re-scrambles its email-protection tokens on every request (texasattorneygeneral.gov).
    re.compile(rb"email-protection#[0-9a-f]+"),
    re.compile(rb"(?i)data-cfemail=\"[0-9a-f]+\""),
    # A long hex token in an attribute is a nonce, a build id or a cache key, never the law.
    re.compile(rb"=\"[0-9a-f]{24,}\""),
    re.compile(rb"\s+"),
]


# Lines of text that change on every request without a change of substance.
_VOLATILE_TEXT = [
    re.compile(r"(?i)page generated[^.]{0,80}"),
    re.compile(r"(?i)(last|date) (updated|modified|generated)\s*:?\s*[A-Za-z0-9,/: -]{4,40}"),
    re.compile(r"(?i)\b\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?\b"),
]

def page_text(data, ctype):
    """What matters on a page as text: a PDF's bytes stand as they are; for HTML the <main> element where there
    is one (a government page's chrome, its news blocks and menus, sits outside it), scripts, styles and tags
    removed, entities unescaped, whitespace collapsed, and the parts that change on every request taken out.
    Two fetches of the same law give the same text; a changed sidebar does not read as a changed law."""
    if "pdf" in (ctype or ""):
        return data
    body = data
    m = re.search(rb"(?is)<main\b.*?</main>", body)
    if m and len(m.group(0)) > 2000:
        body = m.group(0)
    body = re.sub(rb"(?is)<(script|style|noscript|svg).*?</\1>", b" ", body)
    body = re.sub(rb"(?is)<!--.*?-->", b" ", body)
    body = re.sub(rb"(?s)<[^>]+>", b" ", body)
    text = _html.unescape(body.decode("utf-8", "replace"))
    for rx in _VOLATILE_TEXT:
        text = rx.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip().encode("utf-8")


def substance(data, ctype):
    """A checksum of page_text: what the re-check compares."""
    return sha256(page_text(data, ctype))


def first_difference(a, b, span=160):
    """Where two texts first part, as a pair of snippets, or None when they agree."""
    if a == b:
        return None
    a = a.decode("utf-8", "replace") if isinstance(a, bytes) else a
    b = b.decode("utf-8", "replace") if isinstance(b, bytes) else b
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return {"stored": a[max(0, i - 60):i + span], "live": b[max(0, i - 60):i + span]}


def _ext_for(ctype, url):
    if "pdf" in (ctype or "") or (url or "").lower().endswith(".pdf"):
        return ".pdf"
    if "xml" in (ctype or "") and "html" not in (ctype or ""):
        return ".xml"
    if "json" in (ctype or ""):
        return ".json"
    if "plain" in (ctype or ""):
        return ".txt"
    return ".html"


def copy_folder():
    from flask import current_app
    return os.path.join(current_app.config["UPLOAD_FOLDER"], COPY_FOLDER)


def copy_path(source):
    """Where the board's copy of a source is on the volume, or None."""
    if not source.copy_file:
        return None
    path = os.path.join(copy_folder(), source.copy_file)
    return path if os.path.exists(path) else None


def take_copy(source):
    """Fetch the board's own copy of one source onto the volume. Returns
    (ok, message). A browser-only source is never fetched here."""
    import volume_files
    from models import db
    if source.fetch_how == "browser":
        return False, "read by hand: this site refuses scripts"
    try:
        body, ctype, final = fetch_bytes(source.url)
    except Exception as err:  # noqa: BLE001 - every refusal is said, none stops the loop
        return False, str(err)[:300]
    name = f"{_slug(source.key)}{_ext_for(ctype, final)}"
    volume_files.write(copy_folder(), name, body)
    source.copy_file = name
    source.board_sha256 = sha256(body)
    source.board_substance = substance(body, ctype)
    source.board_fetched_at = _now()
    source.board_bytes = len(body)
    source.content_type = source.content_type or ctype
    db.session.commit()
    return True, f"{len(body):,} bytes"


def take_missing_copies(limit=200):
    """Every source without a board copy, fetched. Returns (taken, failed)."""
    from models import LegalSource
    taken = failed = 0
    for s in LegalSource.query.filter(LegalSource.copy_file.is_(None), LegalSource.fetch_how != "browser") \
            .order_by(LegalSource.id).limit(limit).all():
        ok, _ = take_copy(s)
        taken += ok
        failed += not ok
    return taken, failed


# ── Filing ────────────────────────────────────────────


def _match_app(name_or_host):
    """A My Apps tile by its name (case does not matter) or by the host of its
    address; None when nothing matches, and the touch keeps the name as filed."""
    from models import AppLink
    needle = (name_or_host or "").strip().lower()
    if not needle:
        return None
    for link in AppLink.query.all():
        if (link.name or "").strip().lower() == needle:
            return link
    host = urllib.parse.urlsplit(needle if "://" in needle else "https://" + needle).hostname or needle
    for link in AppLink.query.all():
        lh = urllib.parse.urlsplit(link.url or "").hostname or ""
        if lh and (lh == host or lh.endswith("." + host) or host.endswith("." + lh)):
            return link
    for link in AppLink.query.all():
        if _slug(link.name) == _slug(needle):
            return link
    return None


def _laws_md(laws):
    lines = []
    for law in laws or []:
        if not isinstance(law, dict):
            continue
        name = law.get("name") or ""
        cite = law.get("citation") or ""
        keys = ", ".join(s.get("id") if isinstance(s, dict) else str(s) for s in (law.get("sources") or []))
        line = f"- **{name}**" if name else "-"
        if cite:
            line += f", {cite}"
        if keys:
            line += f" ({keys})"
        lines.append(line)
    return "\n".join(lines)


def _recorded_md(items):
    if isinstance(items, str):
        return items
    return "\n".join(f"- {i}" for i in (items or []) if str(i).strip())


def upsert(payload, filed_by=""):
    """A product's register, applied on arrival. Returns a summary dict."""
    from models import db, LegalEntry, LegalEntrySource, LegalSource, LegalTouch
    product = _slug(payload.get("product") or "") or "unknown"
    entries = payload.get("entries") or []
    if not isinstance(entries, list):
        raise ValueError("entries must be a list")
    made = updated = 0
    sources_seen = set()
    unmatched = set()
    slugs = []
    for raw in entries:
        if not isinstance(raw, dict) or not raw.get("slug") or not raw.get("title"):
            raise ValueError("every entry needs a slug and a title")
        slug = _slug(raw["slug"])
        status = raw.get("status") or "watch"
        from models import LEGAL_STATUSES
        if status not in LEGAL_STATUSES:
            raise ValueError(f"entry {slug}: status {status!r} is not one of {LEGAL_STATUSES}")
        entry = LegalEntry.query.filter_by(slug=slug).first()
        if entry is None:
            entry = LegalEntry(slug=slug)
            db.session.add(entry)
            made += 1
        else:
            updated += 1
        entry.title = str(raw["title"])[:240]
        entry.product = product
        entry.topic = str(raw.get("topic") or "")[:60]
        entry.jurisdiction = str(raw.get("jurisdiction") or "")[:120]
        entry.laws_md = _laws_md(raw.get("laws"))
        entry.requires_md = str(raw.get("requires") or "")
        entry.decision_md = str(raw.get("decision") or "")
        entry.recorded_in_md = _recorded_md(raw.get("recorded_in"))
        entry.status = status
        entry.notes_md = str(raw.get("notes") or "")
        entry.lawyer_question = str(raw.get("lawyer_question") or "")
        issues = raw.get("issues") or []
        entry.issues = ", ".join(str(i) for i in issues)[:300] if isinstance(issues, list) else str(issues)[:300]
        entry.filed_by = (filed_by or "")[:120]
        entry.is_active = True
        if raw.get("last_checked"):
            entry.last_checked_at = _when(raw.get("last_checked"))
        db.session.flush()
        # Sources, kept once each.
        entry.links.clear()
        db.session.flush()
        position = 0
        for law in raw.get("laws") or []:
            for s in (law.get("sources") or []) if isinstance(law, dict) else []:
                if not isinstance(s, dict) or not s.get("id"):
                    continue
                key = _slug(s["id"])
                src = LegalSource.query.filter_by(key=key).first()
                if src is None:
                    src = LegalSource(key=key)
                    db.session.add(src)
                src.title = str(s.get("title") or src.title or key)[:400]
                src.site = str(s.get("site") or src.site or "")[:200]
                if s.get("url"):
                    if not host_ok(s["url"]):
                        raise ValueError(f"source {key}: {s['url']} is not on an official host")
                    src.url = str(s["url"])[:700]
                src.pdf_url = str(s.get("pdf_url") or src.pdf_url or "")[:700]
                src.kind = str(s.get("kind") or src.kind or "")[:20]
                src.jurisdiction = str(s.get("jurisdiction") or src.jurisdiction or "")[:120]
                src.fetch_how = "browser" if s.get("fetch") == "browser" or s.get("how") == "browser" else "script"
                src.note = str(s.get("note") or src.note or "")
                if s.get("copy"):
                    src.repo_copy = str(s["copy"])[:300]
                if s.get("sha256"):
                    src.repo_sha256 = str(s["sha256"])[:64]
                if s.get("substance_sha256"):
                    src.repo_substance = str(s["substance_sha256"])[:64]
                if s.get("fetched_at"):
                    src.repo_fetched_at = _when(s["fetched_at"])
                if s.get("bytes") is not None:
                    try:
                        src.repo_bytes = int(s["bytes"])
                    except (TypeError, ValueError):
                        pass
                if s.get("content_type"):
                    src.content_type = str(s["content_type"])[:80]
                db.session.flush()
                if any(lk.source_id == src.id for lk in entry.links):
                    continue
                entry.links.append(LegalEntrySource(source=src, citation=str(law.get("citation") or "")[:400],
                                                    position=position))
                position += 1
                sources_seen.add(key)
        # The apps it touches.
        entry.touches.clear()
        db.session.flush()
        for t in raw.get("apps") or []:
            if not isinstance(t, dict):
                continue
            name = str(t.get("app") or t.get("name") or product)
            link = _match_app(name)
            if link is None:
                unmatched.add(name)
            entry.touches.append(LegalTouch(
                app_id=link.id if link else None, app_name=(link.name if link else name)[:160],
                functions_json=json.dumps(t.get("functions") or []), routes_json=json.dumps(t.get("routes") or []),
                note=str(t.get("note") or "")[:400]))
        slugs.append(slug)
    db.session.commit()
    return {"product": product, "made": made, "updated": updated, "entries": slugs,
            "sources": len(sources_seen), "unmatched_apps": sorted(unmatched)}


# ── The re-check ──────────────────────────────────────


def recheck(keys=None, by="", run=None):
    """Every source (or the named ones) fetched again and compared with the
    board's copy, or the repo's checksum where the board has none yet. Returns
    the LegalCheck. Synchronous; the thread below and the overnight job both
    call this."""
    from models import db, LegalCheck, LegalEntry, LegalSource
    if run is None:
        run = LegalCheck(by=by[:120], status="running")
        db.session.add(run)
        db.session.commit()
    q = LegalSource.query.order_by(LegalSource.id)
    if keys:
        q = q.filter(LegalSource.key.in_([_slug(k) for k in keys]))
    detail = {}
    checked = changed = unreachable = by_hand = 0
    for src in q.all():
        now = _now()
        if src.fetch_how == "browser":
            src.last_check, src.last_checked_at = "by_hand", now
            detail[src.key] = {"status": "by_hand", "url": src.url}
            by_hand += 1
            continue
        try:
            body, ctype, final = fetch_bytes(src.url)
        except Exception as err:  # noqa: BLE001
            src.last_check, src.last_checked_at = "unreachable", now
            detail[src.key] = {"status": "unreachable", "error": str(err)[:300]}
            unreachable += 1
            continue
        live = substance(body, ctype)
        # Compare with the board's own copy re-read under today's rules, so a change to what counts as volatile
        # never reads as a change in the law; the stored checksum stands in only where the copy is gone.
        known = None
        stored_bytes = None
        stored = copy_path(src)
        if stored:
            try:
                with open(stored, "rb") as fh:
                    stored_bytes = fh.read()
                known = substance(stored_bytes, src.content_type or ctype)
            except OSError:
                known = None
        known = known or src.board_substance or src.repo_substance
        if not known:
            # No copy to compare with: this fetch becomes the board's copy.
            import volume_files
            name = f"{_slug(src.key)}{_ext_for(ctype, final)}"
            volume_files.write(copy_folder(), name, body)
            src.copy_file, src.board_sha256, src.board_substance = name, sha256(body), live
            src.board_fetched_at, src.board_bytes = now, len(body)
            src.content_type = src.content_type or ctype
            known = live
        src.live_substance = live
        src.last_checked_at = now
        if live != known:
            src.last_check = "changed"
            changed += 1
            detail[src.key] = {"status": "changed", "bytes": len(body), "stored": known, "live": live}
            if stored_bytes is not None:
                # Where the words first part, so a reader can tell a changed law from a changed page at a glance.
                detail[src.key]["diff"] = first_difference(page_text(stored_bytes, src.content_type or ctype),
                                                           page_text(body, ctype))
        else:
            src.last_check = "same"
            detail[src.key] = {"status": "same", "bytes": len(body)}
        checked += 1
    # Each entry carries the worst of its sources.
    for entry in LegalEntry.query.filter_by(is_active=True).all():
        results = {lk.source.last_check for lk in entry.links}
        if not results or results == {"never"}:
            continue
        if "changed" in results:
            entry.check_result = "changed"
        elif "unreachable" in results:
            entry.check_result = "unreachable"
        elif results <= {"by_hand"}:
            entry.check_result = "by_hand"
        else:
            entry.check_result = "same"
        entry.last_checked_at = _now()
    run.status = "done"
    run.finished_at = _now()
    run.checked, run.changed, run.unreachable, run.by_hand = checked, changed, unreachable, by_hand
    run.detail_json = json.dumps(detail)
    db.session.commit()
    return run


def start_recheck(app, keys=None, by=""):
    """The re-check on a thread, so a request answers at once. Returns the run
    id, or the running run's id when one is already going."""
    from models import db, LegalCheck
    with _runs["lock"]:
        running = _runs["running"]
        if running is not None:
            live = db.session.get(LegalCheck, running)
            if live is not None and live.status == "running":
                return running
        run = LegalCheck(by=(by or "")[:120], status="running")
        db.session.add(run)
        db.session.commit()
        run_id = run.id
        _runs["running"] = run_id

    def work():
        with app.app_context():
            from models import db as _db, LegalCheck as _LC
            row = _db.session.get(_LC, run_id)
            try:
                recheck(keys, by=by, run=row)
            except Exception as err:  # noqa: BLE001 - the run records its own failure
                row.status = "failed"
                row.finished_at = _now()
                row.note = str(err)[:1000]
                _db.session.commit()
            finally:
                with _runs["lock"]:
                    if _runs["running"] == run_id:
                        _runs["running"] = None

    threading.Thread(target=work, name=f"legal-recheck-{run_id}", daemon=True).start()
    return run_id


def run_summary(run):
    return {"id": run.id, "status": run.status, "by": run.by or "",
            "started_at": run.started_at.isoformat() + "Z" if run.started_at else None,
            "finished_at": run.finished_at.isoformat() + "Z" if run.finished_at else None,
            "checked": run.checked, "changed": run.changed, "unreachable": run.unreachable,
            "by_hand": run.by_hand, "detail": run.detail, "note": run.note or ""}


# ── Reading ───────────────────────────────────────────


def product_tiles():
    """The tiles the gaps view covers: Live and earning and Building to earn,
    in the board's order; never Personal projects."""
    from models import AppLink
    tiles = AppLink.query.order_by(AppLink.position.is_(None), AppLink.position, AppLink.id).all()
    return [t for t in tiles if t.section in ("client", "building")]


def gaps_by_product():
    """[{tile, section, entries, reviewed, counts}] for every product tile."""
    from models import LegalEntry
    live = LegalEntry.query.filter_by(is_active=True).order_by(LegalEntry.status, LegalEntry.title).all()
    out = []
    for tile in product_tiles():
        mine = [e for e in live if any(t.app_id == tile.id for t in e.touches)]
        attention = [e for e in mine if e.needs_attention]
        counts = {k: sum(1 for e in mine if e.status == k) for k in ("backed", "gap", "lawyer", "watch", "not_applicable")}
        counts["moved"] = sum(1 for e in mine if e.check_result == "changed")
        out.append({"tile": tile, "section": tile.section, "entries": attention, "all": mine,
                    "reviewed": bool(mine), "counts": counts})
    return out


def _d(value):
    return value.strftime("%Y-%m-%d") if value else "never"


def entry_text(entry, with_sources=True):
    """One entry as the text a session reads."""
    lines = [f"{entry.title} [{entry.slug}]",
             f"  status: {entry.status_label}; topic: {entry.topic or '-'}; jurisdiction: {entry.jurisdiction or '-'}; "
             f"last checked: {_d(entry.last_checked_at)} ({entry.check_label})"]
    if entry.laws_md:
        lines.append("  THE LAW")
        lines += ["    " + ln for ln in entry.laws_md.splitlines() if ln.strip()]
    if entry.requires_md:
        lines.append("  WHAT IT REQUIRES")
        lines += ["    " + ln for ln in entry.requires_md.splitlines() if ln.strip()]
    if entry.decision_md:
        lines.append("  OUR DECISION")
        lines += ["    " + ln for ln in entry.decision_md.splitlines() if ln.strip()]
    if entry.recorded_in_md:
        lines.append("  RECORDED IN")
        lines += ["    " + ln for ln in entry.recorded_in_md.splitlines() if ln.strip()]
    if entry.notes_md:
        lines.append("  NOTES")
        lines += ["    " + ln for ln in entry.notes_md.splitlines() if ln.strip()]
    if entry.lawyer_question:
        lines.append("  FOR THE LAWYER")
        lines += ["    " + ln for ln in entry.lawyer_question.splitlines() if ln.strip()]
    if entry.issue_list:
        lines.append("  ISSUES: " + ", ".join(entry.issue_list))
    for t in entry.touches:
        fns = ", ".join(f"{f['name']} ({f['file']})" if f["file"] else f["name"] for f in t.functions)
        lines.append(f"  APP {t.app_name}: functions: {fns or '-'}; routes: {', '.join(t.routes) or '-'}"
                     + (f"; {t.note}" if t.note else ""))
    if with_sources:
        for lk in entry.links:
            s = lk.source
            lines.append(f"  SOURCE {s.key}: {s.title}; {s.url}; fetched {_d(s.fetched_at)}; "
                         f"sha256 {s.sha256 or '-'}; last check {s.check_label}"
                         + ("; read by hand (the site refuses scripts)" if s.fetch_how == "browser" else ""))
    return "\n".join(lines)


def _search_hit(entry, stems):
    hay = " ".join([entry.title, entry.slug, entry.topic, entry.jurisdiction, entry.laws_md or "",
                    entry.requires_md or "", entry.decision_md or "", entry.notes_md or "",
                    entry.lawyer_question or "", entry.issues or "",
                    " ".join(t.app_name for t in entry.touches)]).lower()
    return all(s in hay for s in stems)


def library_text(q="", app=None, status=None, product=None, topic=None, limit=60):
    """The library as text: the brief a session gets from get_legal."""
    from models import LegalEntry, LEGAL_STATUSES
    rows = LegalEntry.query.filter_by(is_active=True).order_by(LegalEntry.status, LegalEntry.topic, LegalEntry.title).all()
    stems = [s for s in re.split(r"[^a-z0-9]+", (q or "").lower()) if len(s) > 2]
    if stems:
        rows = [r for r in rows if _search_hit(r, stems)]
    if status and status in LEGAL_STATUSES:
        rows = [r for r in rows if r.status == status]
    if product:
        rows = [r for r in rows if r.product == _slug(product)]
    if topic:
        rows = [r for r in rows if r.topic == _slug(topic)[:60]]
    if app:
        needle = (app or "").strip().lower()
        rows = [r for r in rows if any(needle in (t.app_name or "").lower() for t in r.touches)]
    out = [f"THE LEGAL LIBRARY, {_now().strftime('%Y-%m-%d %H:%M')} UTC. {DISCLAIMER}",
           f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'}"
           + (" (the first %d shown; narrow the query for the rest)" % limit if len(rows) > limit else "") + ".", ""]
    for r in rows[:limit]:
        out.append(entry_text(r, with_sources=not stems and len(rows) <= 12))
        out.append("")
    if not rows:
        out.append("Nothing matches. The library lists what each product decided and the law behind it; "
                   "file an entry with file_legal when a decision is made.")
    return "\n".join(out)


def gaps_text():
    """The per-product gaps as text."""
    out = [f"LEGAL GAPS BY PRODUCT, {_now().strftime('%Y-%m-%d')}. {DISCLAIMER}", ""]
    for g in gaps_by_product():
        tile = g["tile"]
        head = f"{tile.name} ({'Live and earning' if g['section'] == 'client' else 'Building to earn'})"
        if not g["reviewed"]:
            out.append(f"{head}: NOT YET REVIEWED. No entry names this product; its decisions have not been "
                       "checked against the law.")
            out.append("")
            continue
        c = g["counts"]
        out.append(f"{head}: {c['backed']} backed, {c['gap']} gaps, {c['lawyer']} for the lawyer, "
                   f"{c['watch']} to watch, {c['moved']} whose law moved")
        for e in g["entries"]:
            out.append(f"  - {e.title} [{e.slug}]: {e.status_label}"
                       + (f"; the law moved since {_d(e.last_checked_at)}" if e.check_result == "changed" else "")
                       + (f". {e.lawyer_question.splitlines()[0]}" if e.status == "lawyer" and e.lawyer_question else ""))
        out.append("")
    return "\n".join(out)


def counts():
    """The tab strip's numbers."""
    from models import LegalCheck, LegalEntry, LegalSource
    live = LegalEntry.query.filter_by(is_active=True)
    return {
        "entries": live.count(),
        "gaps": live.filter(LegalEntry.status.in_(("gap", "lawyer"))).count(),
        "sources": LegalSource.query.count(),
        "checks": LegalCheck.query.count(),
        "moved": live.filter(LegalEntry.check_result == "changed").count(),
    }
