# -*- coding: utf-8 -*-
"""The map notices what the repos, Railway and the books say; checklist steps
tick themselves. docs/automation_gaps.md items 18 and 20. Proves:

  18. A playbook's presence signature (proven on its fixture first) firing
      in a business's repo, with no node for that vendor on its map, is a gap
      on its blueprint; a vendor on the books and not the map is one; a
      service with no charge in 90 days is one. A gap Michael closed stays
      closed, and one whose cause went is closed by the run. A Railway custom
      domain becomes a surface once, and a node deleted afterwards is not put
      back. A surface's status follows the site check, and "Building" is
      left alone.
  20. A step with a railway or repo check is ticked when the evidence is
      there, with why in its note; a failing check never unticks a step;
      the door takes a check on a step and refuses one that cannot run.

Run: python tools/test_map_and_step_checks.py
"""
import json
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-map-steps-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, AppBlueprint, AppGap, AppLink, Business, BusinessNode, Client,  # noqa: E402
                    Expense, Playbook, PlaybookStep, Project, ProjectPlaybook, ProjectPlaybookStep,
                    RailwayService, ServiceMapping, ServiceProvider, SiteCheck)
import map_checks  # noqa: E402
import step_checks  # noqa: E402
from pm import guidance_routes  # noqa: E402

application = create_app()
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


TODAY = date(2026, 11, 4)
REPO = {
    "requirements.txt": "flask==3.0\nstripe==9.1.0\ntwilio>=8.0\n",
    "app/mail.py": "RESEND_API_KEY = os.environ['RESEND_API_KEY']\n",
    "README.md": "We might use Sentry one day.\n",
    "railway.json": '{"deploy": {"preDeployCommand": "flask db upgrade"}}\n',
}
FETCHED = []


def fetch(repo):
    FETCHED.append(repo)
    return dict(REPO), "abc1234"


SIG = r"""(?i)(^\s*{v}\s*[=<>~]|{V}_)"""

with application.app_context():
    db.create_all()
    ehq = Business(name="EntertainHQ LLC", slug="ehq", sales_source="manual")
    db.session.add(ehq)
    db.session.flush()
    pbs = {}
    for slug, name, pattern, fixture in (
            ("stripe", "Stripe", SIG.format(v="stripe", V="STRIPE"), "stripe==9.1.0"),
            ("twilio", "Twilio", SIG.format(v="twilio", V="TWILIO"), "twilio>=8.0"),
            ("resend", "Resend", SIG.format(v="resend", V="RESEND"), "resend==2.0"),
            ("sentry", "Sentry", r"(?i)(sentry[-_]sdk|SENTRY_DSN)", "sentry-sdk==2.0"),
            ("broken", "Broken", r"never-matches-anything", "the fixture it should match"),
            ("railway", "Railway", None, None),
            ("mercury", "Mercury", None, None)):
        pbs[slug] = Playbook(slug=slug, display_name=name, presence_pattern=pattern,
                             presence_globs="**/requirements*.txt, **/*.py" if pattern else None,
                             presence_fixture=fixture)
        db.session.add(pbs[slug])
    db.session.flush()
    bp = AppBlueprint(slug="entertainhq", name="EntertainHQ", business_id=ehq.id,
                      source_repos="BuiltByBean/EntertainHQ")
    db.session.add(bp)
    # The map: Stripe is on it by its runbook, Twilio by name only; Mercury
    # is a service that has gone quiet; the app is a surface.
    nodes = [
        BusinessNode(business_id=ehq.id, kind="service", playbook_id=pbs["stripe"].id),
        BusinessNode(business_id=ehq.id, kind="service", name="Twilio texting"),
        BusinessNode(business_id=ehq.id, kind="service", playbook_id=pbs["mercury"].id),
        BusinessNode(business_id=ehq.id, kind="surface", name="The app", url="https://app.entertainhq.com",
                     surface_kind="app", status=""),
        BusinessNode(business_id=ehq.id, kind="surface", name="Status", url="https://status.entertainhq.com",
                     surface_kind="status", status="building"),
    ]
    db.session.add_all(nodes)
    db.session.add_all([
        Expense(amount=43.71, description="Railway - EntertainHQ", date=TODAY - timedelta(days=20), business_id=ehq.id),
        Expense(amount=9.00, description="Mercury fee", date=TODAY - timedelta(days=200), business_id=ehq.id),
    ])
    db.session.add_all([
        RailwayService(project_ref="p-ehq", service_ref="s-web", environment="production",
                       service_name="web", project_name="EntertainHQ", repo="BuiltByBean/EntertainHQ",
                       domains_json=json.dumps(["app.entertainhq.com", "partners.entertainhq.com",
                                                "web-1.up.railway.app"]),
                       custom_domains_json=json.dumps(["app.entertainhq.com", "partners.entertainhq.com"]),
                       deploy_status="SUCCESS", deploy_commit="abc1234", branch_head="abc1234fff",
                       healthcheck_path="/healthz"),
        RailwayService(project_ref="p-ehq", service_ref="s-web", environment="staging",
                       service_name="web", project_name="EntertainHQ", repo="BuiltByBean/EntertainHQ",
                       custom_domains_json=json.dumps(["staging.entertainhq.com"])),
    ])
    db.session.add(SiteCheck(url="https://app.entertainhq.com", host="app.entertainhq.com", ok=True, fail_nights=0))
    db.session.add(SiteCheck(url="https://status.entertainhq.com", host="status.entertainhq.com", ok=False, fail_nights=3))
    db.session.commit()
    ehq_id, bp_id = ehq.id, bp.id

    print("18. THE MAP CHECKS")
    note = map_checks.run(fetch=fetch, today=TODAY)
    gaps = {g.key: g for g in AppGap.query.filter_by(blueprint_id=bp_id).all()}
    check("the blueprint's repo is the one read", FETCHED == ["BuiltByBean/EntertainHQ"], FETCHED)
    check("Resend in the code and not on the map is a gap", "map-repo-resend" in gaps
          and gaps["map-repo-resend"].status == "open" and "app/mail.py" in gaps["map-repo-resend"].detail_md, list(gaps))
    check("Stripe on the map by its runbook is not one", "map-repo-stripe" not in gaps)
    check("Twilio on the map by name only is not one", "map-repo-twilio" not in gaps)
    check("a vendor named only in a README is not a sighting", "map-repo-sentry" not in gaps)
    check("a signature that does not fire on its own fixture is never trusted", "map-repo-broken" not in gaps)
    check("Railway on the books and not on the map is a gap", "map-books-railway" in gaps, list(gaps))
    check("Mercury, quiet for 200 days, is a gap", "map-quiet-mercury" in gaps
          and "90 days" in gaps["map-quiet-mercury"].title)
    names = {n.name for n in db.session.get(Business, ehq_id).nodes}
    check("a Railway custom domain not on the map becomes a surface", "partners.entertainhq.com" in names, names)
    check("staging is not", "staging.entertainhq.com" not in names)
    check("and its memory is a closed gap", gaps.get("map-surface-partners.entertainhq.com")
          and gaps["map-surface-partners.entertainhq.com"].status == "done")
    nodes = {n.name: n for n in db.session.get(Business, ehq_id).nodes}
    check("the app's surface answers, so it is live", nodes["The app"].status == "live", nodes["The app"].status)
    check("Building is Michael's word and stays", nodes["Status"].status == "building")
    check("the run says what it did", "1 surfaces added" in note and "3 open gaps" in note, note)

    gaps["map-repo-resend"].status = "dismissed"
    db.session.delete(nodes["partners.entertainhq.com"])
    db.session.add(BusinessNode(business_id=ehq_id, kind="service", playbook_id=pbs["railway"].id))
    db.session.commit()
    map_checks.run(fetch=fetch, today=TODAY)
    gaps = {g.key: g for g in AppGap.query.filter_by(blueprint_id=bp_id).all()}
    check("a gap closed as not wanted stays closed", gaps["map-repo-resend"].status == "dismissed")
    check("a gap whose cause went is closed as done", gaps["map-books-railway"].status == "done")
    check("a surface deleted after it was added is not put back",
          "partners.entertainhq.com" not in {n.name for n in db.session.get(Business, ehq_id).nodes})

    print("\n20. STEPS THAT TICK THEMSELVES")
    client = Client(name="EHQ", email="ehq@example.test")
    db.session.add(client)
    db.session.flush()
    proj = Project(name="EntertainHQ", client_id=client.id, repo="BuiltByBean/EntertainHQ")
    db.session.add(proj)
    rail = ServiceProvider(name="railway", display_name="Railway", is_active=True)
    db.session.add(rail)
    db.session.flush()
    db.session.add(ServiceMapping(provider_id=rail.id, resource_identifier="railway:p-ehq", project_id=proj.id))
    rb = pbs["railway"]
    steps = [
        PlaybookStep(playbook_id=rb.id, position=1, title="Health check", check_kind="railway", check_target="healthcheck"),
        PlaybookStep(playbook_id=rb.id, position=2, title="Custom domain", check_kind="railway",
                     check_target="custom_domain", check_pattern=r"\.entertainhq\.com$"),
        PlaybookStep(playbook_id=rb.id, position=3, title="Pre-deploy", check_kind="railway", check_target="pre_deploy"),
        PlaybookStep(playbook_id=rb.id, position=4, title="Migrations in railway.json", check_kind="repo",
                     check_target="railway.json", check_pattern="preDeployCommand"),
        PlaybookStep(playbook_id=rb.id, position=5, title="Deploy is the head", check_kind="railway",
                     check_target="deploy_current"),
        PlaybookStep(playbook_id=rb.id, position=6, title="Ticked by hand", check_kind="railway", check_target="pre_deploy"),
        PlaybookStep(playbook_id=rb.id, position=7, title="Not checkable"),
    ]
    db.session.add_all(steps)
    applied = ProjectPlaybook(project_id=proj.id, playbook_id=rb.id)
    db.session.add(applied)
    db.session.flush()
    db.session.add(ProjectPlaybookStep(project_playbook_id=applied.id, playbook_step_id=steps[5].id,
                                       done=True, note="Michael did it"))
    db.session.commit()
    note = step_checks.run(repo_files=lambda repo: dict(REPO))
    applied = db.session.get(ProjectPlaybook, applied.id)
    done = {s.title for s in steps if s.id in applied.done_ids}
    check("a health check path on the mapped service ticks its step", "Health check" in done, done)
    check("a custom domain matching the pattern ticks its step", "Custom domain" in done)
    check("no pre-deploy command on Railway: not ticked", "Pre-deploy" not in done)
    check("the line in railway.json ticks the repo step", "Migrations in railway.json" in done)
    check("a deploy at the branch's head ticks its step", "Deploy is the head" in done)
    check("a step with no check is never touched", "Not checkable" not in done)
    row = next(p for p in applied.progress if p.playbook_step_id == steps[0].id)
    check("the note says why", row.note.startswith("Ticked by the nightly check: Railway"), row.note)
    hand = next(p for p in applied.progress if p.playbook_step_id == steps[5].id)
    check("a step ticked by hand keeps its note, and a failing check never unticks it",
          hand.done and hand.note == "Michael did it")
    check("the run says what it did", note == "5 steps checked, 4 ticked", note)

    print("\nTHE DOOR")
    got, err = guidance_routes.normalise_steps([{"title": "Domain", "check_kind": "railway",
                                                 "check_target": "custom_domain"}])
    check("a step may carry a check", err is None and got[0]["check_kind"] == "railway", (got, err))
    _, err = guidance_routes.normalise_steps([{"title": "X", "check_kind": "railway", "check_target": "vibes"}])
    check("a railway fact nobody can read is refused, naming the ones there are",
          err and "custom_domain" in err, err)
    _, err = guidance_routes.normalise_steps([{"title": "X", "check_kind": "repo", "check_target": "*.py",
                                               "check_pattern": "("}])
    check("a pattern that does not compile is refused", err and "compile" in err, err)
    check("a playbook takes a presence signature", "presence_pattern" in guidance_routes.TEXT_FIELDS["playbook"])
    check("the checklist snapshot carries the check, so a revert puts it back",
          guidance_routes.steps_snapshot(rb)[0]["check_target"] == "healthcheck")

print("\n" + ("ALL PASS" if not FAIL else str(len(FAIL)) + " FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
