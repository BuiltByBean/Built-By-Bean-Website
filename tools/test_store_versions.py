# -*- coding: utf-8 -*-
"""Two readings that were wrong on 2026-11-01, pinned.

1. The Play listing's live version. The page carries `]]],"1.2.3",null,` once
   per REVIEW (the version that reviewer had installed) and the live version
   once, in the About blob `[[["1.2.3"]],[[[<targetSdk>]],[[[<minSdk>,"..."]]`.
   The first reader took the review one: Firefox read 135.0.1 against a live
   159.0, and an app with no reviews matched nothing at all. The pages here are
   cut down from the real ones, reviews first, as Play serves them.
2. The guidance door's text bound. A replace was cut to 6000 characters without
   a word, so a rewrite of a field grown past that by appends would have
   deleted the field's tail on accept. Now the whole text is kept up to
   TEXT_MAX and anything longer is refused, with nothing recorded.

Run: python tools/test_store_versions.py          (offline)
     python tools/test_store_versions.py --live   (also reads Firefox's real listing)
"""
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-stores-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["GUIDANCE_API_KEY"] = "test-key"
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import store_versions_service as svs  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


class Page:
    def __init__(self, status_code, text=""):
        self.status_code, self.text = status_code, text


def serve(page):
    svs._get = lambda url, params: page


REVIEW = ('["gp:AOqp",["Ana",null],5,null,"Works well",[1761000000,0],12,null,'
          '[[null,[]],[["vaf_a"]]]]],"{v}",null,[["vaf_b"]]')
ABOUT = (']],"You can request that data be deleted"]],1],null,null,null,'
         '{slot},null,null,null,[null,[null,"What is new"]]')
UPDATED = 'Updated on</div><div class="xg1aie">Oct 22, 2026</div>'
TITLE = "<title>{t} - Apps on Google Play</title>"


def listing(about_slot, reviews=("135.0.1", "134.0.1"), title="Firefox"):
    return (TITLE.format(t=title) + UPDATED
            + "".join(REVIEW.format(v=v) for v in reviews)
            + ABOUT.format(slot=about_slot))


class Link:
    def __init__(self, bundle=None, package=None, versions=None):
        self.app_store_bundle_id, self.play_package = bundle, package
        self.store_versions, self.store_checked_at = versions, None


print("The Play listing")
serve(Page(200, listing('[[["159.0"]],[[[37]],[[[26,"8.0"]]]]]')))
got = svs.lookup_play("org.mozilla.firefox")
check("reads the About blob, not a review", got.get("version") == "159.0", got)
check("still reads the title and the update date",
      got.get("name") == "Firefox" and got.get("released") == "Oct 22, 2026", got)

serve(Page(200, listing('[[["159.0"]],[[[37]],[[[26,"8.0"]]]]]', reviews=())))
check("an app with no reviews yet is live", svs.lookup_play("x").get("version") == "159.0")

serve(Page(200, listing('[[["50614-r-2026-10-20"]],[[[37]],[[[24,"7.0"]]]]]',
                        reviews=("50598-r-2026-07-13",))))
check("a version that is not dotted numbers", svs.lookup_play("x").get("version") == "50614-r-2026-10-20")

serve(Page(200, listing("[[null,[]],[[[35]],[null,[]]]]", reviews=("6.96.2",))))
got = svs.lookup_play("com.duolingo")
check("per-device builds read live with no version, never a review's",
      got.get("status") == "live" and got.get("version") == "", got)

serve(Page(200, "<html>" + REVIEW.format(v="1.0.0") + "</html>"))
check("a page whose About blob moved is an error, not a guess",
      svs.lookup_play("x") == {"status": "error"})

serve(Page(404))
check("404 is not listed", svs.lookup_play("x") == {"status": "not_listed"})

print("The tile's verdict")
both = Link("io.x", "io.x", '{"app_store": {"status": "live", "version": "1.0.1"},'
                            ' "play": {"status": "live", "version": "1.0.1"}}')
check("same version on both reads match", svs.summary(both)["verdict"] == "match")
both.store_versions = both.store_versions.replace('"version": "1.0.1"}}', '"version": "1.0.0"}}')
check("two versions read differ", svs.summary(both)["verdict"] == "differ")
both.store_versions = both.store_versions.replace('"version": "1.0.0"}}', '"version": ""}}')
check("a store with no single version reads live, not differ", svs.summary(both)["verdict"] == "live")

print("The guidance door")
from app import create_app  # noqa: E402
from models import db, Playbook, CatalogueProposal  # noqa: E402
from pm import guidance_routes  # noqa: E402

application = create_app()
application.config["GUIDANCE_API_KEY"] = "test-key"
with application.app_context():
    db.create_all()
    db.session.add(Playbook(slug="vendor", display_name="Vendor", traps_md="x" * 14005))
    db.session.commit()
    web = application.test_client()
    auth = {"Authorization": "Bearer test-key"}

    def propose(**body):
        body = {"kind": "playbook", "slug": "vendor", "project": "Test", "reason": "test", **body}
        return web.post("/api/guidance/proposals", json=body, headers=auth)

    whole = "y" * 14100
    r = propose(field="traps_md", mode="replace", text=whole)
    row = CatalogueProposal.query.order_by(CatalogueProposal.id.desc()).first()
    check("a replace past 6000 waits in the inbox whole",
          r.status_code == 200 and row is not None and row.proposed == whole,
          (r.status_code, len(row.proposed) if row else None))

    before = CatalogueProposal.query.count()
    r = propose(field="traps_md", mode="replace", text="z" * (guidance_routes.TEXT_MAX + 1))
    check("past TEXT_MAX is refused with a 400 that says so",
          r.status_code == 400 and "at most" in (r.get_json() or {}).get("error", ""), r.get_json())
    check("and nothing is recorded", CatalogueProposal.query.count() == before)

    lesson = "**A long lesson.** " + "w" * 6500
    r = propose(field="traps_md", mode="append", text=lesson)
    check("an append past 6000 lands whole",
          r.status_code == 200 and lesson in Playbook.query.filter_by(slug="vendor").first().traps_md,
          r.get_json())

if "--live" in sys.argv:
    print("Firefox's real listing")
    import importlib
    importlib.reload(svs)
    got = svs.lookup_play("org.mozilla.firefox")
    import re
    v = got.get("version") or ""
    check("live answer reads as a version", got.get("status") == "live" and re.fullmatch(r"\d+(\.\d+)*", v), got)
    print("       Firefox on Play right now:", v)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
sys.exit(1 if FAIL else 0)
