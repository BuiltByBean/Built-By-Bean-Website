# -*- coding: utf-8 -*-
"""A client's build: picked from Best Practices, and a prompt a session can take.

On 2026-11-03 a package with two items on it wrote a prompt of 1,077,939
characters, because every rule rode in whole, which nobody can hand to a
session. Michael, the same day: "when i get new client I can easily grab
features from those best practices in my mvp and spit out that prompt", with
"no price shit left over", and of the builder itself, no money at all.

This boots the board on a throwaway SQLite database with a catalogue as big as
the real one was, and proves:

  1. A prompt stays small whatever the catalogue weighs: the chosen features
     whole, the rules for their areas up to the budget, the rest one line each.
  2. A rule outside the chosen areas is named, and its body stays out.
  3. A vendor comes as what waits on the client and the checklist, with the
     whole runbook one get_playbook away.
  4. A reference project says which repo it is, and nothing names a Windows path.
  5. Nothing about money survives: not the prompt, the builder, the list, what
     the client sees, or the SOW link.
  6. A new client can be typed on the spot, and typing them twice makes one.
  7. A tap puts a feature on, a second tap takes it off, and a note for this
     client reaches the prompt.
  8. Copy reads the same text the prompt page shows.
  9. The guidance door takes no price and hands none out, and takes a category.

Run: python tools/test_mvp_prompt.py
"""
import os
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-mvp-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["GUIDANCE_API_KEY"] = "test-key"
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, Client, Feature, MvpPackage, Playbook, PlaybookStep,  # noqa: E402
                    Product, User)
from pm.mvp_routes import FULL_RULES_BUDGET, RULE_LINES_BUDGET, build_package_prompt, reference_repo  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
application.config["GUIDANCE_API_KEY"] = "test-key"
FAIL = []
AUTH = {"Authorization": "Bearer test-key"}
MONEY = re.compile(r"\$\s?\d")


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def main_of(html):
    """The page's own content, without the shell's scripts and styles."""
    body = html.split('id="pm-main"', 1)[-1]
    return re.sub(r"<script.*?</script>|<style.*?</style>", "", body, flags=re.S)


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    db.session.add(boss)
    # As heavy as the real list: 500 rules, about a megabyte, most of it in the
    # two areas every build has.
    body = "Do it this way, because of what happened last time. " * 38
    for n in range(500):
        area = ["platform", "ui", "money", "comms", "records"][n % 5] if n % 3 == 0 else ["platform", "ui"][n % 2]
        db.session.add(Feature(slug=f"rule-{n}", name=f"Rule number {n}", kind="rule", category=area,
                               summary=f"What rule {n} covers", gold_standard_md=body,
                               pitfalls_md=f"WENT-WRONG-{n}", sort_order=n))
    booking = Feature(slug="online-booking", name="Online booking", kind="feature", category="scheduling",
                      summary="Customers book a time that is actually free.",
                      gold_standard_md="HOW-TO-BOOK", pitfalls_md="BOOKING-TRAP",
                      reference_project="Talent Booker", reference_path="routes/booking.py")
    invoices = Feature(slug="invoices", name="Invoices", kind="feature", category="money",
                       summary="Numbered invoices from recorded work.", gold_standard_md="HOW-TO-INVOICE",
                       reference_project="Flipping (with Kuper Plumbing and Data Dungeon)")
    other = Feature(slug="inventory", name="Inventory", kind="feature", category="records",
                    summary="What the business owns.", gold_standard_md="NOT-PICKED-GUIDANCE")
    runbook = Playbook(slug="twilio", display_name="Twilio", one_liner="Texting that gets through",
                       client_only_md="CLIENT-SIGNS-THE-BRAND", access_grant_md="ACCESS-GRANT",
                       traps_md="TWILIO-TRAP " * 4000, your_steps_md="TWILIO-STEP " * 500)
    db.session.add_all([booking, invoices, other, runbook])
    db.session.flush()
    db.session.add(PlaybookStep(playbook_id=runbook.id, position=1, title="Register the brand",
                                client_channel="email", client_message_md="Please sign"))
    product = Product(slug="texting", name="Text messaging", summary="Texts from their own number",
                      price=1000.0, monthly_price=50.0, playbook_slug="twilio")
    client = Client(name="Acme Plumbing", email="acme@example.test")
    db.session.add_all([product, client])
    db.session.commit()
    ids = dict(boss=boss.id, booking=booking.id, invoices=invoices.id, other=other.id,
               product=product.id, client=client.id)

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True

print("Starting one")
r = c.post("/admin/mvp/new", data={"new_client": "  Brand New   Client ", "name": "Their MVP"})
check("a new client typed on the spot starts a package", r.status_code == 302, r.status_code)
with application.app_context():
    made = Client.query.filter_by(name="Brand New Client").all()
    check("and is a client now", len(made) == 1)
c.post("/admin/mvp/new", data={"new_client": "brand new client"})
with application.app_context():
    check("typed again, it is the same client", Client.query.filter(Client.name.ilike("brand new client")).count() == 1)
r = c.post("/admin/mvp/new", data={"client_id": ids["client"], "name": "Acme MVP"})
pid = int(r.headers["Location"].rstrip("/").split("/")[-1])

print("Picking")
page = c.get(f"/admin/mvp/{pid}").get_data(as_text=True)
check("the builder offers the features by area", "Online booking" in page and ">Scheduling<" in page)
check("and the products", "Text messaging" in page)
check("and the Copy button", "Copy build prompt" in page)
check("the builder shows no money", not MONEY.search(main_of(page)), MONEY.findall(main_of(page))[:3])
check("and asks for none", not re.search(r'name="(price|monthly_price|price_override|new_value)"', page))
for field, value in (("feature_id", ids["booking"]), ("feature_id", ids["invoices"]), ("feature_id", ids["other"]),
                     ("product_id", ids["product"])):
    c.post(f"/admin/mvp/{pid}/items", data={field: value})
with application.app_context():
    pack = db.session.get(MvpPackage, pid)
    check("a tap puts each on", len(pack.items) == 4, len(pack.items))
    inventory_item = next(i.id for i in pack.items if i.feature_id == ids["other"])
    booking_item = next(i.id for i in pack.items if i.feature_id == ids["booking"])
page = c.get(f"/admin/mvp/{pid}").get_data(as_text=True)
check("a picked one offers to come off from the list",
      f'/admin/mvp/{pid}/items/{inventory_item}/remove' in page)
c.post(f"/admin/mvp/{pid}/items/{inventory_item}/remove")
c.post(f"/admin/mvp/{pid}/items/{booking_item}", data={"notes": "They book by the half hour"})

with application.app_context():
    pack = db.session.get(MvpPackage, pid)
    prompt = build_package_prompt(pack)

print("The prompt")
budget = FULL_RULES_BUDGET + RULE_LINES_BUDGET + 15000
check(f"fits: {len(prompt):,} characters against a megabyte of rules", len(prompt) <= budget, len(prompt))
check("the chosen features come whole", all(x in prompt for x in ("HOW-TO-BOOK", "BOOKING-TRAP", "HOW-TO-INVOICE")))
check("what was taken off is gone", "NOT-PICKED-GUIDANCE" not in prompt)
check("this client's note reaches it", "They book by the half hour" in prompt)
check("rules for a chosen area come in full", "WENT-WRONG-" in prompt and "THE RULES FOR WHAT THIS BUILD DOES" in prompt)
check("a rule outside them is named and its body stays out",
      "[rule-1]" in prompt and "WENT-WRONG-1\n" not in prompt)
check("and how to read the whole of it is said", "get_feature_guidance" in prompt)
check("a vendor brings what waits on the client", "CLIENT-SIGNS-THE-BRAND" in prompt and "ACCESS-GRANT" in prompt)
check("and its checklist", "Register the brand  [waits on the client]" in prompt)
check("and not its whole runbook", "TWILIO-TRAP" not in prompt and "get_playbook twilio" in prompt)
check("a reference names its repo", "(BuiltByBean/Talent-Booker) - routes/booking.py" in prompt)
check("the first project named decides the repo", reference_repo("Flipping (with Kuper Plumbing and Data Dungeon)") == "BuiltByBean/Flipping")
check("no Windows path is left in it", "C:\\" not in prompt and "Documents\\Apps" not in prompt)
check("missing tools never stop a build or send anybody to a script",
      "stop and say so" not in prompt and "bootstrap_guidance" not in prompt)
check("it says how to reach the door without them",
      "https://builtbybeans.com/api/guidance" in prompt and "railway variables --kv" in prompt)
check("and what to do if that fails too", "Lessons to file" in prompt)
check("and that no command is ever handed over", "never hand me one" in prompt)
check("it holds no money", not MONEY.search(prompt), MONEY.findall(prompt)[:3])
check("and no heading for any", "THE NUMBERS" not in prompt and "Quoted at" not in prompt)

print("Copy")
r = c.get(f"/admin/mvp/{pid}/prompt.txt")
check("the text route answers plain text", r.status_code == 200 and r.mimetype == "text/plain", r.mimetype)
check("the same text", r.get_data(as_text=True) == prompt)
check("and is not stored by anything between", "no-store" in r.headers.get("Cache-Control", ""), r.headers.get("Cache-Control"))
page = c.get(f"/admin/mvp/{pid}/prompt").get_data(as_text=True)
check("the prompt page draws it", "HOW-TO-BOOK" in page)

print("Everywhere else")
listing = c.get("/admin/mvp/").get_data(as_text=True)
check("the list of packages shows no money", not MONEY.search(main_of(listing)))
seen = c.get(f"/admin/mvp/{pid}/summary").get_data(as_text=True)
check("what the client sees lists what they get, in the words typed for them",
      "Online booking" in seen and "They book by the half hour" in seen)
check("and the summary where nothing was typed", "Numbered invoices from recorded work." in seen)
check("and shows no money", not MONEY.search(seen) and "What it costs" not in seen)
r = c.get(f"/admin/mvp/{pid}/sow")
check("the SOW opens with the scope and no price", r.status_code == 302 and "project_name=" in r.headers["Location"]
      and "mvp_price" not in r.headers["Location"], r.headers.get("Location"))
for url in ("/admin/features/", "/admin/practices/"):
    page = c.get(url).get_data(as_text=True)
    check(f"{url} asks for and shows no price", "typical_value" not in page and "Worth $" not in page
          and not MONEY.search(main_of(page)))

print("The door")
got = c.get("/api/guidance/products", headers=AUTH).get_json()["products"][0]
check("hands out no price", "price" not in got and "monthly_price" not in got, got)
r = c.post("/api/guidance/proposals", headers=AUTH, json={
    "kind": "product", "slug": "texting", "field": "price", "mode": "replace", "text": "5", "project": "t", "reason": "t"})
check("refuses to set one", r.status_code == 400, r.get_json())
r = c.post("/api/guidance/proposals", headers=AUTH, json={
    "kind": "feature", "slug": "invoices", "field": "typical_value", "mode": "replace", "text": "5", "project": "t", "reason": "t"})
check("on a feature too", r.status_code == 400, r.get_json())
r = c.post("/api/guidance/proposals", headers=AUTH, json={
    "kind": "feature", "slug": "invoices", "field": "category", "mode": "replace", "text": "comms", "project": "t", "reason": "t"})
with application.app_context():
    check("takes a category", r.status_code == 200 and Feature.query.filter_by(slug="invoices").one().category == "comms", r.get_json())
r = c.post("/api/guidance/proposals", headers=AUTH, json={
    "kind": "feature", "slug": "invoices", "field": "category", "mode": "replace", "text": "nonsense", "project": "t", "reason": "t"})
check("but only a real one", r.status_code == 400, r.get_json())

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
sys.exit(1 if FAIL else 0)
