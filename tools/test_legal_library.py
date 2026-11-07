# -*- coding: utf-8 -*-
"""The Legal library (issue #42): filed through the door, read back by a session,
shown beside Best Practices, with the proof copies and the re-check.

Michael, 2026-11-07: legal runs the way Best Practices does but kept apart from
it, with proof copies of the law behind each decision, the apps and functions
each touches, a gaps view per product, and a re-check a session runs on demand
that the overnight job can call later. Proves:

  1. A register filed through the door lands as entries, sources (kept once
     however many entries cite them) and touches matched to My Apps tiles by
     name or host; a source off an official host is refused; a bad status is
     refused; filing again updates in place.
  2. The board takes its own copy of each source onto the volume (a fake
     fetcher here) with its sha256 and date, and serves it as the proof.
  3. The re-check fetches each source again, says same or changed by
     substance, marks browser-only sources as read by hand, stamps the
     entries, and keeps the run; the door answers it and the bridge's loop
     can poll it.
  4. The door reads the library as text, one entry, and the gaps per product:
     Live and earning and Building to earn only, never Personal projects, and
     a product nobody filed is "not yet reviewed".
  5. The pages render with the disclaimer on every one, the sidebar carries
     Legal apart from the Handbook, and Michael's status press records his
     call with his name and the day.
  6. The door is shut without the key.

Run: python tools/test_legal_library.py
"""
import json
import os
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-legal-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["GUIDANCE_API_KEY"] = "test-key"
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import app_icon_service  # noqa: E402
app_icon_service.fetch = lambda url: None

import legal_library  # noqa: E402
from app import create_app  # noqa: E402
from models import (db, AppLink, LegalCheck, LegalEntry, LegalSource, LegalTouch, User)  # noqa: E402

application = create_app()
application.config["GUIDANCE_API_KEY"] = "test-key"
application.config["WTF_CSRF_ENABLED"] = False
application.config["LEGAL_COPIES_INLINE"] = True
AUTH = {"Authorization": "Bearer test-key"}
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


# A fake of the law: what each URL answers, changeable between fetches.
PAGES = {
    "https://tcss.legis.texas.gov/resources/BC/htm/BC.541.htm": (b"<html><title>BC 541</title><body>Sec. 541.104. DUTIES OF PROCESSOR. The contract must include...</body></html>", "text/html"),
    "https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap110-sec8403.htm": (b"<html><title>15 USC 8403</title><body>It shall be unlawful for any person to charge...</body></html>", "text/html"),
    "https://www.govinfo.gov/content/pkg/FR-2026-03-13/pdf/2026-04952.pdf": (b"%PDF-1.4 the ANPRM", "application/pdf"),
}


def fake_fetch(url):
    if url not in PAGES:
        raise RuntimeError(f"{url}: HTTP Error 404")
    body, ctype = PAGES[url]
    return body, ctype, url


legal_library.fetch_bytes = fake_fetch

REGISTER = {
    "product": "entertainhq",
    "project": "EntertainHQ #310",
    "entries": [
        {
            "slug": "processor-contract-terms",
            "title": "Schedule B carries the processor terms the Texas privacy act lists",
            "topic": "personal-data", "jurisdiction": "Texas", "status": "backed",
            "laws": [{"name": "Texas Data Privacy and Security Act", "citation": "Tex. Bus. & Com. Code 541.104(b)",
                      "sources": [{"id": "tx-bc-541", "title": "Tex. Bus. & Com. Code ch. 541",
                                   "site": "statutes.capitol.texas.gov",
                                   "url": "https://tcss.legis.texas.gov/resources/BC/htm/BC.541.htm",
                                   "kind": "statute", "fetched_at": "2026-11-07T18:00:00Z",
                                   "sha256": "a" * 64, "substance_sha256": "b" * 64, "bytes": 80485,
                                   "content_type": "text/html",
                                   "copy": "docs/legal/library/sources/tx-bc-541.html"}]}],
            "requires": "A processor's contract must carry six things: instructions, nature and purpose...",
            "decision": "Schedule B of the Customer Agreement carries all six.",
            "recorded_in": ["docs/legal/customer_agreement.md, Schedule B"],
            "issues": ["#310"],
            "apps": [{"app": "EntertainHQ", "functions": [{"name": "legal_docs.letterhead", "file": "legal_docs.py"}],
                      "routes": ["/customer-agreement"]}],
        },
        {
            "slug": "rosca-renewal-disclosure",
            "title": "Renewal terms are shown and ticked before the card is charged",
            "topic": "renewal", "jurisdiction": "Federal", "status": "lawyer",
            "lawyer_question": "Does ROSCA's 'consumer' reach a business buyer? Treat it as if it does.",
            "laws": [{"name": "ROSCA", "citation": "15 U.S.C. 8403",
                      "sources": [{"id": "us-15-8403", "title": "15 U.S.C. 8403", "site": "govinfo.gov",
                                   "url": "https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap110-sec8403.htm",
                                   "kind": "statute", "sha256": "c" * 64, "substance_sha256": "d" * 64}]},
                     {"name": "FTC Negative Option Rule ANPRM", "citation": "91 FR 12318",
                      "sources": [{"id": "fr-2026-04952", "title": "91 FR 12318", "site": "govinfo.gov",
                                   "url": "https://www.govinfo.gov/content/pkg/FR-2026-03-13/pdf/2026-04952.pdf",
                                   "kind": "regulation", "sha256": "e" * 64, "substance_sha256": "f" * 64}]}],
            "requires": "Disclose the material terms before billing, get express informed consent, offer a simple cancel.",
            "decision": "The signup box and the Stripe portal cancel.",
            "recorded_in": ["docs/legal/customer_agreement.md 5.2, 5.3"],
            "apps": [{"app": "app.entertainhq.com", "functions": ["signup._checkout_params"], "routes": ["/signup"]}],
        },
        {
            "slug": "ny-renewal-notice",
            "title": "New York's renewal notice for service contracts",
            "topic": "renewal", "jurisdiction": "New York", "status": "watch",
            "laws": [{"name": "N.Y. Gen. Oblig. Law 5-903", "citation": "5-903",
                      "sources": [{"id": "ny-gol-5-903", "title": "N.Y. GOL 5-903", "site": "nysenate.gov",
                                   "url": "https://www.nysenate.gov/legislation/laws/GOB/5-903",
                                   "kind": "statute", "fetch": "browser", "sha256": "1" * 64,
                                   "substance_sha256": "2" * 64}]}],
            "requires": "Written notice 15 to 30 days before the deadline for terms over a month.",
            "decision": "Monthly plans are exempt; yearly plans get the 30-day reminder.",
            "recorded_in": ["docs/legal/customer_agreement.md 5.2"],
            "apps": [{"app": "Nowhere Known", "functions": [], "routes": []}],
        },
    ],
}

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    ehq = AppLink(name="EntertainHQ", url="https://app.entertainhq.com", board_group="client")
    kuper = AppLink(name="Kuper Plumbing", url="https://kuperplumbing.com", board_group="building")
    mine = AppLink(name="Bible Study", url="https://bible.example.test", board_group="mine")
    db.session.add_all([boss, ehq, kuper, mine])
    db.session.commit()
    ehq_id, kuper_id, mine_id = ehq.id, kuper.id, mine.id

c = application.test_client()

print("1. Filing through the door")
r = c.post("/api/guidance/legal", headers=AUTH, json=REGISTER)
check("the register is accepted", r.status_code == 201, r.get_data(as_text=True)[:300])
body = r.get_json() or {}
check("three made, none updated", body.get("made") == 3 and body.get("updated") == 0, body)
check("four sources kept once each", body.get("sources") == 4, body)
check("the app nobody has is reported", body.get("unmatched_apps") == ["Nowhere Known"], body)
check("the answer carries the disclaimer", "legal advice" in (body.get("disclaimer") or ""))
with application.app_context():
    e1 = LegalEntry.query.filter_by(slug="processor-contract-terms").one()
    check("the touch matched the tile by name", e1.touches[0].app_id == ehq_id)
    e2 = LegalEntry.query.filter_by(slug="rosca-renewal-disclosure").one()
    check("the touch matched the tile by host", e2.touches[0].app_id == ehq_id and e2.touches[0].app_name == "EntertainHQ")
    check("functions as filed: a dict and a bare name both read",
          e1.touches[0].functions[0]["file"] == "legal_docs.py" and e2.touches[0].functions[0]["name"] == "signup._checkout_params")
    check("the laws read as markdown with the source ids", "541.104(b)" in e1.laws_md and "(tx-bc-541)" in e1.laws_md)
    src = LegalSource.query.filter_by(key="tx-bc-541").one()
    check("the repo's checksum and date are kept", src.repo_sha256 == "a" * 64 and src.repo_fetched_at is not None)
    check("the browser-only source is marked", LegalSource.query.filter_by(key="ny-gol-5-903").one().fetch_how == "browser")
    check("the board took its own copies (inline here)",
          src.copy_file and os.path.exists(os.path.join(TMP, "legal", src.copy_file)) and src.board_sha256, src.copy_file)
    check("a browser-only source has no board copy", LegalSource.query.filter_by(key="ny-gol-5-903").one().copy_file is None)

r = c.post("/api/guidance/legal", headers=AUTH, json={"product": "x", "entries": [{"slug": "bad", "title": "t", "status": "maybe", "laws": []}]})
check("a status outside the five is refused", r.status_code == 400 and "status" in r.get_json()["error"])
r = c.post("/api/guidance/legal", headers=AUTH, json={"product": "x", "entries": [
    {"slug": "mirror", "title": "t", "status": "watch",
     "laws": [{"name": "x", "sources": [{"id": "mirror-1", "url": "https://law.cornell.edu/x"}]}]}]})
check("a source off an official host is refused", r.status_code == 400 and "official" in r.get_json()["error"])
again = json.loads(json.dumps(REGISTER))
again["entries"][0]["status"] = "gap"
again["entries"][0]["title"] = "Schedule B carries the processor terms (changed)"
r = c.post("/api/guidance/legal", headers=AUTH, json=again)
check("filing again updates in place", r.status_code == 201 and r.get_json()["updated"] == 3 and r.get_json()["made"] == 0)
with application.app_context():
    check("the entry took the new status and title",
          LegalEntry.query.filter_by(slug="processor-contract-terms").one().status == "gap"
          and LegalEntry.query.count() == 3 and LegalSource.query.count() == 4 and LegalTouch.query.count() == 3)

print("2. The proof copy is served")
with application.app_context():
    boss = User.query.filter_by(username="mb").one()
with c.session_transaction() as sess:
    sess["_user_id"] = str(boss.id)
    sess["_fresh"] = True
r = c.get("/admin/legal/sources/tx-bc-541/copy")
check("the board's copy of the statute comes back as a file", r.status_code == 200 and b"541.104" in r.data
      and "attachment" in (r.headers.get("Content-Disposition") or ""), r.status_code)
check("nothing in it may load or run", r.headers.get("Content-Security-Policy") == "default-src 'none'")
r = c.get("/admin/legal/sources/ny-gol-5-903/copy")
check("no copy, no file", r.status_code == 404)

print("3. The re-check")
PAGES["https://tcss.legis.texas.gov/resources/BC/htm/BC.541.htm"] = (
    b"<html><title>BC 541</title><body>Sec. 541.104. DUTIES OF PROCESSOR. The contract must include SEVEN things now...</body></html>", "text/html")
with application.app_context():
    run = legal_library.recheck(by="the test")
    check("the run is done", run.status == "done" and run.checked == 3 and run.by == "the test", run)
    check("the statute that changed is said", run.changed == 1 and run.detail["tx-bc-541"]["status"] == "changed")
    check("the one that did not is unchanged", run.detail["us-15-8403"]["status"] == "same")
    check("the pdf is compared by its bytes", run.detail["fr-2026-04952"]["status"] == "same")
    check("the browser-only source is read by hand", run.by_hand == 1 and run.detail["ny-gol-5-903"]["status"] == "by_hand")
    e1 = LegalEntry.query.filter_by(slug="processor-contract-terms").one()
    e2 = LegalEntry.query.filter_by(slug="rosca-renewal-disclosure").one()
    e3 = LegalEntry.query.filter_by(slug="ny-renewal-notice").one()
    check("each entry carries the worst of its sources",
          e1.check_result == "changed" and e2.check_result == "same" and e3.check_result == "by_hand"
          and e1.last_checked_at is not None)
    check("the moved law counts as needing attention, a watched one read by hand does not", e1.needs_attention and not e3.needs_attention)
PAGES.pop("https://www.govinfo.gov/content/pkg/USCODE-2023-title15/html/USCODE-2023-title15-chap110-sec8403.htm")
r = c.post("/api/guidance/legal/recheck", headers=AUTH, json={"project": "the test", "sources": ["us-15-8403"]})
check("the door starts a run", r.status_code == 202 and r.get_json()["run"]["id"])
run_id = r.get_json()["run"]["id"]
import time
for _ in range(40):
    r = c.get(f"/api/guidance/legal/checks/{run_id}", headers=AUTH)
    if r.get_json()["run"]["status"] != "running":
        break
    time.sleep(0.25)
run = r.get_json()["run"]
check("the run on the thread finishes and the door reports it",
      run["status"] == "done" and run["unreachable"] == 1 and run["detail"]["us-15-8403"]["status"] == "unreachable", run)
r = c.get("/api/guidance/legal/checks", headers=AUTH)
check("the door lists the runs", len(r.get_json()["runs"]) == 2)

print("4. Reading through the door")
r = c.get("/api/guidance/legal", headers=AUTH)
text = r.get_json()["text"]
check("the library reads as text with the disclaimer first", text.startswith("THE LEGAL LIBRARY") and "legal advice" in text)
check("every entry is in it", "processor-contract-terms" in text and "rosca-renewal-disclosure" in text and "ny-renewal-notice" in text)
r = c.get("/api/guidance/legal?q=processor+contract", headers=AUTH)
check("words narrow it", "processor-contract-terms" in r.get_json()["text"] and "ny-renewal-notice" not in r.get_json()["text"])
r = c.get("/api/guidance/legal?status=lawyer", headers=AUTH)
check("status narrows it", "rosca-renewal-disclosure" in r.get_json()["text"] and "processor-contract-terms" not in r.get_json()["text"])
r = c.get("/api/guidance/legal?app=entertainhq", headers=AUTH)
check("an app narrows it", "ny-renewal-notice" not in r.get_json()["text"] and "processor-contract-terms" in r.get_json()["text"])
r = c.get("/api/guidance/legal/rosca-renewal-disclosure", headers=AUTH)
one = r.get_json()
check("one entry comes whole: its sources, their checksums and the lawyer's question",
      "8403" in one["text"] and one["entry"]["sources"][0]["sha256"] and "FOR THE LAWYER" in one["text"]
      and one["entry"]["apps"][0]["routes"] == ["/signup"])
check("the entry carries its check", one["entry"]["check_result"] == "unreachable")
r = c.get("/api/guidance/legal/gaps", headers=AUTH)
gaps = r.get_json()["text"]
check("the gaps are per product, the two earning sections only",
      "EntertainHQ (Live and earning)" in gaps and "Kuper Plumbing (Building to earn)" in gaps and "Bible Study" not in gaps)
check("a product nobody filed is not yet reviewed", "Kuper Plumbing (Building to earn): NOT YET REVIEWED" in gaps)
check("the gap and the lawyer item are listed, the watch is not",
      "processor-contract-terms" in gaps and "rosca-renewal-disclosure" in gaps and "ny-renewal-notice" not in gaps)
r = c.get("/api/guidance/legal/no-such", headers=AUTH)
check("an unknown slug is 404", r.status_code == 404)

print("5. The pages")
for path, marks in (
    ("/admin/legal/", ["processor-contract-terms", "rosca-renewal-disclosure", "Every status", "data-legal-disclaimer"]),
    ("/admin/legal/processor-contract-terms", ["541.104", "legal_docs.letterhead", "/customer-agreement", "the board's copy", "data-legal-disclaimer", "data-status-form"]),
    ("/admin/legal/gaps", ["Not yet reviewed", "Kuper Plumbing", "data-legal-disclaimer"]),
    ("/admin/legal/sources", ["tx-bc-541", "saved from a browser", "data-legal-disclaimer"]),
    ("/admin/legal/checks", ["Run 1", "data-run-check", "data-legal-disclaimer"]),
):
    r = c.get(path)
    html = r.get_data(as_text=True)
    missing = [m for m in marks if m not in html]
    check(f"{path} renders with what it must", r.status_code == 200 and not missing, (r.status_code, missing))
r = c.get("/admin/legal/gaps")
html = r.get_data(as_text=True)
check("the gaps page leaves Personal projects out", "Bible Study" not in html)
check("the sidebar carries Legal apart from the Handbook",
      re.search(r'href="/admin/legal/"[^>]*class="sidebar-link', html) and "Handbook" in html)
check("the Legal tab strip is its own", 'data-keep="legal-tabs"' in html and 'data-keep="practices-tabs"' not in html)
r = c.post("/admin/legal/processor-contract-terms/status", data={"status": "backed", "reason": "the lawyer agreed", "next": "/admin/legal/"})
check("Michael's press moves the status and comes back", r.status_code == 302 and r.headers["Location"].endswith("/admin/legal/"))
with application.app_context():
    e1 = LegalEntry.query.filter_by(slug="processor-contract-terms").one()
    check("the call is recorded with his name and the day",
          e1.status == "backed" and "Michael, 20" in e1.notes_md and "the lawyer agreed" in e1.notes_md, e1.notes_md)
r = c.post("/admin/legal/processor-contract-terms/status", data={"status": "nonsense"})
check("a status outside the five is refused on the page too", r.status_code == 400)
r = c.get("/admin/practices/")
check("the Handbook's strip does not grow a Legal tab", r.status_code == 200 and "legal-tabs" not in r.get_data(as_text=True))

print("6. The door is shut without the key")
fresh = application.test_client()
check("GET refused", fresh.get("/api/guidance/legal").status_code == 401)
check("POST refused", fresh.post("/api/guidance/legal", json=REGISTER).status_code == 401)
check("recheck refused", fresh.post("/api/guidance/legal/recheck", json={}).status_code == 401)

print()
if FAIL:
    print(f"FAILED: {len(FAIL)}: " + "; ".join(FAIL))
    sys.exit(1)
print("All checks passed.")
