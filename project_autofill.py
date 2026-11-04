"""What a project's repo and domain say about it, read nightly (audit item 11).

Michael typed three things on every project that are already written down
somewhere else: which GitHub repo it is, the day the build started, and the
day it went live. The last one starts the free maintenance clock, so a missed
one turns billable hours into free ones.

- **The repo pair.** `Project.repo` (owner/name) and the My Apps tile's
  `github_url` are two fields for one fact, joined by `AppLink.project_id`.
  Whichever is empty is filled from the other; failing both, from a repo
  whose `homepage` is the tile's host. The nightly store-id read skips a tile
  without `github_url`, which is why this runs before it.
- **Contracted to MVP** on the first commit after the contract date (the
  earliest signed contract on the project, else the day the project was put on
  the board, since nothing reaches this board before it is under contract).
  `build_started_on` records the commit's day.
- **The My Apps tile.** A project with no tile is put on the one unattached
  tile with its repo, its name or a domain spelled like its name, so its card
  carries the tile's icon and picks up a new one by itself.
- **Go-live** is filled in by itself (Michael's pick, 2026-11-04, over a
  suggestion to accept) on the first night the project's real domain answers,
  for a project whose build has started. A platform's temporary address
  (railway.app and the like) never counts. `go_live_source` says where the
  date came from, so the page can say so.

All three only ever write into an EMPTY field, never move a phase anybody
held (`phase_locked`), and leave archived projects alone. No model, no cost:
GitHub's API with the token the sweep already has, and one GET per domain.

`plan` is pure, so the rules are tested without a network; `main` is the
nightly step.
"""
import json
import os
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone

GITHUB = "https://api.github.com"
USER_AGENT = "builtbybean-board/1.0 (project autofill)"
# A platform's own address before a real domain is attached: a stepping stone,
# never the day something went live (the same list register_app keeps).
TEMP_HOSTS = (".up.railway.app", ".railway.app", ".onrender.com", ".fly.dev",
              ".vercel.app", ".netlify.app", ".herokuapp.com", ".pages.dev")
# The phases in which a domain answering means it went live. Before the build
# started, a domain answering is more likely the client's old site.
LIVE_FROM = ("mvp", "delivered")


def repo_of(url):
    m = re.match(r"https?://(?:www\.)?github\.com/([^/\s]+/[^/#?\s]+)", url or "")
    return m.group(1).removesuffix(".git").rstrip("/") if m else None


def url_of(repo):
    repo = (repo or "").strip().strip("/")
    return f"https://github.com/{repo}" if re.fullmatch(r"[\w.\-]+/[\w.\-]+", repo) else None


def host_of(url):
    host = (url or "").split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
    return host[4:] if host.startswith("www.") else host


def is_real_domain(url):
    host = host_of(url)
    return bool(host) and "." in host and not any(host.endswith(t) for t in TEMP_HOSTS) \
        and host not in ("localhost", "127.0.0.1")


def texas_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Chicago")).date()
    except Exception:  # noqa: BLE001
        return (datetime.now(timezone.utc) - timedelta(hours=6)).date()


# ------------------------------------------------------------- the network

def _github(path, token=None):
    """(json, headers) for a GitHub path."""
    token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(GITHUB + path, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8") or "null"), dict(resp.headers)


def first_commit_after(repo, since, fetch=_github):
    """The day of the earliest commit on the default branch on or after
    `since`, or None. GitHub lists newest first, so with one per page the
    Link header's last page IS the oldest: two calls whatever the history."""
    path = f"/repos/{repo}/commits?since={since.isoformat()}T00:00:00Z&per_page=1"
    rows, headers = fetch(path)
    if not rows:
        return None
    link = headers.get("Link") or headers.get("link") or ""
    m = re.search(r'<[^>]*[?&]page=(\d+)[^>]*>;\s*rel="last"', link)
    if m and m.group(1) != "1":
        rows, _ = fetch(f"{path}&page={m.group(1)}")
        if not rows:
            return None
    when = ((rows[0].get("commit") or {}).get("committer") or {}).get("date") \
        or ((rows[0].get("commit") or {}).get("author") or {}).get("date")
    try:
        return datetime.fromisoformat(str(when).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def answers(url, opener=None):
    """Whether the address answers with a page: anything under 400, after
    redirects. A timeout, a refusal or a certificate error is no answer."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with (opener or urllib.request.urlopen)(req, timeout=12) as resp:
            return resp.status < 400
    except Exception:  # noqa: BLE001
        return False


def homepages(fetch=_github):
    """{host: owner/name} from every repo the token can see that names a
    homepage. One paged call; nothing when there is no token."""
    if not os.environ.get("GITHUB_TOKEN"):
        return {}
    out = {}
    for page in range(1, 6):
        rows, _ = fetch(f"/user/repos?per_page=100&page={page}&sort=pushed")
        for r in rows or []:
            if r.get("homepage") and is_real_domain(r["homepage"]):
                out.setdefault(host_of(r["homepage"]), r["full_name"])
        if not rows or len(rows) < 100:
            break
    return out


# ------------------------------------------------------------- the rules

def contract_date(project):
    """The day the project went under contract: its earliest signed
    contract, else the day it was put on the board."""
    from models import SignatureRequest
    signed = [s.completed_at for s in SignatureRequest.query.filter(
        SignatureRequest.project_id == project.id,
        SignatureRequest.completed_at.isnot(None)).all()]
    if not signed and project.client_id:
        signed = [s.completed_at for s in SignatureRequest.query.filter(
            SignatureRequest.client_id == project.client_id,
            SignatureRequest.project_id.is_(None),
            SignatureRequest.kind.in_(("sow", "engagement_letter")),
            SignatureRequest.completed_at.isnot(None)).all()]
    if signed:
        return min(signed).date()
    return project.created_at.date() if project.created_at else None


def movable(project):
    """Dates may move this one: a client build nobody held, not archived.
    His own products and personal projects have no contract and no phases."""
    return (not project.phase_locked and (project.status or "") != "archived"
            and project.is_client_build)


def fill_repos(project, links, by_host=None):
    """Fill the empty half of each repo pair. Returns what changed."""
    changed = []
    by_host = by_host or {}
    if not project.repo:
        found = next((repo_of(l.github_url) for l in links if repo_of(l.github_url)), None) \
            or next((by_host.get(host_of(l.url)) for l in links if by_host.get(host_of(l.url))), None)
        if found:
            project.repo = found
            changed.append(f"repo {found}")
    url = url_of(project.repo)
    for link in links:
        if not link.github_url and url:
            link.github_url = url
            changed.append(f"{link.name} GitHub")
    return changed


def _flat(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def tile_matches(project, tile):
    """Whether an unattached My Apps tile is this project's: the same repo,
    the same name, or a domain spelled like the name (deedinhand.com)."""
    if project.repo and repo_of(tile.github_url) and             repo_of(tile.github_url).lower() == project.repo.strip().lower():
        return True
    name = _flat(project.name)
    if not name:
        return False
    host = host_of(tile.url).split(".")[0] if is_real_domain(tile.url) else ""
    return name in (_flat(tile.name), _flat(host))


def tile_for(project, unattached):
    """The one unattached tile that is this project's, or None. Two matches
    is a guess, and a guess is never written."""
    hits = [t for t in unattached if tile_matches(project, t)]
    return hits[0] if len(hits) == 1 else None


def attach_tiles(projects, tiles):
    """Put each project with no tile on the one unattached tile that is its
    own (Michael, 2026-11-04: "Deed in Hand has a logo now" while its card
    showed initials). The tile keeps its half of My Apps: an unattached tile
    sat in Personal projects, and attaching a project must not move it."""
    loose = [t for t in tiles if not t.project_id]
    lines = []
    for p in projects:
        if any(t.project_id == p.id for t in tiles):
            continue
        tile = tile_for(p, loose)
        if tile:
            if not tile.board_group:
                tile.board_group = "mine"
            tile.project_id = p.id
            loose.remove(tile)
            lines.append(f"{p.name}: My Apps tile {tile.name}")
    return lines


def plan(project, links, first_commit=None, live=None, today=None):
    """What the dates say, given what was read. Pure: `first_commit` is the
    day of the first commit after the contract (or None), `live` the tile URL
    that answered tonight (or None). Returns [(field, value, why)]."""
    today = today or date.today()
    out = []
    if not movable(project):
        return out
    if project.phase == "contracted" and first_commit:
        out.append(("phase", "mvp", f"first commit after the contract, {first_commit:%b %d, %Y}"))
        if not project.build_started_on:
            out.append(("build_started_on", first_commit, "first commit"))
    phase_after = "mvp" if any(f == "phase" for f, _, _ in out) else project.phase
    if not project.go_live_date and phase_after in LIVE_FROM and live:
        # The domain whose first answer set the date; the page shows it as a fact.
        out.append(("go_live_date", today, host_of(live)))
    return out


def apply(project, moves):
    for field, value, why in moves:
        setattr(project, field, value)
        if field == "go_live_date":
            project.go_live_source = why


def run(fetch=_github, probe=answers, today=None):
    """Every project, once. Returns lines saying what changed."""
    from models import db, Project, AppLink
    today = today or texas_today()
    lines = []
    projects = Project.query.order_by(Project.id).all()
    lines += attach_tiles(projects, AppLink.query.order_by(AppLink.id).all())
    links_by_project = {}
    for link in AppLink.query.filter(AppLink.project_id.isnot(None)).all():
        links_by_project.setdefault(link.project_id, []).append(link)

    need_homepage = any(not p.repo and not any(repo_of(l.github_url) for l in links_by_project.get(p.id, []))
                        and links_by_project.get(p.id) for p in projects)
    try:
        by_host = homepages(fetch) if need_homepage else {}
    except Exception as err:  # noqa: BLE001
        by_host = {}
        lines.append(f"homepages: {str(err)[:120]}")

    for p in projects:
        links = links_by_project.get(p.id, [])
        changed = fill_repos(p, links, by_host)

        first = None
        if movable(p) and p.phase == "contracted" and p.repo:
            since = contract_date(p)
            if since:
                try:
                    first = first_commit_after(p.repo, since, fetch)
                except Exception as err:  # noqa: BLE001 - one repo never stops the rest
                    lines.append(f"{p.name}: commits: {str(err)[:120]}")

        live = None
        phase_next = "mvp" if (p.phase == "contracted" and first) else p.phase
        if movable(p) and not p.go_live_date and phase_next in LIVE_FROM:
            live = next((l.url for l in links if is_real_domain(l.url) and probe(l.url)), None)

        moves = plan(p, links, first, live, today)
        apply(p, moves)
        changed += [f"{f} {v}" for f, v, _ in moves]
        if changed:
            lines.append(f"{p.name}: {', '.join(str(c) for c in changed)}")
    db.session.commit()
    return lines


def main():
    """The nightly step (sync_costs._sweep)."""
    from app import create_app
    app = create_app()
    with app.app_context():
        lines = run()
    for line in lines:
        print(f"project dates: {line}", flush=True)
    # What the night record says for this step: what changed, or nothing.
    return "; ".join(lines)[:500] or None


if __name__ == "__main__":
    main()
