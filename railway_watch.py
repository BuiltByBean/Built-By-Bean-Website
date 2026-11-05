"""Every Railway service, read nightly with the account token, and what it means.

docs/automation_gaps.md item 7 (and the deploy half of item 9). Until
2026-11-04 every ServiceMapping, Railway project to board project, was typed on
the mappings form or found by an exact-name "Automap"; a tile's railway_url
was typed; and a build live on Railway with no tile was noticed only if a
session remembered register_app. One GraphQL query per workspace, with the
account token the board already holds for bills (PM_RAILWAY_ACCOUNT_TOKEN),
answers all three: each service's source repo, its domains and its latest
deployment.

What it writes, and the rule for each:

  - RailwayService: one row per service per environment, the picture as it is
    tonight. Upserted on (service, environment), so it is always current, and
    a service the workspace no longer has is taken off (`prune`).
  - ServiceMapping: only for a Railway project that points at exactly ONE
    board project (by repo, or by a tile it serves), and only where no
    mapping exists or the one that does names no project. Two candidates is
    a guess, and a cost confidently booked to the wrong client is worse than
    one left unallocated.
  - AppLink.railway_url, github_url and a platform address: they FOLLOW the
    one production service a tile matches, whatever was there before, and
    never on two candidates (`match_tiles`). They were filled only when empty
    until 2026-11-05, when the tile lost its edit button (Michael: "nothing
    should be manual"): with no form there is nothing typed left to protect,
    and Railway is the truth about what serves an app.
  - A tile whose Railway project was on the board last night and is gone
    tonight is retired (`app_retire.retire`), only when every workspace
    answered and none was held back, because a project that moved to a
    workspace that did not answer looks exactly like one that was deleted.

"Live on Railway, not on My Apps" is a production service people can reach
(a domain, not a template database) that no tile matches by host or repo,
and that nobody has marked "Not an app". It is one row on Needs attention.

`parse_workspace` and the matching are pure over rows, so the test runs them
on the shape Railway really answers with (read live on 2026-11-04).
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

QUERY = """
query($w: String!) { workspace(workspaceId: $w) { projects { edges { node { id name deletedAt
  environments { edges { node { id name } } }
  services { edges { node { id name
    serviceInstances { edges { node { environmentId
      source { repo image }
      domains { serviceDomains { domain } customDomains { domain } }
      latestDeployment { status createdAt meta }
    } } }
  } } }
} } } } }"""

# A deploy that did not come up.
BROKEN = ("FAILED", "CRASHED")
# How long a newer commit may sit on the branch undeployed before it is a row.
BEHIND_GRACE = timedelta(days=1)


def _when(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def norm_repo(value):
    """owner/name, lower case, from a repo name or a GitHub URL."""
    value = (value or "").strip()
    m = re.match(r"(?:https?://)?(?:www\.)?github\.com/([^/]+/[^/#?]+)", value)
    if m:
        value = m.group(1)
    value = value.strip("/").removesuffix(".git")
    return value.lower() if value.count("/") == 1 else ""


def host_of(url):
    """The host a URL answers on, lower case, no www, no port."""
    url = (url or "").strip()
    if not url or url.startswith("/"):
        return ""
    if "//" not in url:
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def parse_workspace(ws):
    """[{...}] one per service instance, from the workspace query's answer."""
    out = []
    for pe in ((ws or {}).get("projects") or {}).get("edges") or []:
        p = pe.get("node") or {}
        # A deleted project stays in the answer for two days with the time
        # Railway will remove it (2026-11-05: Personal Trainer and Dom's
        # Painting). It is gone from the moment it was deleted, so its rows
        # are left out and `prune` takes them off tonight, not in two days.
        if p.get("deletedAt"):
            continue
        envs = {e["node"]["id"]: e["node"]["name"]
                for e in (p.get("environments") or {}).get("edges") or []}
        for se in (p.get("services") or {}).get("edges") or []:
            s = se.get("node") or {}
            for ie in (s.get("serviceInstances") or {}).get("edges") or []:
                i = ie.get("node") or {}
                source = i.get("source") or {}
                doms = i.get("domains") or {}
                service_domains = [d["domain"] for d in doms.get("serviceDomains") or [] if d.get("domain")]
                # A wildcard is a routing rule, not an address anybody visits.
                custom = [d["domain"] for d in doms.get("customDomains") or []
                          if d.get("domain") and "*" not in d["domain"]]
                ld = i.get("latestDeployment") or {}
                meta = ld.get("meta") or {}
                deploy = ((meta.get("serviceManifest") or {}).get("deploy") or {})
                out.append({
                    "project_ref": p.get("id"), "project_name": p.get("name") or "",
                    "service_ref": s.get("id"), "service_name": s.get("name") or "",
                    "environment": envs.get(i.get("environmentId"), "production"),
                    "repo": source.get("repo"), "image": source.get("image"),
                    "domains": [d.lower() for d in custom + service_domains],
                    "custom_domains": [d.lower() for d in custom],
                    "deploy_status": ld.get("status"),
                    "deploy_commit": meta.get("commitHash"),
                    "deploy_branch": meta.get("branch"),
                    "deployed_at": _when(ld.get("createdAt")),
                    "healthcheck_path": deploy.get("healthcheckPath"),
                    "pre_deploy": (" ".join(deploy["preDeployCommand"])
                                   if isinstance(deploy.get("preDeployCommand"), list)
                                   else deploy.get("preDeployCommand")),
                })
    return out


def store(provider_id, rows, now=None):
    """Upsert tonight's rows. Returns how many."""
    from models import db, RailwayService
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    for r in rows:
        if not r.get("service_ref"):
            continue
        row = RailwayService.query.filter_by(service_ref=r["service_ref"],
                                             environment=r["environment"]).first()
        if row is None:
            row = RailwayService(service_ref=r["service_ref"], environment=r["environment"])
            db.session.add(row)
        row.provider_id = provider_id
        row.project_ref = r["project_ref"]
        row.project_name = (r["project_name"] or "")[:200]
        row.service_name = (r["service_name"] or "")[:200]
        row.repo = (r["repo"] or None) and r["repo"][:200]
        row.image = (r["image"] or None) and r["image"][:300]
        row.domains_json = json.dumps(r["domains"])
        row.custom_domains_json = json.dumps(r["custom_domains"])
        row.deploy_status = r["deploy_status"]
        if r["deploy_commit"] != row.deploy_commit:
            row.branch_head = row.branch_head_at = None  # read again below
        row.deploy_commit = r["deploy_commit"]
        row.deploy_branch = r["deploy_branch"]
        row.deployed_at = r["deployed_at"]
        row.healthcheck_path = (r["healthcheck_path"] or None) and str(r["healthcheck_path"])[:200]
        row.pre_deploy = (r["pre_deploy"] or None) and str(r["pre_deploy"])[:300]
        row.seen_at = now
    db.session.flush()
    return len(rows)


def prune(provider_id, rows):
    """Take off the rows of services this workspace no longer has, and say which.

    `store` only ever upserted, so a project deleted on Railway stayed on the
    board for good: its web service kept reading "live on Railway, not on My
    Apps" and its last deploy kept being judged (2026-11-05, Personal Trainer
    and Dom's Painting). Called only with the rows of a read that answered.
    An answer with nothing in it, or one missing more than half of what this
    workspace had, removes nothing: that is likelier a bad read than a cull,
    and the night's note says what was held back.
    """
    from models import db, RailwayService
    keep = {(r["service_ref"], r["environment"]) for r in rows if r.get("service_ref")}
    have = RailwayService.query.filter_by(provider_id=provider_id).all()
    gone = [s for s in have if (s.service_ref, s.environment) not in keep]
    if not gone:
        return [], None
    if not keep or len(gone) * 2 > len(have):
        return [], f"{len(gone)} of {len(have)} services missing from the read, none removed"
    names = [f"{s.project_name}/{s.service_name} ({s.environment})" for s in gone]
    for s in gone:
        db.session.delete(s)
    db.session.flush()
    return names, None


def read_branch_heads(get=None):
    """For every production service built from a repo, the head of the branch
    it deploys, so a deploy that is behind can be said. One request each."""
    from models import db, RailwayService
    import sweep_repos
    get = get or sweep_repos._get
    done = {}
    for row in RailwayService.query.filter(RailwayService.repo.isnot(None),
                                           RailwayService.deploy_branch.isnot(None)).all():
        key = (row.repo, row.deploy_branch)
        if key not in done:
            try:
                got = get(f"/repos/{row.repo}/commits/{row.deploy_branch}")
                done[key] = (got.get("sha"),
                             _when(((got.get("commit") or {}).get("committer") or {}).get("date")))
            except Exception as err:  # noqa: BLE001 - one repo never stops the rest
                print(f"railway: {row.repo}@{row.deploy_branch}: {str(err)[:120]}", flush=True)
                done[key] = (None, None)
        row.branch_head, row.branch_head_at = done[key]
    db.session.flush()


def is_behind(row, now=None):
    """The deployed commit is not the branch's head, and the head has had a
    day to deploy."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if not (row.deploy_commit and row.branch_head and row.branch_head_at):
        return False
    if row.branch_head.startswith(row.deploy_commit) or row.deploy_commit.startswith(row.branch_head):
        return False
    return now - row.branch_head_at > BEHIND_GRACE


# ── Matching ─────────────────────────────────────────────


def _tile_matches(link, services):
    """The services one tile is: by its host first, else by its repo."""
    host = host_of(link.url)
    by_host = [s for s in services if host and host in s.domains]
    if by_host:
        return by_host
    repo = norm_repo(link.github_url)
    if not repo:
        return []
    by_repo = [s for s in services if norm_repo(s.repo) == repo]
    reachable = [s for s in by_repo if s.domains]
    return reachable or by_repo


def _live(services):
    return [s for s in services if s.environment == "production" and not s.is_database]


def _platform_host(host):
    return host.endswith(".railway.app")


def better_host(link, s, taken=()):
    """The host this tile should be on, when Railway says it should move, else
    None. Only a tile on Railway's own address moves: to the service's custom
    domain (the shortest, so the apex over a subdomain, the rule register_app
    keeps), or, with none, to the address Railway gives it now when the old
    one is no longer the service's. A real domain is never moved: which of two
    a client means is not a thing the board can read. Never onto a host
    another tile already has."""
    host = host_of(link.url)
    if not host or not link.is_external or not _platform_host(host):
        return None
    custom = sorted(s.custom_domains, key=lambda d: (len(d), d))
    if custom:
        new = custom[0]
    elif host not in s.domains and s.domains:
        new = s.domains[0]
    else:
        return None
    new = new.lower()
    return None if host_of(new) in (host, *taken) else new


def _moved(url, host):
    parts = urlparse(url if "//" in url else "https://" + url)
    return parts._replace(scheme="https", netloc=host).geturl()


def match_tiles(links, services):
    """Each tile's Railway link, repo and platform address, from the one
    production service it matches. Returns what changed. A moved address has
    its icon fetched again by tile upkeep, later the same night, unless the
    icon was uploaded by hand."""
    notes = []
    prod = _live(services)
    taken = {host_of(link.url) for link in links}
    for link in links:
        found = _tile_matches(link, prod)
        if len(found) != 1:
            continue
        s = found[0]
        if link.railway_url != s.dashboard_url:
            link.railway_url = s.dashboard_url
            notes.append(f"{link.name}: Railway {s.project_name}/{s.service_name}")
        if s.repo and norm_repo(link.github_url) != norm_repo(s.repo):
            link.github_url = f"https://github.com/{s.repo}"
            notes.append(f"{link.name}: repo {s.repo}")
        new = better_host(link, s, taken)
        if new:
            old = host_of(link.url)
            link.url = _moved(link.url, new)[:500]
            taken.add(host_of(new))
            if not (link.icon_file and link.icon_source is None):
                link.icon_fetched_at = None
            notes.append(f"{link.name}: {old} -> {new}")
    return notes


def retire_gone(project_refs):
    """Tiles and hosting mappings of Railway projects gone from Railway, taken
    off the way retire_app takes them. Returns the names of the tiles."""
    import app_retire
    names = []
    for ref in sorted(project_refs):
        done = app_retire.retire(railway_project=ref)
        names += [r["name"] for r in done["removed_apps"]]
        for r in done["removed_apps"]:
            print("railway: retired tile, project gone from Railway: "
                  + json.dumps(r, default=str), flush=True)
    return names


def project_candidates(project_ref, services, projects, links):
    """The board projects one Railway project could be: by repo, or by a tile
    that one of its services serves."""
    mine = [s for s in services if s.project_ref == project_ref]
    repos = {norm_repo(s.repo) for s in mine if s.repo}
    found = {p.id for p in projects if norm_repo(p.repo) and norm_repo(p.repo) in repos}
    live = _live(mine)
    for link in links:
        if link.project_id and _tile_matches(link, live):
            found.add(link.project_id)
    return found


def match_projects(services, projects, links):
    """Write ServiceMappings for every Railway project that points at exactly
    one board project. Returns what was written."""
    from models import db, ServiceMapping
    by_id = {p.id: p for p in projects}
    notes = []
    seen = {}
    for s in services:
        seen.setdefault((s.provider_id, s.project_ref), s.project_name)
    for (provider_id, project_ref), name in seen.items():
        if provider_id is None:
            continue
        found = project_candidates(project_ref, services, projects, links)
        if len(found) != 1:
            continue
        project = by_id[found.pop()]
        rid = f"railway:{project_ref}"
        have = ServiceMapping.query.filter_by(provider_id=provider_id, resource_identifier=rid).all()
        if not have:
            db.session.add(ServiceMapping(
                provider_id=provider_id, resource_identifier=rid, resource_label=name,
                client_id=project.client_id, project_id=project.id,
                split_percentage=100.0, is_active=True))
            notes.append(f"{name} -> {project.name}")
        elif len(have) == 1 and have[0].project_id is None and have[0].client_id in (None, project.client_id):
            have[0].project_id = project.id
            have[0].client_id = project.client_id
            notes.append(f"{name} -> {project.name}")
    db.session.flush()
    return notes


def unlisted(services=None, links=None):
    """Production services people can reach that no tile is: [(service, ...)].
    One per service; databases, crons with no address and services marked
    "Not an app" are left out."""
    from models import AppLink, RailwayService
    services = services if services is not None else RailwayService.query.all()
    links = links if links is not None else AppLink.query.all()
    covered = set()
    prod = _live(services)
    for link in links:
        for s in _tile_matches(link, prod):
            covered.add(s.id)
        repo = norm_repo(link.github_url)
        for s in prod:
            if repo and norm_repo(s.repo) == repo:
                covered.add(s.id)
    return sorted([s for s in prod if s.domains and not s.ignored and s.id not in covered],
                  key=lambda s: ((s.project_name or "").lower(), (s.service_name or "").lower()))


def deploy_problems(services=None, now=None):
    """Production services whose latest deploy broke, or that are a day behind."""
    from models import RailwayService
    services = services if services is not None else RailwayService.query.all()
    out = []
    for s in services:
        if s.environment != "production" or s.is_database or s.ignored:
            continue
        if s.deploy_status in BROKEN:
            out.append({"service": s, "kind": "broken"})
        elif is_behind(s, now):
            out.append({"service": s, "kind": "behind"})
    return out


# ── The night ────────────────────────────────────────────


def _gql(token, query, variables):
    import service_costs_service
    return service_costs_service._railway_gql(token, query, variables, timeout=60)


def read_all(gql=None):
    """Every Railway provider that names its workspace, read and stored, and
    what each no longer has taken off. Returns (read, errors, removed).
    Raises only when no workspace could be read."""
    from models import db, ServiceProvider
    import service_costs_service
    gql = gql or _gql
    read, errors, removed = 0, [], []
    providers = ServiceProvider.query.filter_by(name="railway", is_active=True).all()
    for p in providers:
        creds = service_costs_service._get_credentials(p)
        workspace = (creds.get("workspace_id") or "").strip()
        token = service_costs_service.railway_token(creds)
        if not workspace or not token:
            continue
        try:
            ws = gql(token, QUERY, {"w": workspace}).get("workspace")
        except Exception as err:  # noqa: BLE001 - one workspace never stops the other
            errors.append(f"{p.display_name}: {str(err)[:160]}")
            continue
        rows = parse_workspace(ws)
        read += store(p.id, rows)
        gone, held = prune(p.id, rows)
        removed += gone
        if held:
            errors.append(f"{p.display_name}: {held}")
    db.session.commit()
    if errors and not read:
        raise RuntimeError("; ".join(errors))
    return read, errors, removed


def run(gql=None, get=None):
    from models import db, AppLink, Project, RailwayService
    had = {s.project_ref for s in RailwayService.query.all()}
    read, errors, removed = read_all(gql)
    for name in removed:
        print(f"railway: gone from Railway, taken off: {name}", flush=True)
    # A project is gone only when every workspace answered whole: one that
    # moved into a workspace that failed tonight looks just like a deletion.
    gone = (had - {s.project_ref for s in RailwayService.query.all()}) if not errors else set()
    retired = retire_gone(gone)
    db.session.commit()
    try:
        read_branch_heads(get)
    except Exception as err:  # noqa: BLE001
        errors.append(f"branch heads: {str(err)[:160]}")
    services = RailwayService.query.all()
    links = AppLink.query.order_by(AppLink.id).all()
    projects = Project.query.all()
    mapped = match_projects(services, projects, links)
    tiles = match_tiles(links, services)
    db.session.commit()
    for note in mapped + tiles:
        print(f"railway: {note}", flush=True)
    loose = unlisted(services, links)
    broken = deploy_problems(services)
    note = (f"{read} services, {len(removed)} gone from Railway, {len(retired)} tiles retired, "
            f"{len(mapped)} mapped, {len(tiles)} tile changes, {len(loose)} live with no tile, "
            f"{len(broken)} deploy problems")
    if errors:
        note += "; " + "; ".join(errors)
    return note


def main():
    from app import create_app
    app = create_app()
    with app.app_context():
        return run()


if __name__ == "__main__":
    print(main())
    sys.exit(0)
