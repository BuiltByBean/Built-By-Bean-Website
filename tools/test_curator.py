# -*- coding: utf-8 -*-
"""Best Practices tends itself: nothing waits on a yes.

Michael, 2026-11-02: "stop this waiting on a yes thing. Just have it adjust
properly over time ... add new, delete or prune ... based on my core
projects' repos." This proves the parts that would quietly come apart:

  1. The door applies everything on arrival, a rewrite and a retire
     included, and each one still reverts exactly.
  2. A held change is a curator NOTE: not applied, not in any brief.
  3. The sweeper reads core repos only, files new AND changed sections, and
     a heading recorded before fingerprints existed is fingerprinted
     silently instead of flooding the curator.
  4. One night of the curator, against a scripted model: notes become a
     rule, an addition, an applied change, or nothing; the plan merges,
     tightens and retires; a slug the model invents or names twice is
     ignored; a merge keeps the absorbed rule's scanner; every change is
     on History and a retire reverts.
  5. No ANTHROPIC_API_KEY is a recorded skip, not a crash.
  6. The session-start brief fits the context a hook keeps, even at 485
     long rules, and ?full=1 is still every rule in full.
  7. History lists the curator's nights and the changes, and has no Accept.

Run: python tools/test_curator.py
"""
import json
import os
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-curator-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["GUIDANCE_API_KEY"] = "test-key"
os.environ.pop("ANTHROPIC_API_KEY", None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, CatalogueProposal, CuratorRun, Feature, RepoWatch,  # noqa: E402
                    User)
import curate_practices  # noqa: E402
import sweep_repos  # noqa: E402
from pm import guidance_routes  # noqa: E402
from pm.guidance_routes import _propose, revert_proposal, rules_index  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def rule(slug, name, **kw):
    return Feature(slug=slug, name=name, kind="rule", category="ui",
                   summary=kw.pop("summary", name), gold_standard_md=kw.pop("gold", "Do it right."),
                   pitfalls_md=kw.pop("traps", "It went wrong once."), **kw)


auth = {"Authorization": "Bearer test-key"}

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    db.session.add_all([
        boss,
        rule("commas", "Numbers wear their commas"),
        rule("thousands", "Thousands separators on figures"),
        rule("comma-totals", "Totals use commas", check_pattern=r"\{\{ *total *\}\}",
             check_globs="templates/**/*.html"),
        rule("wordy", "A wordy rule", traps="x" * 9000),
        rule("old-vendor", "Fax machine setup"),
        rule("em-dash", "No em dashes"),
        Feature(slug="texting", name="Text messaging", kind="feature", category="comms"),
    ])
    db.session.commit()
    boss_id = boss.id
    web = application.test_client()

    print("1. Everything applies on arrival")
    r = web.post("/api/guidance/proposals", headers=auth, json={
        "kind": "rule", "slug": "em-dash", "field": "summary", "mode": "replace",
        "text": "Never an em dash, anywhere.", "project": "Talent Booker"})
    body = r.get_json()
    check("a replace answers applied", r.status_code == 200 and body.get("action") == "applied", body)
    check("and the rule reads the new words",
          Feature.query.filter_by(slug="em-dash").one().summary == "Never an em dash, anywhere.")
    p = db.session.get(CatalogueProposal, body["id"])
    check("revert puts the old words back",
          revert_proposal(p)[0] and Feature.query.filter_by(slug="em-dash").one().summary == "No em dashes")
    p.status = "reverted"
    db.session.commit()

    r = web.post("/api/guidance/proposals", headers=auth, json={
        "kind": "rule", "slug": "old-vendor", "mode": "retire",
        "reason": "Nobody faxes", "project": "Data Dungeon"})
    body = r.get_json()
    check("a retire answers applied", body.get("action") == "applied", body)
    check("and switches the rule off", not Feature.query.filter_by(slug="old-vendor").one().is_active)
    p = db.session.get(CatalogueProposal, body["id"])
    revert_proposal(p)
    p.status = "reverted"
    db.session.commit()
    check("revert switches it back on", Feature.query.filter_by(slug="old-vendor").one().is_active)

    print("2. A held change is a note for the curator")
    result, status = _propose(kind="rule", slug="", field="*", mode="create", text="",
                              reason="New in x", project="BuiltByBean/X (swept)",
                              payload={"name": "Swept heading", "what_went_wrong": "body " * 40},
                              hold=True)
    check("it is filed as a candidate", result.get("action") == "candidate", result)
    check("no rule was made", Feature.query.filter_by(name="Swept heading").first() is None)
    check("and nothing on it reaches the brief", "Swept heading" not in rules_index())

    print("3. The sweeper: core repos, new and changed sections")
    check("a push last week is core", sweep_repos._recent("2026-10-30T10:00:00Z", days=100000))
    check("a push two years ago is not", not sweep_repos._recent("2020-01-01T00:00:00Z", days=120))
    files = {"BuiltByBean/App": "## Phone first\n" + "Design at 375px. " * 20
                                + "\n## Totals\n" + "Use commas. " * 20}
    filed = []

    def fake_propose(**kw):
        filed.append(kw["payload"]["name"] + "|" + kw["reason"])
        return {"action": "candidate"}, 200

    def fetch(name):
        return str(hash(files[name])), files[name]

    sweep_repos.sweep(application, fake_propose, repos=["BuiltByBean/App"], fetch=fetch)
    check("the first read only records", filed == [], filed)
    files["BuiltByBean/App"] += "\n## Dark mode\n" + "Never flash white. " * 20
    sweep_repos.sweep(application, fake_propose, repos=["BuiltByBean/App"], fetch=fetch)
    check("a new section is filed", filed == ["Dark mode|New in the CLAUDE.md of BuiltByBean/App"], filed)
    filed.clear()
    files["BuiltByBean/App"] = files["BuiltByBean/App"].replace("Use commas. ", "Use commas, always. ")
    sweep_repos.sweep(application, fake_propose, repos=["BuiltByBean/App"], fetch=fetch)
    check("a changed section is filed", filed == ["Totals|Changed in the CLAUDE.md of BuiltByBean/App"], filed)
    filed.clear()
    sweep_repos.sweep(application, fake_propose, repos=["BuiltByBean/App"],
                      fetch=lambda n: ("other-sha", files[n]))
    check("an unchanged file files nothing", filed == [], filed)
    watch = RepoWatch.query.filter_by(repo="BuiltByBean/App").one()
    watch.seen_json = json.dumps(["phone-first", "totals", "dark-mode"])
    watch.last_sha = "legacy"
    db.session.commit()
    sweep_repos.sweep(application, fake_propose, repos=["BuiltByBean/App"], fetch=fetch)
    check("a list from before fingerprints is fingerprinted silently", filed == [], filed)
    check("and stored as fingerprints", isinstance(json.loads(RepoWatch.query.filter_by(
        repo="BuiltByBean/App").one().seen_json), dict))

    print("4. One night of the curator")
    # The notes it will read: the swept one from section 2, a replace on a
    # rule, and two more swept sections.
    replace_note = CatalogueProposal(kind="rule", target_slug="em-dash", field="gold_standard_md",
                                     mode="replace", proposed="Use a comma or a full stop.",
                                     project="Kuper Plumbing", status="candidate")
    db.session.add_all([
        replace_note,
        CatalogueProposal(kind="rule", field="*", mode="create", status="candidate",
                          project="BuiltByBean/App (swept)",
                          payload_json=json.dumps({"name": "Dark mode", "what_went_wrong": "Never flash white."})),
        CatalogueProposal(kind="rule", field="*", mode="create", status="candidate",
                          project="BuiltByBean/App (swept)",
                          payload_json=json.dumps({"name": "Our Twilio number", "what_went_wrong": "It is 555."})),
    ])
    db.session.commit()
    # A rewrite held for days, and a session's lesson arriving after it on the
    # same field: applying the old one as proposed would delete the lesson.
    stale_note = CatalogueProposal(kind="rule", target_slug="em-dash", field="pitfalls_md",
                                   mode="replace", proposed="A rewrite from three days ago.",
                                   project="Kuper Plumbing", status="candidate")
    db.session.add(stale_note)
    db.session.commit()
    result, _ = _propose(kind="rule", slug="em-dash", field="pitfalls_md", mode="append",
                         text="A lesson filed after the rewrite.", reason="found today",
                         project="Kuper Plumbing")
    check("the later lesson went straight in", result.get("action") == "applied", result)
    notes = {CatalogueProposal.query.filter_by(status="candidate").filter(
        CatalogueProposal.payload_json.contains(n)).first().id: n
        for n in ("Swept heading", "Dark mode", "Our Twilio number")}
    ids = {v: k for k, v in notes.items()}

    def blank(**kw):
        base = {"slug": "", "name": "", "summary": "", "category": "ui",
                "how_to_build": "", "what_went_wrong": "", "why": "because"}
        base.update(kw)
        return base

    SCRIPT = {
        "notes": {"decisions": [
            blank(id=ids["Swept heading"], action="add_to", slug="commas",
                  what_went_wrong="A total read 1234567 on a phone."),
            blank(id=ids["Dark mode"], action="create", name="Dark that never flashes white",
                  summary="Paint dark before the first frame", how_to_build="Set the colour on html.",
                  what_went_wrong="A white flash on every load."),
            blank(id=ids["Our Twilio number"], action="discard", why="Only true of one repo"),
            blank(id=replace_note.id, action="apply"),
            blank(id=stale_note.id, action="apply"),
            blank(id=999999, action="create", name="Invented"),
        ]},
        "plan": {
            "merges": [{"keep": "commas", "absorb": ["thousands", "comma-totals", "ghost"], "why": "Same rule"},
                       {"keep": "wordy", "absorb": ["commas"], "why": "named twice"}],
            "tighten": [{"slug": "wordy", "why": "Too long"}],
            "retire": [{"slug": "old-vendor", "why": "One vendor, long gone"},
                       {"slug": "nope", "why": "invented"}],
        },
    }
    prompts = []

    class Block:
        type = "text"

        def __init__(self, text):
            self.text = text

    class Usage:
        input_tokens, output_tokens = 1000, 200
        cache_read_input_tokens = cache_creation_input_tokens = 0

    class Message:
        stop_reason = "end_turn"
        usage = Usage()

        def __init__(self, data):
            self.content = [Block(json.dumps(data))]

    class Stream:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return Message(self.data)

    class Messages:
        def stream(self, **kw):
            text = kw["messages"][0]["content"]
            prompts.append((text, kw))
            if "THE NOTES" in text:
                return Stream(SCRIPT["notes"])
            if "Read the whole list" in text:
                return Stream(SCRIPT["plan"])
            slugs = re.findall(r"(?:MERGE into|TIGHTEN) \[([a-z0-9-]+)\]", text)
            return Stream({"rules": [
                {"slug": s, "name": "Numbers wear their commas" if s == "commas" else "A short rule",
                 "summary": "Every figure over 999 is grouped", "gold_standard_md": "Run figures through the commas filter.",
                 "pitfalls_md": "A total read 1234567 on a phone."} for s in slugs] + [
                {"slug": "invented", "name": "x", "summary": "x", "gold_standard_md": "x", "pitfalls_md": "x"}]})

    class Beta:
        messages = Messages()

    class FakeClient:
        beta = Beta()

    run = db.session.get(CuratorRun, curate_practices.curate(application, client=FakeClient()))
    check("the run finished ok", run.status == "ok", (run.status, run.note))
    check("the model asked for is Opus with fallbacks and JSON",
          prompts and prompts[0][1]["model"] == curate_practices.MODEL
          and prompts[0][1]["fallbacks"] == "default"
          and prompts[0][1]["output_config"]["format"]["type"] == "json_schema")
    check("a note became a new rule written for any project",
          Feature.query.filter_by(name="Dark that never flashes white", is_active=True).first() is not None)
    check("a note was folded into the rule it belongs to",
          "1234567" in Feature.query.filter_by(slug="commas").one().pitfalls_md)
    check("a repo-only note was set aside",
          db.session.get(CatalogueProposal, ids["Our Twilio number"]).status == "discarded")
    check("a proposed rewrite was applied as proposed",
          Feature.query.filter_by(slug="em-dash").one().gold_standard_md == "Use a comma or a full stop.")
    db.session.refresh(stale_note)  # the night ran in its own session
    check("a rewrite the field has moved past is set aside, whatever the model says",
          stale_note.status == "discarded" and "changed since" in stale_note.reason,
          (stale_note.status, stale_note.reason))
    check("and what arrived after it is still there",
          "A lesson filed after the rewrite." in Feature.query.filter_by(slug="em-dash").one().pitfalls_md
          and "three days ago" not in Feature.query.filter_by(slug="em-dash").one().pitfalls_md)
    check("and the model was never asked about it",
          not any("three days ago" in text for text, _ in prompts if "THE NOTES" in text))
    check("no note is left waiting", CatalogueProposal.query.filter_by(status="candidate").count() == 0,
          CatalogueProposal.query.filter_by(status="candidate").count())
    check("a merge retires what it absorbed",
          not Feature.query.filter_by(slug="thousands").one().is_active
          and not Feature.query.filter_by(slug="comma-totals").one().is_active)
    check("and the survivor carries the merged text",
          Feature.query.filter_by(slug="commas").one().gold_standard_md == "Run figures through the commas filter.")
    check("and the absorbed rule's scanner",
          Feature.query.filter_by(slug="commas").one().check_pattern == r"\{\{ *total *\}\}")
    check("a slug named in two actions is used once (wordy only tightened)",
          Feature.query.filter_by(slug="wordy").one().is_active
          and len(Feature.query.filter_by(slug="wordy").one().pitfalls_md) < 100)
    check("a retirement switches the rule off", not Feature.query.filter_by(slug="old-vendor").one().is_active)
    check("invented slugs changed nothing", Feature.query.filter_by(name="Invented").first() is None
          and Feature.query.filter_by(slug="invented").first() is None)
    check("the night's counts", (run.added, run.folded, run.merged, run.tightened, run.retired, run.discarded)
          == (1, 2, 1, 1, 1, 2), (run.added, run.folded, run.merged, run.tightened, run.retired, run.discarded))
    check("rules before and after", (run.rules_before, run.rules_after) == (6, 4),
          (run.rules_before, run.rules_after))
    retired = CatalogueProposal.query.filter_by(target_slug="old-vendor", mode="retire",
                                                status="applied").first()
    check("every change is attributed to the curator", retired is not None and retired.project == "curator")
    revert_proposal(retired)
    db.session.commit()
    check("and a curator retire reverts", Feature.query.filter_by(slug="old-vendor").one().is_active)

    print("5. No key is a recorded skip")
    skipped = curate_practices.curate(application)
    check("status skipped", db.session.get(CuratorRun, skipped).status == "skipped")

    print("6. The brief fits what a session start keeps")
    for i in range(485):
        db.session.add(rule(f"r{i:03}", f"A long rule name number {i} about something",
                            summary="A summary that runs on for a while " * 4, traps="t" * 2000))
    db.session.commit()
    index = rules_index()
    check("the index is inside the budget", len(index) <= guidance_routes.INDEX_BUDGET, len(index))
    check("and says how many it left off", "more. get_feature_guidance" in index)
    full = web.get("/api/guidance/brief?full=1", headers=auth).get_data(as_text=True)
    check("?full=1 is still every rule in full", len(full) > 485 * 2000 and "r484" in full, len(full))
    check("the plain brief is the index", web.get("/api/guidance/brief", headers=auth)
          .get_data(as_text=True) == index)


print("7. History")
signed = application.test_client()
with signed.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True
resp = signed.get("/admin/features/inbox/")
page = resp.get_data(as_text=True)
check("it renders with History lit",
      re.search(r'aria-current="page"[^>]*>\s*History', page) is not None)
check("it lists the curator's nights", "The curator&#39;s nights" in page or "The curator's nights" in page)
check("it shows the skip honestly", "No key" in page)
check("it has no Accept", ">\n                Accept<" not in page and "inbox.accept" not in page
      and "/accept" not in page)
check("the curator's merge is listed with a Revert",
      "Merged into commas" in page and "/revert" in page)
check("no em dashes", "\u2014" not in page)
everything = signed.get("/admin/practices/").get_data(as_text=True)
check("Everything has no waiting banner", "waiting on your yes" not in everything)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
