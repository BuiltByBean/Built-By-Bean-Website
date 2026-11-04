# -*- coding: utf-8 -*-
"""A phone app's store ids come out of its own repo.

Michael, 2026-11-04: EntertainHQ's tile said nothing about Google Play
because its Play id had never been typed. Proves:

  1. The ids parse out of real project files: an Android applicationId, the
     Xcode bundle id (not a test or extension target's), a Capacitor appId
     only for a platform the repo has, and an Expo app.json.
  2. fill() writes only an empty field and reads the repo through GitHub's
     tree and contents calls.
  3. With --repo PATH it parses a local clone, e.g. EntertainHQ's.

Run: python tools/test_store_ids.py [--repo C:/path/to/EntertainHQ]
"""
import base64
import pathlib
import subprocess
import sys
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import store_ids_service as s  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


GRADLE = 'android {\n    namespace = "com.acme.app"\n    defaultConfig {\n        applicationId "com.acme.app"\n'
PBX = ("PRODUCT_BUNDLE_IDENTIFIER = com.acme.app.UITests;\nPRODUCT_BUNDLE_IDENTIFIER = com.acme.app;\n"
       "PRODUCT_BUNDLE_IDENTIFIER = \"com.acme.app.NotificationService\";\nPRODUCT_BUNDLE_IDENTIFIER = $(PRODUCT_NAME);\n")
CAP = "const config = {\n  appId: 'com.acme.cap',\n  appName: 'Acme',\n};"

print("1. Parsing")
check("Android applicationId and the app's own bundle id",
      s.ids_from_files({"android/app/build.gradle": GRADLE, "ios/App/App.xcodeproj/project.pbxproj": PBX})
      == {"ios": "com.acme.app", "android": "com.acme.app"})
check("Kotlin build script", s.ids_from_files({"android/app/build.gradle.kts": 'applicationId = "com.k.app"'})["android"] == "com.k.app")
check("a Capacitor appId only for the platform the repo has",
      s.ids_from_files({"capacitor.config.ts": CAP, "ios/App/Podfile": ""}) == {"ios": "com.acme.cap", "android": None})
check("no platform folder, no store id", s.ids_from_files({"capacitor.config.ts": CAP}) == {"ios": None, "android": None})
check("Expo app.json", s.ids_from_files({"app.json": '{"expo": {"ios": {"bundleIdentifier": "com.e.i"}, '
                                                    '"android": {"package": "com.e.a"}}}'}) == {"ios": "com.e.i", "android": "com.e.a"})

print("2. Filling a tile")
REPO = {"android/app/build.gradle": GRADLE, "ios/App/App.xcodeproj/project.pbxproj": PBX, "README.md": "x"}


def fake_get(path):
    if path == "/repos/BuiltByBean/Acme":
        return {"default_branch": "main"}
    if path.startswith("/repos/BuiltByBean/Acme/git/trees/main"):
        return {"tree": [{"path": p, "type": "blob"} for p in REPO]}
    name = path.split("/contents/", 1)[1]
    return {"content": base64.b64encode(REPO[name].encode()).decode()}


link = SimpleNamespace(github_url="https://github.com/BuiltByBean/Acme", app_store_bundle_id="com.typed.by.hand",
                       play_package=None)
changed = s.fill(link, fake_get)
check("fills the empty Play id", link.play_package == "com.acme.app" and changed == ["Google Play com.acme.app"], changed)
check("and leaves the typed App Store id alone", link.app_store_bundle_id == "com.typed.by.hand")
check("a tile with no repo is left alone", s.fill(SimpleNamespace(github_url=None), fake_get) == [])

if "--repo" in sys.argv:
    print("3. A real clone")
    repo = sys.argv[sys.argv.index("--repo") + 1]
    names = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "--name-only", "origin/main"],
                           capture_output=True, text=True).stdout.split()
    files = {p: "" for p in names if "/ios/" in f"/{p}" or "/android/" in f"/{p}"}
    for p in names:
        if s.WANTED.search(p) and "node_modules/" not in p:
            files[p] = subprocess.run(["git", "-C", repo, "show", f"origin/main:{p}"],
                                      capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    ids = s.ids_from_files(files)
    print("  ", ids)
    check("both stores' ids found", ids["ios"] and ids["android"], ids)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
