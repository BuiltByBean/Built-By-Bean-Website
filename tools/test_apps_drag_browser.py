# -*- coding: utf-8 -*-
"""My Apps: a tile dragged to any place lands there, in a real browser.

Michael, 2026-11-05: "I'm trying to take one up and move it up a row into the
middle to where everything shifts properly, and it's just not working." The
old drag only knew which half a tile was dropped in and re-filed it by id.
This boots the board on a throwaway SQLite database, signs in, and drives
Chromium:

  1. At 1600 (three columns), a mouse drags the fifth tile up a row onto the
     second: while it is carried a gap stands there, the tiles after it have
     slid along, nothing paints over the carried tile, and letting go puts it
     second. One POST saves it and a reload draws the same order.
  2. At 375 (one column), a FINGER (real touch events, not a mouse) drags the
     last tile to the top, and it stays there after a reload.
  3. A tile dragged into the other half lands where it was dropped there.
  4. A tap on the grip moves nothing; the arrow keys move a tile one place.

Run: python tools/test_apps_drag_browser.py
"""
import os
import pathlib
import socket
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-drag-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["MAIL_SYNC_DISABLED"] = "1"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("  FAIL playwright is installed, so the drag was actually driven")
    sys.exit(1)

import app_icon_service  # noqa: E402
app_icon_service.fetch = lambda url: None

from app import create_app  # noqa: E402
from models import db, AppLink, User  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = free_port()
BASE = f"http://127.0.0.1:{PORT}"
MONEY = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]
MINE = ["Golf", "Hotel"]

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("password")
    db.session.add(boss)
    for n in MONEY:
        db.session.add(AppLink(name=n, url=f"https://{n.lower()}.example.test", board_group="client"))
    for n in MINE:
        db.session.add(AppLink(name=n, url=f"https://{n.lower()}.example.test", board_group="mine"))
    db.session.commit()

threading.Thread(target=lambda: application.run(port=PORT, use_reloader=False, threaded=True),
                 daemon=True).start()

ORDER = """() => [...document.querySelectorAll('[data-group-section]')].map(s =>
    [s.dataset.group, [...s.querySelectorAll('[data-app-tile]')].map(t => t.dataset.appName)])"""


def order(page):
    return {g: names for g, names in page.evaluate(ORDER)}


def grip_of(page, name):
    return page.locator(f'[data-app-tile][data-app-name="{name}"] [data-app-grip]')


def centre(page, selector):
    box = page.locator(selector).bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, box


def tile_box(page, name):
    return page.locator(f'[data-app-tile][data-app-name="{name}"]').bounding_box()


def open_board(page):
    page.goto(BASE + "/admin/apps/", wait_until="domcontentloaded")
    page.wait_for_timeout(700)


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000}, color_scheme="dark")
    page = ctx.new_page()
    page.goto(BASE + "/login", wait_until="domcontentloaded")
    page.fill("[name=username]", "mb")
    page.fill("[name=password]", "password")
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")

    print("1. Desktop: the fifth tile up a row onto the second")
    open_board(page)
    check("three columns at 1600", page.evaluate(
        "getComputedStyle(document.querySelector('[data-group-grid]')).gridTemplateColumns.split(' ').length") == 3)
    check("starting order", order(page)["client"] == MONEY, order(page))
    gx, gy, _ = centre(page, '[data-app-tile][data-app-name="Echo"] [data-app-grip]')
    bravo = tile_box(page, "Bravo")
    charlie_before = tile_box(page, "Charlie")
    page.mouse.move(gx, gy)
    page.mouse.down()
    # Into the left half of Bravo, in small steps like a hand.
    tx, ty = bravo["x"] + bravo["width"] * 0.25, bravo["y"] + bravo["height"] / 2
    for i in range(1, 21):
        page.mouse.move(gx + (tx - gx) * i / 20, gy + (ty - gy) * i / 20)
        page.wait_for_timeout(16)
    page.wait_for_timeout(400)
    mid = page.evaluate("""() => {
        const grid = document.querySelector('[data-group-section][data-group="client"] [data-group-grid]');
        const kids = [...grid.children].filter(el => !el.classList.contains('is-lifted'));
        const lifted = document.querySelector('[data-app-tile].is-lifted');
        let top = null;
        if (lifted) {
            lifted.style.pointerEvents = 'auto';
            const r = lifted.getBoundingClientRect();
            const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
            top = !!(hit && lifted.contains(hit));
            lifted.style.pointerEvents = '';
        }
        const lr = lifted && lifted.getBoundingClientRect();
        return {slot: kids.findIndex(el => el.hasAttribute('data-app-slot')),
                lifted: lifted && lifted.dataset.appName, onTop: top,
                rect: lr && {l: lr.left, t: lr.top, r: lr.right, b: lr.bottom}};
    }""")
    if os.environ.get("DRAG_SHOT"):
        page.screenshot(path=os.environ["DRAG_SHOT"])
    r = mid["rect"] or {}
    check("the carried tile stays under the pointer",
          r and r["l"] <= tx <= r["r"] and r["t"] <= ty <= r["b"], (r, tx, ty))
    check("while carried, the gap stands second", mid["slot"] == 1, mid)
    check("the carried tile is Echo", mid["lifted"] == "Echo", mid)
    check("nothing paints over the carried tile", mid["onTop"] is True, mid)
    charlie_mid = tile_box(page, "Charlie")
    check("the tiles after the gap slid along", abs(charlie_mid["x"] - charlie_before["x"]) > 50
          or abs(charlie_mid["y"] - charlie_before["y"]) > 50, (charlie_before, charlie_mid))
    with page.expect_response(lambda r: r.url.endswith("/admin/apps/order")) as resp:
        page.mouse.up()
    check("one POST saved it", resp.value.status == 200, resp.value.status)
    want = ["Alpha", "Echo", "Bravo", "Charlie", "Delta", "Foxtrot"]
    page.wait_for_timeout(300)
    check("letting go put it second", order(page)["client"] == want, order(page))
    check("no gap is left behind", page.locator("[data-app-slot]").count() == 0)
    check("the tile is back in the flow", page.evaluate(
        "() => document.querySelector('[data-app-name=\"Echo\"]').style.position") == "")
    open_board(page)
    check("a reload draws the same order", order(page)["client"] == want, order(page))

    print("2. Desktop: into the other half, between its two tiles")
    gx, gy, _ = centre(page, '[data-app-tile][data-app-name="Delta"] [data-app-grip]')
    hotel = tile_box(page, "Hotel")
    tx, ty = hotel["x"] + hotel["width"] * 0.25, hotel["y"] + hotel["height"] / 2
    page.mouse.move(gx, gy)
    page.mouse.down()
    for i in range(1, 25):
        page.mouse.move(gx + (tx - gx) * i / 24, gy + (ty - gy) * i / 24)
        page.wait_for_timeout(16)
    page.wait_for_timeout(400)
    with page.expect_response(lambda r: r.url.endswith("/admin/apps/order")):
        page.mouse.up()
    page.wait_for_timeout(300)
    check("it landed between Golf and Hotel", order(page)["mine"] == ["Golf", "Delta", "Hotel"], order(page))
    open_board(page)
    check("and stays there after a reload", order(page) == {
        "client": ["Alpha", "Echo", "Bravo", "Charlie", "Foxtrot"], "mine": ["Golf", "Delta", "Hotel"]}, order(page))

    print("3. A tap moves nothing; the arrows move one place")
    before = order(page)
    grip_of(page, "Bravo").click()
    page.wait_for_timeout(300)
    check("a tap on the grip moves nothing", order(page) == before, order(page))
    grip_of(page, "Bravo").focus()
    with page.expect_response(lambda r: r.url.endswith("/admin/apps/order")):
        page.keyboard.press("ArrowLeft")
    check("ArrowLeft moves it one place back", order(page)["client"][:3] == ["Alpha", "Bravo", "Echo"], order(page))
    open_board(page)
    check("and that is saved", order(page)["client"][:3] == ["Alpha", "Bravo", "Echo"], order(page))

    print("4. Phone: a finger drags the last tile to the top")
    phone = browser.new_context(viewport={"width": 375, "height": 760}, color_scheme="dark",
                                has_touch=True, is_mobile=True, storage_state=ctx.storage_state())
    pp = phone.new_page()
    open_board(pp)
    check("one column at 375", pp.evaluate(
        "getComputedStyle(document.querySelector('[data-group-grid]')).gridTemplateColumns.split(' ').length") == 1)
    check("nothing scrolls sideways", pp.evaluate(
        "() => { const s = document.getElementById('pm-scroll'); return s.scrollWidth <= s.clientWidth; }"))
    last = order(pp)["client"][-1]
    pp.locator(f'[data-app-tile][data-app-name="{last}"]').scroll_into_view_if_needed()
    pp.wait_for_timeout(200)
    gx, gy, _ = centre(pp, f'[data-app-tile][data-app-name="{last}"] [data-app-grip]')
    cdp = phone.new_cdp_session(pp)

    def touch(kind, x, y):
        pts = [] if kind == "touchEnd" else [{"x": x, "y": y, "id": 1}]
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": pts})

    touch("touchStart", gx, gy)
    # Up to the top edge and held there: the board scrolls itself up under
    # the finger until the first tile is in reach.
    top = pp.evaluate("document.getElementById('pm-scroll').getBoundingClientRect().top")
    for i in range(1, 21):
        touch("touchMove", gx, gy + (top + 20 - gy) * i / 20)
        pp.wait_for_timeout(16)
    for _ in range(120):
        if pp.evaluate("document.getElementById('pm-scroll').scrollTop") == 0:
            break
        pp.wait_for_timeout(30)
    first = tile_box(pp, order(pp)["client"][0])
    fx, fy = first["x"] + first["width"] / 2, first["y"] + first["height"] * 0.25
    for i in range(1, 11):
        touch("touchMove", gx, (top + 20) + (fy - top - 20) * i / 10)
        pp.wait_for_timeout(16)
    pp.wait_for_timeout(400)
    slot_at = pp.evaluate("""() => {
        const grid = document.querySelector('[data-group-section][data-group="client"] [data-group-grid]');
        return [...grid.children].filter(el => !el.classList.contains('is-lifted'))
            .findIndex(el => el.hasAttribute('data-app-slot'));
    }""")
    check("under the finger the gap is at the top", slot_at == 0, slot_at)
    with pp.expect_response(lambda r: r.url.endswith("/admin/apps/order")) as resp:
        touch("touchEnd", fx, fy)
    check("the finger's drop was saved", resp.value.status == 200)
    pp.wait_for_timeout(300)
    check("it is first", order(pp)["client"][0] == last, order(pp))
    open_board(pp)
    check("and still first after a reload", order(pp)["client"][0] == last, order(pp))
    browser.close()

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
sys.exit(1 if FAIL else 0)
