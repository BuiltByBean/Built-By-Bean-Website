"""Playbook steps that tick themselves when a machine can see them done.

docs/automation_gaps.md item 20. Every ProjectPlaybookStep was a press,
including the ones the repo and Railway already prove: a pre-deploy command,
a health check path, a custom domain, a deploy from the branch's head. A
step may now carry a check (PlaybookStep.check_kind / check_target /
check_pattern, written through the door like the rest of the checklist), and
nightly every project running that playbook is held against it.

  repo     a line matching check_pattern in a file matching check_target's
           globs, in the project's repo (Project.repo, else a tile's
           github_url). The rule audit's own scanner and glob dialect.
  railway  a fact about the Railway services mapped to the project
           (ServiceMapping railway:<project>), read tonight by railway_watch:
           one of RAILWAY_FACTS. check_pattern, when given, must also match
           the fact's value (a domain, a path, a command).
  http     the project's site answers check_target (a path) under 400, and
           check_pattern, when given, is in the body.

A pass ticks the step and writes why in its note when the note is empty. A
fail does nothing: nothing is ever unticked automatically, because a check
that cannot see something tonight is not proof that it was undone.
"""
import re
from datetime import datetime, timezone

import requests

RAILWAY_FACTS = {
    "service": "a service exists",
    "repo": "a service deploys from a repo",
    "custom_domain": "a custom domain is attached",
    "healthcheck": "a health check path is set",
    "pre_deploy": "a pre-deploy command is set",
    "deploy_success": "the latest deploy succeeded",
    "deploy_current": "the latest deploy succeeded from the branch's head",
}


def validate(kind, target, pattern):
    """An error string for a check that cannot run, else None."""
    if not kind:
        return None
    if kind not in ("repo", "railway", "http"):
        return "check_kind must be repo, railway or http"
    if kind == "railway" and target not in RAILWAY_FACTS:
        return "a railway check_target is one of: " + ", ".join(RAILWAY_FACTS)
    if kind == "repo" and not (pattern or "").strip():
        return "a repo check needs a check_pattern"
    if kind == "http" and not (target or "").startswith("/"):
        return "an http check_target is a path starting with /"
    if pattern:
        try:
            re.compile(pattern)
        except re.error as err:
            return f"check_pattern does not compile: {err}"
    return None


def project_repo(project):
    import railway_watch
    if railway_watch.norm_repo(project.repo):
        return railway_watch.norm_repo(project.repo)
    for link in getattr(project, "apps", None) or []:
        if railway_watch.norm_repo(link.github_url):
            return railway_watch.norm_repo(link.github_url)
    return None


def project_services(project):
    from models import RailwayService, ServiceMapping
    refs = [m.resource_identifier.split(":", 1)[1]
            for m in ServiceMapping.query.filter_by(project_id=project.id, is_active=True).all()
            if (m.resource_identifier or "").startswith("railway:")]
    if not refs:
        return []
    return [s for s in RailwayService.query.filter(RailwayService.project_ref.in_(refs)).all()
            if s.environment == "production" and not s.is_database]


def railway_fact(services, fact):
    """[values] that make the fact true; empty means not seen."""
    import railway_watch
    if fact == "service":
        return [s.service_name or s.service_ref for s in services]
    if fact == "repo":
        return [s.repo for s in services if s.repo]
    if fact == "custom_domain":
        return [d for s in services for d in s.custom_domains]
    if fact == "healthcheck":
        return [s.healthcheck_path for s in services if s.healthcheck_path]
    if fact == "pre_deploy":
        return [s.pre_deploy for s in services if s.pre_deploy]
    if fact == "deploy_success":
        return [s.deploy_commit or s.service_name for s in services if s.deploy_status == "SUCCESS"]
    if fact == "deploy_current":
        return [s.deploy_commit for s in services
                if s.deploy_status == "SUCCESS" and s.deploy_commit and s.branch_head
                and (s.branch_head.startswith(s.deploy_commit) or s.deploy_commit.startswith(s.branch_head))]
    return []


def run_check(step, project, repo_files=None, http_get=None):
    """(passed, why)."""
    pattern = re.compile(step.check_pattern) if (step.check_pattern or "").strip() else None
    if step.check_kind == "railway":
        values = railway_fact(project_services(project), step.check_target)
        if pattern is not None:
            values = [v for v in values if pattern.search(str(v))]
        return (bool(values), f"Railway: {RAILWAY_FACTS.get(step.check_target, step.check_target)}"
                + (f" ({values[0]})" if values else ""))
    if step.check_kind == "repo":
        import audit_repos
        repo = project_repo(project)
        if not repo or repo_files is None:
            return False, "no repo"
        files = repo_files(repo)
        sig = audit_repos.compile_signature(step.check_pattern, step.check_target or "**/*", "")
        if sig is None:
            return False, "bad pattern"
        count, samples = audit_repos._scan(files, [(step, sig)]).get(step.id, (0, []))
        where = f" ({samples[0]['path']}:{samples[0]['line']})" if samples else ""
        return count > 0, f"In the repo{where}"
    if step.check_kind == "http":
        base = next((a.url for a in (getattr(project, "apps", None) or [])
                     if (a.url or "").startswith(("http://", "https://"))), None)
        if not base:
            return False, "no site"
        url = base.rstrip("/") + step.check_target
        get = http_get or (lambda u: requests.get(u, timeout=15, headers={"User-Agent": "BuiltByBean-Board/1.0"}))
        try:
            resp = get(url)
        except requests.RequestException:
            return False, "no answer"
        ok = resp.status_code < 400 and (pattern is None or bool(pattern.search(resp.text or "")))
        return ok, f"{url} answered {resp.status_code}"
    return False, "no check"


def run(repo_files=None, http_get=None, now=None):
    """Every applied playbook with a checked step not yet done. Returns a summary."""
    from models import db, PlaybookStep, ProjectPlaybook, ProjectPlaybookStep
    now = now or datetime.now(timezone.utc)
    cache = {}

    def files_of(repo):
        if repo not in cache:
            if repo_files is not None:
                cache[repo] = repo_files(repo)
            else:
                import audit_repos
                cache[repo] = audit_repos.fetch_tarball(repo)[0]
        return cache[repo]

    checked = ticked = 0
    steps_by_playbook = {}
    for step in PlaybookStep.query.filter(PlaybookStep.check_kind.isnot(None)).all():
        if validate(step.check_kind, step.check_target, step.check_pattern) is None:
            steps_by_playbook.setdefault(step.playbook_id, []).append(step)
    if not steps_by_playbook:
        return "no steps carry a check"
    for applied in ProjectPlaybook.query.filter(
            ProjectPlaybook.playbook_id.in_(list(steps_by_playbook))).all():
        done = applied.done_ids
        for step in steps_by_playbook[applied.playbook_id]:
            if step.id in done:
                continue
            checked += 1
            try:
                passed, why = run_check(step, applied.project, files_of, http_get)
            except Exception as err:  # noqa: BLE001 - one project never stops the rest
                print(f"step checks: {applied.project.name} / {step.title}: {str(err)[:120]}", flush=True)
                continue
            if not passed:
                continue
            row = next((p for p in applied.progress if p.playbook_step_id == step.id), None)
            if row is None:
                row = ProjectPlaybookStep(project_playbook_id=applied.id, playbook_step_id=step.id)
                db.session.add(row)
                applied.progress.append(row)
            row.done, row.done_at = True, now
            if not (row.note or "").strip():
                row.note = f"Ticked by the nightly check: {why}"[:500]
            ticked += 1
        db.session.commit()
    return f"{checked} steps checked, {ticked} ticked"
