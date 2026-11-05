# -*- coding: utf-8 -*-
"""My Apps: every tile one height, measured in a real browser.

Michael, 2026-11-05: "I also dont like how the app rectangles are different
heights. the height of a one like wedding planner ... should be the default
height ... the ones that also show app store and google play store live and
versions matching ... make that fit and not expand the height". And no pills,
versions in colour, a button for each live store listing, no pencil.

This boots the board on a throwaway SQLite database with the tiles that used
to grow (two stores, one store not live, a long name, a site that is down, a
long platform address, every button at once) beside a plain web tile, and at
320, 375, 768, 1024 and 1600 asserts:

  1. every tile is the height of the plain web tile, to the pixel;
  2. nothing inside a tile spills out of it and the page never scrolls
     sideways; every button keeps its 44px; the icon opens the app at every
     width, and Open is there wherever five buttons fit (from 360);
  3. a version reads green where the stores agree, red where they differ,
     yellow "not live"; and it is on screen, not cut off by the host;
  4. three sections, Live and earning, Building to earn, Personal projects,
     in that order, each heading on one line with its rule across, and more
     room above a section than between two tiles (2026-11-05: "make sure the
     sections are clearly separated").

Run: python tools/test_apps_tiles_browser.py   (screenshots: --shots <dir>)
"""
import json
import os
import pathlib
import socket
import sys
import tempfile
import threading
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-tiles-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["MAIL_SYNC_DISABLED"] = "1"
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)[:400]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("  FAIL playwright is installed, so the tiles were actually measured")
    sys.exit(1)

import app_icon_service  # noqa: E402
app_icon_service.fetch = lambda url: None
import store_versions_service  # noqa: E402
store_versions_service.is_stale = lambda link, now=None: False   # never ask a real store

from app import create_app  # noqa: E402
from models import db, AppLink, User, SiteCheck  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = free_port()
BASE = f"http://127.0.0.1:{PORT}"
APPLE = "https://apps.apple.com/us/app/x/id6700000001"
PLAY = "https://play.google.com/store/apps/details?id=com.x"
RAIL = "https://railway.com/project/p/service/s"
GIT = "https://github.com/BuiltByBean/x"


def stores(a, p):
    return json.dumps({"app_store": a, "play": p})


LIVE = {"status": "live", "version": "1.0.1", "url": APPLE}
LIVE_P = {"status": "live", "version": "1.0.1", "url": PLAY}
TILES = [
    # (name, url, extra fields)
    ("Wedding Planner", "https://web-production-89814.up.railway.app",
     dict(railway_url=RAIL, github_url=GIT)),
    ("EntertainHQ", "https://entertainhq.com",
     dict(railway_url=RAIL, github_url=GIT, app_store_bundle_id="com.ehq", play_package="com.ehq",
          store_versions=stores(LIVE, LIVE_P))),
    ("Data Dungeon", "https://datadungeon.io",
     dict(railway_url=RAIL, github_url=GIT, app_store_bundle_id="com.dd", play_package="com.dd",
          store_versions=stores({"status": "not_listed"}, {"status": "not_listed"}))),
    ("Master by Trade", "https://masterbytrade.com",
     dict(railway_url=RAIL, github_url=GIT, app_store_bundle_id="com.mbt",
          store_versions=json.dumps({"app_store": {"status": "not_listed"}}))),
    ("Differing Stores", "https://differ.example.test",
     dict(railway_url=RAIL, github_url=GIT, app_store_bundle_id="com.d", play_package="com.d",
          store_versions=stores(dict(LIVE, version="1.2.10"), dict(LIVE_P, version="1.2.9")))),
    ("Robinsonandco Project Manager With A Very Long Name Indeed", "https://covenantchristianchurch-production.up.railway.app/admin/login",
     dict(railway_url=RAIL, github_url=GIT, app_store_bundle_id="com.r", play_package="com.r",
          store_versions=stores(dict(LIVE, version="10.12.3"), {"status": "not_listed"}))),
    ("Down Site", "https://down.example.test", dict(github_url=GIT)),
    ("Bible Study", "/Bible-Study", {}),
]

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("password")
    db.session.add(boss)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i, (name, url, extra) in enumerate(TILES):
        db.session.add(AppLink(name=name, url=url, board_group="client" if i < 6 else ("building" if i == 6 else "mine"),
                               store_checked_at=now if extra.get("store_versions") else None, **extra))
    db.session.add(SiteCheck(url="https://down.example.test", fail_nights=3, down_since=now))
    db.session.commit()

threading.Thread(target=lambda: application.run(port=PORT, use_reloader=False, threaded=True),
                 daemon=True).start()

MEASURE = """() => {
  const sc = document.getElementById('pm-scroll');
  const tiles = [...document.querySelectorAll('[data-app-tile]')].map(t => {
    const r = t.getBoundingClientRect();
    const spill = [...t.querySelectorAll('*')].filter(e => {
      const b = e.getBoundingClientRect();
      if (!b.width || !b.height || e.closest('.sr-only') || e.classList.contains('sr-only')) return false;
      return b.left < r.left - 0.5 || b.right > r.right + 0.5 || b.top < r.top - 0.5 || b.bottom > r.bottom + 0.5;
    }).map(e => e.tagName + '.' + (e.className.baseVal ?? e.className).toString().slice(0, 40));
    const small = [...t.querySelectorAll('a, button')].filter(a => {
      const b = a.getBoundingClientRect();
      if (getComputedStyle(a).display === 'none') return false;
      return b.height < 44 || b.width < (a.hasAttribute('data-app-grip') ? 20 : 44);
    }).map(a => a.textContent.trim() || a.getAttribute('title'));
    const line = t.querySelector('[data-app-line]').getBoundingClientRect();
    const versions = [...t.querySelectorAll('[data-store]')].map(v => {
      const b = v.getBoundingClientRect();
      return {state: v.dataset.store, text: v.textContent.trim(), colour: getComputedStyle(v).color,
              inside: b.left >= line.left - 0.5 && b.right <= line.right + 0.5 && b.width > 0};
    });
    const row = t.querySelector('[data-app-buttons]');
    const rb = row.getBoundingClientRect();
    [...row.children].forEach(b => {
      const x = b.getBoundingClientRect();
      if (x.width && (x.left < rb.left - 0.5 || x.right > rb.right + 0.5)) spill.push('outside its row: ' + (b.textContent.trim() || b.title));
    });
    const fit = {tile: Math.round(r.width), row: row.clientWidth, needs: row.scrollWidth,
                 buttons: [...row.children].map(b => Math.round(b.getBoundingClientRect().width))};
    const shown = e => e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0;
    const opens = {icon: shown(t.querySelector('[data-app-icon]')), button: shown(t.querySelector('[data-app-open]'))};
    return {name: t.dataset.appName, h: Math.round(r.height * 10) / 10, spill, small, versions, fit, opens,
            stores: [...t.querySelectorAll('[data-store-link]')].map(a => a.href)};
  });
  const sections = [...document.querySelectorAll('[data-group-section]')].map(sec => {
    const head = sec.querySelector('[data-group-head]').getBoundingClientRect();
    const grid = sec.querySelector('[data-group-grid]').getBoundingClientRect();
    const kids = [...sec.querySelector('[data-group-head]').children].map(k => k.getBoundingClientRect());
    return {key: sec.dataset.group, label: sec.querySelector('h2').textContent.trim(),
            top: head.top, headH: head.height, gridTop: grid.top, gridBottom: grid.bottom,
            headFits: kids.every(k => k.right <= head.right + 0.5), rule: kids[kids.length - 1].width};
  });
  const gaps = [...document.querySelectorAll('[data-group-grid]')].map(g => parseFloat(getComputedStyle(g).rowGap));
  return {tiles, sections, gaps, sideways: sc.scrollWidth - sc.clientWidth,
          window: document.documentElement.scrollHeight - innerHeight};
}"""

GREEN, RED, YELLOW = "rgb(52, 211, 153)", "rgb(248, 113, 113)", "rgb(253, 224, 71)"

with sync_playwright() as p:
    browser = p.chromium.launch()
    for width in (320, 375, 768, 1024, 1600):
        ctx = browser.new_context(viewport={"width": width, "height": 900}, color_scheme="dark")
        page = ctx.new_page()
        page.goto(BASE + "/login", wait_until="domcontentloaded")
        page.fill("[name=username]", "mb")
        page.fill("[name=password]", "password")
        page.click("button[type=submit]")
        page.wait_for_load_state("networkidle")
        page.goto(BASE + "/admin/apps/", wait_until="networkidle")
        page.wait_for_timeout(900)
        got = page.evaluate(MEASURE)
        by = {t["name"]: t for t in got["tiles"]}
        print(f"{width}px")
        base = by["Wedding Planner"]["h"]
        check(f"{width}: every tile is a plain web tile's height ({base}px)",
              all(abs(t["h"] - base) <= 0.5 for t in got["tiles"]), {t["name"]: t["h"] for t in got["tiles"]})
        check(f"{width}: nothing spills out of a tile",
              not any(t["spill"] for t in got["tiles"]), {t["name"]: (t["spill"], t["fit"]) for t in got["tiles"] if t["spill"]})
        check(f"{width}: every button keeps its 44px",
              not any(t["small"] for t in got["tiles"]), {t["name"]: t["small"] for t in got["tiles"] if t["small"]})
        check(f"{width}: every tile's icon opens its app, and Open is there wherever it fits",
              all(t["opens"]["icon"] for t in got["tiles"])
              and all(t["opens"]["button"] for t in got["tiles"] if width >= 360),
              {t["name"]: t["opens"] for t in got["tiles"]})
        check(f"{width}: the page never scrolls sideways, and the window never scrolls",
              got["sideways"] <= 0 and got["window"] <= 0, (got["sideways"], got["window"]))
        check(f"{width}: every version is on screen inside its line",
              all(v["inside"] for t in got["tiles"] for v in t["versions"]),
              {t["name"]: t["versions"] for t in got["tiles"]})
        secs = got["sections"]
        check(f"{width}: three sections in order, each with its name",
              [(x["key"], x["label"]) for x in secs] == [("client", "Live and earning"), ("building", "Building to earn"),
                                                         ("mine", "Personal projects")], secs)
        room = [secs[i]["top"] - secs[i - 1]["gridBottom"] for i in range(1, len(secs))]
        check(f"{width}: clearly apart: more room above a section than between two tiles",
              all(r >= 2 * max(got["gaps"]) for r in room), (room, got["gaps"]))
        check(f"{width}: each heading fits on its line, with its rule drawn across",
              all(x["headFits"] and x["rule"] > 20 for x in secs), secs)
        if width == 1600:
            ehq, dd, dif, rob = by["EntertainHQ"], by["Data Dungeon"], by["Differing Stores"], by[TILES[5][0]]
            check("stores that agree are green", [v["colour"] for v in ehq["versions"]] == [GREEN, GREEN], ehq["versions"])
            check("stores that differ are red", [v["colour"] for v in dif["versions"]] == [RED, RED], dif["versions"])
            check("not live is yellow, and says so", all(v["colour"] == YELLOW and v["text"].endswith("not live")
                                                          for v in dd["versions"]), dd["versions"])
            check("one live, one not: green and yellow", [v["colour"] for v in rob["versions"]] == [GREEN, YELLOW],
                  rob["versions"])
            check("a button for each live listing, none for one that is not",
                  ehq["stores"] == [APPLE, PLAY] and dd["stores"] == [] and rob["stores"] == [APPLE], (ehq["stores"], rob["stores"]))
            down = page.locator('[data-app-name="Down Site"] [data-site-down]')
            check("a site that is down turns its host red, with no pill",
                  down.count() == 1 and down.evaluate("e => getComputedStyle(e).color") == RED)
            check("no pencil anywhere", page.locator('[data-app-tile] a[href*="/edit"]').count() == 0)
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            page.screenshot(path=os.path.join(SHOTS, f"apps-{width}.png"))
        ctx.close()
    browser.close()

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
sys.exit(1 if FAIL else 0)
