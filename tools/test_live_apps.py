# -*- coding: utf-8 -*-
"""What is live, read nightly: Railway, sites, domains, deploys, stores, tiles.

docs/automation_gaps.md items 7, 9, 19, 4 (store versions) and the smaller
ones (tile text and icons, Railway bills from mail). Proves:

  7.  The Railway read parses the answer Railway really gives (its shape was
      read live on 2026-11-04), writes a ServiceMapping and a tile's
      railway_url only on a single unambiguous match and only into an empty
      field, and lists what is live with no tile, leaving out databases,
      services marked "Not an app" and anything a tile already is.
  9.  A site down one night is not a row and two nights is; a certificate
      under 14 days, a domain under 30 days that does not renew itself, a
      crashed deploy and a deploy a day behind its branch are each a row.
  19. The version in the repo is read from gradle, the Xcode project and
      Expo, and the tile says "1.4.0 in the repo, stores on 1.3.2".
  4.  Store versions that differ for over a day are a row; for an hour, not.
  -   An empty tile description fills from the repo, a typed one never
      changes; a fetched icon is fetched again monthly, an uploaded one
      never. A Railway receipt in the mailbox records its month for an
      account with no token, and never overwrites a typed bill.

Run: python tools/test_live_apps.py
"""
import json
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-live-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, AppLink, Client, Project, ServiceProvider, ServiceMapping,  # noqa: E402
                    RailwayService, SiteCheck, DomainWatch, ProviderInvoice, Receipt,
                    ReceiptMailbox, Business, User)
import railway_watch  # noqa: E402
import live_watch  # noqa: E402
import store_ids_service  # noqa: E402
import store_versions_service  # noqa: E402
import tile_upkeep  # noqa: E402
import railway_mail  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def instance(env, repo=None, image=None, service=(), custom=(), status="SUCCESS", commit=None,
             branch="main", health=None, pre=None):
    meta = {"serviceManifest": {"deploy": {"healthcheckPath": health, "preDeployCommand": pre}}}
    if commit:
        meta.update(commitHash=commit, branch=branch)
    return {"node": {"environmentId": env, "source": {"repo": repo, "image": image},
                     "domains": {"serviceDomains": [{"domain": d} for d in service],
                                 "customDomains": [{"domain": d} for d in custom]},
                     "latestDeployment": {"status": status, "createdAt": "2026-11-03T10:00:00.000Z",
                                          "meta": meta}}}


def project(pid, name, services, envs=(("env-prod", "production"),)):
    return {"node": {"id": pid, "name": name,
                     "environments": {"edges": [{"node": {"id": i, "name": n}} for i, n in envs]},
                     "services": {"edges": [{"node": {"id": sid, "name": sname,
                                                       "serviceInstances": {"edges": insts}}}
                                            for sid, sname, insts in services]}}}


# The shape Railway answered on 2026-11-04, trimmed to the cases that matter.
WORKSPACE = {"projects": {"edges": [
    project("p-kuper", "Kuper Plumbing", [
        ("s-kuper-web", "web", [instance("env-prod", repo="BuiltByBean/KuperPlumbing",
                                         service=["web-production-8b56c.up.railway.app"],
                                         custom=["kuperplumbing.com"], commit="3533f3b5aaaa",
                                         health="/healthz", pre="flask db upgrade")]),
        ("s-kuper-db", "Postgres", [instance("env-prod", image="ghcr.io/railwayapp-templates/postgres-ssl:18")]),
    ]),
    project("p-ehq", "EntertainHQ", [
        ("s-ehq-web", "web", [instance("env-prod", repo="BuiltByBean/EntertainHQ",
                                       service=["web-production-3449c.up.railway.app"],
                                       custom=["app.entertainhq.com", "*.entertainhq.com"],
                                       commit="6864589aaaaa"),
                              instance("env-stage", repo="BuiltByBean/EntertainHQ",
                                       service=["web-staging-3002.up.railway.app"],
                                       commit="fb36cec5aaaa", branch="staging")]),
    ], envs=(("env-prod", "production"), ("env-stage", "staging"))),
    project("p-rob", "Robinson & Co.", [
        ("s-rob-web", "Robinson-Co", [instance("env-prod", repo="BuiltByBean/Robinson-Co.",
                                               custom=["admin.robinsonandcodesign.com"], commit="43c1127d")]),
        ("s-rob-sweep", "Robinson-Co-sweep", [instance("env-prod", repo="BuiltByBean/Robinson-Co.",
                                                       status="CRASHED", commit="43c1127d")]),
    ]),
    project("p-ideas", "ideas", [
        ("s-ideas", "web", [instance("env-prod", repo="BuiltByBean/Ideas",
                                     service=["web-production-b01419.up.railway.app"], commit="2547e80d")]),
    ]),
    project("p-twin", "Twin Build", [
        ("s-twin", "web", [instance("env-prod", repo="BuiltByBean/Twin",
                                    service=["twin-production.up.railway.app"])]),
    ]),
]}}

print("7. THE RAILWAY READ")
rows = railway_watch.parse_workspace(WORKSPACE)
by = {(r["service_ref"], r["environment"]): r for r in rows}
check("one row per service per environment", len(rows) == 8, len(rows))
ehq = by[("s-ehq-web", "production")]
check("a wildcard domain is a routing rule, not an address", "*.entertainhq.com" not in ehq["domains"], ehq["domains"])
check("custom domains come first", ehq["domains"][0] == "app.entertainhq.com", ehq["domains"])
check("staging is its own row with its own branch",
      by[("s-ehq-web", "staging")]["deploy_branch"] == "staging")
kuper = by[("s-kuper-web", "production")]
check("the health check and pre-deploy are read off the manifest",
      kuper["healthcheck_path"] == "/healthz" and kuper["pre_deploy"] == "flask db upgrade")
check("repo names and hosts normalise",
      railway_watch.norm_repo("https://github.com/BuiltByBean/KuperPlumbing.git") == "builtbybean/kuperplumbing"
      and railway_watch.host_of("https://www.KuperPlumbing.com/x") == "kuperplumbing.com")

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    db.session.add(boss)
    bbb = Business(name="Built by Bean LLC", slug="bbb", sales_source="board")
    db.session.add(bbb)
    rail = ServiceProvider(name="railway", display_name="Railway", is_active=True,
                           credentials_json=json.dumps({"workspace_id": "ws-1", "api_token": "t"}))
    db.session.add(rail)
    db.session.flush()
    k_client = Client(name="Cason Kuper", email="cason@example.test")
    r_client = Client(name="Robinson", email="rob@example.test")
    t_client = Client(name="Twin Co", email="twin@example.test")
    db.session.add_all([k_client, r_client, t_client])
    db.session.flush()
    kuper_p = Project(name="Kuper Plumbing", client_id=k_client.id, hosting_fee=50.0, hosting_cycle="monthly")
    rob_p = Project(name="Robinson site", client_id=r_client.id, hosting_fee=0.0)
    twin_a = Project(name="Twin A", client_id=t_client.id, repo="BuiltByBean/Twin")
    twin_b = Project(name="Twin B", client_id=t_client.id, repo="BuiltByBean/Twin")
    db.session.add_all([kuper_p, rob_p, twin_a, twin_b])
    db.session.flush()
    # Kuper is known by its tile; Robinson's Railway project is already
    # mapped by hand to a client and no project (filled); Twin's repo is two
    # projects (left alone).
    kuper_tile = AppLink(name="Kuper", url="https://kuperplumbing.com", project_id=kuper_p.id)
    rob_tile = AppLink(name="Robinson", url="https://admin.robinsonandcodesign.com",
                       railway_url="https://typed.example/railway", project_id=rob_p.id)
    ehq_tile = AppLink(name="EntertainHQ", url="https://app.entertainhq.com")
    db.session.add_all([kuper_tile, rob_tile, ehq_tile])
    db.session.add(ServiceMapping(provider_id=rail.id, resource_identifier="railway:p-rob",
                                  resource_label="Robinson & Co.", client_id=r_client.id))
    db.session.commit()
    ids = dict(boss=boss.id, rail=rail.id, kuper_p=kuper_p.id, rob_p=rob_p.id, kuper_tile=kuper_tile.id,
               rob_tile=rob_tile.id, ehq_tile=ehq_tile.id, bbb=bbb.id)

    calls = []
    railway_watch.run(gql=lambda token, q, v: calls.append(v) or {"workspace": WORKSPACE},
                      get=lambda path: {"sha": "zzzz9999", "commit": {"committer": {"date": "2026-11-01T00:00:00Z"}}})
    check("the workspace named on the provider is the one read", calls == [{"w": "ws-1"}], calls)
    m = ServiceMapping.query.filter_by(resource_identifier="railway:p-kuper").all()
    check("Kuper's Railway project maps itself to its one board project, by its tile",
          len(m) == 1 and m[0].project_id == ids["kuper_p"] and m[0].client_id == k_client.id,
          [(x.project_id, x.client_id) for x in m])
    r = ServiceMapping.query.filter_by(resource_identifier="railway:p-rob").one()
    check("a mapping with a client and no project gets its project, nothing else written",
          r.project_id == ids["rob_p"] and ServiceMapping.query.filter_by(resource_identifier="railway:p-rob").count() == 1)
    check("two board projects on one repo is a guess, and nothing is written",
          ServiceMapping.query.filter_by(resource_identifier="railway:p-twin").count() == 0)
    kt = db.session.get(AppLink, ids["kuper_tile"])
    check("an empty railway_url is filled from the one service",
          kt.railway_url == "https://railway.com/project/p-kuper/service/s-kuper-web", kt.railway_url)
    check("and the empty repo with it", kt.github_url == "https://github.com/BuiltByBean/KuperPlumbing")
    check("a typed railway_url is never overwritten",
          db.session.get(AppLink, ids["rob_tile"]).railway_url == "https://typed.example/railway")
    check("EntertainHQ's tile matches production, not staging",
          "s-ehq-web" in (db.session.get(AppLink, ids["ehq_tile"]).railway_url or ""))

    loose = [(s.project_name, s.service_name) for s in railway_watch.unlisted()]
    check("live with no tile: ideas and Twin, and nothing else", sorted(loose) == [("Twin Build", "web"), ("ideas", "web")], loose)
    check("the database and the cron with no address are never listed",
          not any(n in ("Postgres", "Robinson-Co-sweep") for _, n in loose))

    probs = {(p["service"].service_name, p["kind"]) for p in railway_watch.deploy_problems(
        now=datetime(2026, 11, 4, 12))}
    check("a crashed production deploy is a problem", ("Robinson-Co-sweep", "broken") in probs, probs)
    check("a deploy a day behind its branch's head is a problem", ("web", "behind") in probs, probs)
    staging = RailwayService.query.filter_by(service_ref="s-ehq-web", environment="staging").one()
    check("staging is never one", not any(p["service"].id == staging.id for p in railway_watch.deploy_problems()))
    ideas = RailwayService.query.filter_by(service_ref="s-ideas").one()
    ideas.branch_head, ideas.branch_head_at = "2547e80dffff", datetime(2026, 11, 1)
    db.session.commit()
    check("a deploy at the branch's head is not behind", not railway_watch.is_behind(ideas, datetime(2026, 11, 4)))
    ideas.branch_head, ideas.branch_head_at = "abcdef", datetime(2026, 11, 4, 6)
    check("a new commit gets a day before it counts", not railway_watch.is_behind(ideas, datetime(2026, 11, 4, 12)))

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True

page = c.get("/admin/apps/railway").data.decode("utf-8", "replace")
check("the list page names them", "ideas" in page and "Twin Build" in page and "Put it on My Apps" in page)
with application.app_context():
    twin = RailwayService.query.filter_by(service_ref="s-twin").one()
    ideas_id = RailwayService.query.filter_by(service_ref="s-ideas").one().id
    twin_id = twin.id
c.post(f"/admin/apps/railway/{twin_id}/ignore")
with application.app_context():
    check("Not an app takes it off the list", [s.service_name for s in railway_watch.unlisted()] == ["web"]
          and railway_watch.unlisted()[0].id == ideas_id)
import app_icon_service  # noqa: E402
app_icon_service.fetch = lambda url: None
r = c.post(f"/admin/apps/railway/{ideas_id}/add")
with application.app_context():
    made = AppLink.query.filter_by(name="ideas").first()
    check("Put it on My Apps makes the tile in one press, with its Railway and repo links",
          made is not None and made.url == "https://web-production-b01419.up.railway.app"
          and made.railway_url.endswith("/service/s-ideas") and made.github_url.endswith("BuiltByBean/Ideas"),
          made and (made.url, made.railway_url, made.github_url))
    check("and then nothing is left on the list", railway_watch.unlisted() == [])
check("and opens it to check", r.status_code == 302 and "/edit" in r.headers.get("Location", ""))

print("\n9. SITES, CERTIFICATES, DOMAINS")


class Resp:
    def __init__(self, code, url):
        self.status_code, self.url = code, url

    def close(self):
        pass


check("a 200 is up", live_watch.probe("https://a.test", get=lambda u: Resp(200, u), cert=lambda h: None)["ok"])
check("a login wall (403) is a server that answered",
      live_watch.probe("https://a.test", get=lambda u: Resp(403, u), cert=lambda h: None)["ok"])
down = live_watch.probe("https://a.test", get=lambda u: Resp(503, u), cert=lambda h: None)
check("a 503 is down, with why", not down["ok"] and down["error"] == "HTTP 503", down)


def refuse(u):
    import requests
    raise requests.ConnectionError("refused")


gone = live_watch.probe("https://a.test", get=refuse, cert=lambda h: None)
check("no answer at all is down", not gone["ok"] and "ConnectionError" in gone["error"], gone)
check("the certificate's date is read off the host it ended up on",
      live_watch.probe("https://a.test", get=lambda u: Resp(200, "https://b.test/x"),
                       cert=lambda h: date(2026, 11, 10) if h == "b.test" else None)["cert_expires_on"] == date(2026, 11, 10))
check("registrable domains: a subdomain, a country code, a platform host",
      live_watch.registrable("app.entertainhq.com") == "entertainhq.com"
      and live_watch.registrable("shop.example.co.uk") == "example.co.uk"
      and live_watch.registrable("web-production-1.up.railway.app") is None)

with application.app_context():
    t0 = datetime(2026, 11, 3, 13)
    live_watch.record("https://kuperplumbing.com", down, t0)
    db.session.commit()
    live_watch._CACHE["rows"] = None
    keys = {r["key"].split(":")[0] for r in live_watch.attention_rows(force=True, today=date(2026, 11, 4), now=t0)}
    check("one bad night is not a row", "down" not in keys, keys)
    live_watch.record("https://kuperplumbing.com", down, t0 + timedelta(days=1))
    db.session.commit()
    rows = live_watch.attention_rows(force=True, today=date(2026, 11, 4), now=t0)
    downs = [r for r in rows if r["key"].startswith("down:")]
    check("two nights running is a row, saying since when", len(downs) == 1 and "since Nov 3" in downs[0]["detail"],
          downs)
    live_watch.record("https://kuperplumbing.com", {"status_code": 200, "ok": True, "final_url": "https://kuperplumbing.com",
                                                    "error": None, "cert_expires_on": date(2026, 11, 12)})
    db.session.commit()
    sc = SiteCheck.query.filter_by(url="https://kuperplumbing.com").one()
    check("an answer clears the count and the date", sc.fail_nights == 0 and sc.down_since is None)
    rows = live_watch.attention_rows(force=True, today=date(2026, 11, 4), now=t0)
    check("a certificate with 8 days left is a row", any(r["key"].startswith("cert:") and "8 days" in r["detail"] for r in rows),
          [r["detail"] for r in rows])

    def cf(url, headers):
        return {"success": True, "result": [{"name": "kuperplumbing.com", "expires_at": "2026-11-20T00:00:00Z", "auto_renew": False},
                                            {"name": "entertainhq.com", "expires_at": "2026-11-21", "auto_renew": True}]}

    class R:
        status_code = 200

        def json(self):
            return {"events": [{"eventAction": "expiration", "eventDate": "2026-11-25T04:00:00Z"}]}

    db.session.add(ServiceProvider(name="cloudflare", display_name="Cloudflare", is_active=True,
                                   credentials_json=json.dumps({"api_token": "t", "account_id": "a"})))
    db.session.commit()
    live_watch.check_domains(cf=cf, rdap=lambda url: R())
    d = {w.domain: w for w in DomainWatch.query.all()}
    check("Cloudflare's registrar gives the date and the auto-renew setting",
          d["kuperplumbing.com"].expires_on == date(2026, 11, 20) and d["kuperplumbing.com"].auto_renew is False
          and d["kuperplumbing.com"].registrar == "cloudflare")
    check("a domain elsewhere gets its date from RDAP and no setting",
          d["robinsonandcodesign.com"].expires_on == date(2026, 11, 25) and d["robinsonandcodesign.com"].auto_renew is None)
    rows = live_watch.attention_rows(force=True, today=date(2026, 11, 4), now=t0)
    doms = {r["title"] for r in rows if r["key"].startswith("domain:")}
    check("under 30 days with auto-renew off, or held elsewhere, is a row; auto-renewing is not",
          "kuperplumbing.com" in doms and "robinsonandcodesign.com" in doms and "entertainhq.com" not in doms, doms)
    pills = {r["pill"] for r in rows}
    check("the crashed deploy and the stale one are rows", {"Deploy", "Behind"} <= pills, pills)

    attention = c.get("/admin/attention/").data.decode("utf-8", "replace")
    check("Needs attention draws them", "data-live-row=\"deploy:" in attention and "Certificate runs out" in attention)
    from pm.attention_routes import attention_counts
    with application.test_request_context():
        live_watch._CACHE["rows"] = None
        counts = attention_counts()
    check("and the badge counts them", counts["live"] == len(live_watch.attention_rows(force=True)) and counts["live"] >= 4,
          counts)

print("\n19. THE REPO'S VERSION AGAINST THE STORES'")
FILES = {
    "android/app/build.gradle": 'android {\n  defaultConfig {\n    applicationId "com.acme.app"\n    versionName "1.4.0"\n  }\n}',
    "ios/App/App.xcodeproj/project.pbxproj": "MARKETING_VERSION = 1.4.0;\nMARKETING_VERSION = 1.4.0;\nMARKETING_VERSION = 2.0;\n",
}
check("gradle and Xcode", store_ids_service.versions_from_files(FILES) == {"android": "1.4.0", "ios": "1.4.0"},
      store_ids_service.versions_from_files(FILES))
check("Expo's app.json for both",
      store_ids_service.versions_from_files({"app.json": json.dumps({"expo": {"version": "3.1.0"}})})
      == {"android": "3.1.0", "ios": "3.1.0"})
check("a variable is not a version",
      store_ids_service.versions_from_files({"app/build.gradle": 'versionName "${v}"'})["android"] is None)

with application.app_context():
    tile = AppLink(name="Phone", url="https://phone.test", app_store_bundle_id="com.acme.app", play_package="com.acme.app",
                   repo_versions=json.dumps({"android": "1.4.0", "ios": "1.4.0"}),
                   store_versions=json.dumps({"app_store": {"status": "live", "version": "1.3.2"},
                                              "play": {"status": "live", "version": "1.3.2"}}),
                   store_checked_at=datetime.now(timezone.utc).replace(tzinfo=None))
    db.session.add(tile)
    db.session.commit()
    check("the tile says it", tile.repo_line == "1.4.0 in the repo, stores on 1.3.2", tile.repo_line)
    tile.repo_versions = json.dumps({"android": "1.3.2"})
    check("and says nothing when they agree", tile.repo_line is None)
    tile.repo_versions = json.dumps({"android": "1.4.0"})
    db.session.commit()
    tile_id = tile.id
board = c.get("/admin/apps/").data.decode("utf-8", "replace")
check("My Apps draws the line", "1.4.0 in the repo, stores on 1.3.2" in board)

print("\n4. STORE VERSIONS, NIGHTLY")
with application.app_context():
    tile = db.session.get(AppLink, tile_id)
    store_versions_service.lookup_app_store = lambda b: {"status": "live", "version": "1.4.0"}
    store_versions_service.lookup_play = lambda p: {"status": "live", "version": "1.3.2"}
    first = datetime(2026, 11, 3, 13, tzinfo=timezone.utc)
    store_versions_service.refresh(tile, now=first)
    check("differing is dated the first night it is seen", tile.store_differ_since == first.replace(tzinfo=None))
    store_versions_service.refresh(tile, now=first + timedelta(days=1))
    check("and keeps that date while it lasts", tile.store_differ_since == first.replace(tzinfo=None))
    db.session.commit()
    rows = live_watch.attention_rows(force=True, today=date(2026, 11, 4), now=first.replace(tzinfo=None) + timedelta(hours=2))
    check("two hours of differing is not a row", not any(r["key"].startswith("stores:") for r in rows))
    rows = live_watch.attention_rows(force=True, today=date(2026, 11, 4), now=first.replace(tzinfo=None) + timedelta(days=2))
    check("two days is", any(r["key"] == f"stores:{tile_id}" and "1.4.0" in r["detail"] for r in rows),
          [r["key"] for r in rows])
    store_versions_service.lookup_play = lambda p: {"status": "live", "version": "1.4.0"}
    note = store_versions_service.refresh_all()
    check("the nightly refresh asks every tile with an id, and agreeing clears it",
          tile.store_differ_since is None and note.startswith("1 apps asked"), note)

print("\nTILE TEXT AND ICONS")
check("a page's own description is read off its meta tag",
      tile_upkeep.meta_description('<meta property="og:description" content="Plumbing &amp; heating in Paris">')
      == "Plumbing & heating in Paris")
with application.app_context():
    now = datetime(2026, 11, 4)
    blank = AppLink(name="Blank", url="https://blank.test", github_url="https://github.com/BuiltByBean/Blank",
                    description="", icon_source="https://blank.test/icon.png", icon_file="x.png",
                    icon_fetched_at=now - timedelta(days=45))
    typed = AppLink(name="Typed", url="https://typed.test", description="Said by hand",
                    icon_file="up.png", icon_source=None, icon_fetched_at=now - timedelta(days=400))
    fresh = AppLink(name="Fresh", url="https://fresh.test", description="x", icon_source="s", icon_file="f.png",
                    icon_fetched_at=now - timedelta(days=3))
    db.session.add_all([blank, typed, fresh])
    db.session.commit()
    check("a fetched icon a month old wants fetching", tile_upkeep.wants_icon(blank, now))
    check("an uploaded one never does", not tile_upkeep.wants_icon(typed, now))
    check("a fresh one does not", not tile_upkeep.wants_icon(fresh, now))
    fetched = []
    tile_upkeep.run(site=lambda u: Resp(404, u), repo=lambda path: {"description": "Repo words"},
                    refresh_icon=lambda link: fetched.append(link.name) or True)
    check("an empty description fills from the repo", blank.description == "Repo words", blank.description)
    check("a typed one is left alone", typed.description == "Said by hand")
    check("only the stale fetched icons were asked for", "Blank" in fetched and "Typed" not in fetched and "Fresh" not in fetched,
          fetched)

print("\nRAILWAY BILLS FROM MAIL")
check("a receipt on Sep 1 is August's bill, one on Nov 16 October's, one on Mar 1 February's",
      railway_mail.period_month(date(2026, 9, 1)) == date(2026, 8, 1)
      and railway_mail.period_month(date(2026, 11, 16)) == date(2026, 10, 1)
      and railway_mail.period_month(date(2026, 3, 1)) == date(2026, 2, 1))
with application.app_context():
    ehq_b = Business(name="EntertainHQ LLC", slug="ehq", sales_source="manual")
    db.session.add(ehq_b)
    db.session.flush()
    partner = ServiceProvider(name="railway", display_name="Railway (EHQ partner)", is_active=True,
                              credentials_json="{}", account_business_id=ehq_b.id)
    db.session.add(partner)
    db.session.flush()
    box = ReceiptMailbox(business_id=ehq_b.id, address="books@ehq.test")
    db.session.add(box)
    db.session.flush()
    db.session.add_all([
        Receipt(mailbox_id=box.id, message_key="a", sender="Railway <invoice@railway.app>", vendor="Railway",
                subject="Your receipt", received_on=date(2026, 10, 16), amount=43.71),
        Receipt(mailbox_id=box.id, message_key="b", sender="Railway <invoice@railway.app>", vendor="Railway",
                subject="Your receipt", received_on=date(2026, 9, 16), amount=40.00),
        Receipt(mailbox_id=box.id, message_key="c", sender="Twilio <x@twilio.com>", vendor="Twilio",
                subject="Receipt", received_on=date(2026, 10, 16), amount=20.00),
    ])
    db.session.add(ProviderInvoice(provider_id=partner.id, period_month=date(2026, 8, 1), amount=39.0,
                                   note="Typed off the bill"))
    db.session.commit()
    check("the account with a workspace token is not a mail account",
          set(p.id for p in railway_mail.tokenless_providers().values()) == {partner.id},
          railway_mail.tokenless_providers())
    note = railway_mail.run()
    got = {i.period_month: (i.amount, i.note) for i in ProviderInvoice.query.filter_by(provider_id=partner.id).all()}
    check("September's receipt is September's bill, from mail", got.get(date(2026, 9, 1), (None, ""))[0] == 43.71
          and got[date(2026, 9, 1)][1].startswith("From mail"), got)
    check("August's typed bill is never touched", got[date(2026, 8, 1)] == (39.0, "Typed off the bill"), got)
    check("a Twilio receipt is not Railway's", all(a in (43.71, 40.0, 39.0) for a, _ in got.values()), got)

print("\n" + ("ALL PASS" if not FAIL else str(len(FAIL)) + " FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
