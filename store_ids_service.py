"""Each phone app's store ids, read out of its own repo.

Michael, 2026-11-04, on My Apps: "it says App Store is live for Entertain HQ,
but I already know that I've done a submission to the Google Play Store. So
it should have that right next to it ... I need every ... thing automated."
The tile only asks a store about an app whose id it holds, and the Play id
had never been typed, so Play was never asked. The ids are not secrets and not
choices: they are written in the repo (the Android project's applicationId,
the Xcode project's PRODUCT_BUNDLE_IDENTIFIER, a Capacitor appId, an Expo
app.json), so the board reads them from there, nightly, with no model.

`ids_from_files` is pure, so the parse is tested on real file text. `fill`
writes only a field that is empty: a typed id is somebody's deliberate answer
and the repo does not overrule it. A repo whose ios/ or android/ project is
missing gives no id for that store, because an app with no Android project is
not on Play however its Capacitor config is named.
"""
import json
import re

_APP_ID = re.compile(r"""\bapplicationId\s*(?:=\s*)?["']([A-Za-z][\w.]+)["']""")
_BUNDLE = re.compile(r"PRODUCT_BUNDLE_IDENTIFIER\s*=\s*\"?([A-Za-z][\w.\-]+)\"?\s*;")
_CAP_ID = re.compile(r"""\bappId\s*[:=]\s*["']([A-Za-z][\w.]+)["']""")


def _shortest_main(values):
    """The app's own id among a project's targets: not a test or an extension
    target, which carry the app's id plus a suffix, so the shortest wins."""
    keep = [v for v in values if "$(" not in v and not re.search(r"(?i)tests?$|extension|widget|notification", v)]
    return min(keep, key=len) if keep else None


def ids_from_files(files):
    """{"ios": id or None, "android": id or None} from {path: text}."""
    ios = android = None
    has_ios = any("/ios/" in f"/{p}" or p.endswith(".pbxproj") for p in files)
    has_android = any("/android/" in f"/{p}" for p in files)
    for path, text in files.items():
        if re.search(r"(^|/)app/build\.gradle(\.kts)?$", path):
            m = _APP_ID.search(text or "")
            if m:
                android = android or m.group(1)
        elif path.endswith("project.pbxproj"):
            ios = ios or _shortest_main(_BUNDLE.findall(text or ""))
        elif path.endswith("app.json"):
            try:
                expo = (json.loads(text or "{}") or {}).get("expo") or {}
            except ValueError:
                expo = {}
            ios = ios or (expo.get("ios") or {}).get("bundleIdentifier")
            android = android or (expo.get("android") or {}).get("package")
    for path, text in files.items():
        if re.search(r"(^|/)capacitor\.config\.(ts|js|json)$", path):
            m = _CAP_ID.search(text or "")
            if m:
                if has_ios and not ios:
                    ios = m.group(1)
                if has_android and not android:
                    android = m.group(1)
    return {"ios": ios, "android": android}


WANTED = re.compile(r"(^|/)(app/build\.gradle(\.kts)?|project\.pbxproj|app\.json|capacitor\.config\.(ts|js|json))$")


def repo_of(link):
    m = re.match(r"https?://github\.com/([^/]+/[^/#?]+)", link.github_url or "")
    return m.group(1).removesuffix(".git") if m else None


def read_repo(full_name, get=None):
    """{path: text} of the files that can carry a store id, off GitHub."""
    import base64
    import sweep_repos
    get = get or sweep_repos._get
    repo = get(f"/repos/{full_name}")
    tree = get(f"/repos/{full_name}/git/trees/{repo.get('default_branch') or 'main'}?recursive=1")
    paths = [t["path"] for t in tree.get("tree", []) if t.get("type") == "blob"]
    files = {p: "" for p in paths if "/ios/" in f"/{p}" or "/android/" in f"/{p}"}  # presence only
    for path in paths:
        if WANTED.search(path) and "node_modules/" not in path and "/build/" not in path:
            row = get(f"/repos/{full_name}/contents/{path}")
            files[path] = base64.b64decode(row.get("content") or "").decode("utf-8", "replace")
    return files


def fill(link, get=None):
    """Fill the tile's empty store ids from its repo. Returns what changed."""
    full_name = repo_of(link)
    if not full_name:
        return []
    ids = ids_from_files(read_repo(full_name, get))
    changed = []
    if ids["ios"] and not link.app_store_bundle_id:
        link.app_store_bundle_id = ids["ios"]
        changed.append(f"App Store {ids['ios']}")
    if ids["android"] and not link.play_package:
        link.play_package = ids["android"]
        changed.append(f"Google Play {ids['android']}")
    return changed


def main(get=None):
    """Nightly: every tile with a repo and a missing store id."""
    from app import create_app
    from models import db, AppLink
    import store_versions_service
    app = create_app()
    with app.app_context():
        for link in AppLink.query.order_by(AppLink.id).all():
            if not link.github_url or (link.app_store_bundle_id and link.play_package):
                continue
            try:
                changed = fill(link, get)
            except Exception as err:  # noqa: BLE001 - one repo never stops the rest
                print(f"store ids: {link.name}: {str(err)[:160]}", flush=True)
                continue
            if changed:
                store_versions_service.refresh(link)
                db.session.commit()
                print(f"store ids: {link.name}: {', '.join(changed)}", flush=True)
    return 0
