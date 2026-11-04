# -*- coding: utf-8 -*-
"""Time logs itself from the sessions that did the work (audit item 3).

  1. The hook reads a transcript into stretches: a gap over fifteen minutes
     ends one, and the hours are the stretches added up.
  2. It knows a real log_time CALL from the tool's name written in text, and
     skips a session that logged its own hours.
  3. The board maps the repo to a project (Project.repo, then a tile's
     github_url), picks the rate from the phase, and logs it.
  4. The same session again corrects its entry, never adds one.
  5. Two sessions side by side on one project bill the shared hour once.
  6. His own products are never logged: his own client row, a personal tile.
  7. A repo with no project logs nothing; an invoiced entry is never touched.
  8. The real hook script, run as Claude Code runs it, posts to a live server
     and the entry appears; and the installer puts it on SessionEnd.

Run: python tools/test_session_time.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "hooks"))
TMP = tempfile.mkdtemp(prefix="board-session-time-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["GUIDANCE_API_KEY"] = "test-key"
os.environ["SIGNATURE_REFRESH_SECONDS"] = "0"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, AppLink, Client, Invoice, InvoiceLineItem, Project,  # noqa: E402
                    TimeEntry, User)
import session_end  # noqa: E402

application = create_app()
application.config["GUIDANCE_API_KEY"] = "test-key"
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


T0 = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)


def at(minutes):
    return (T0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def line(minutes, kind="assistant", content=None, **extra):
    row = {"type": kind, "timestamp": at(minutes),
           "message": {"content": content if content is not None else "working"}}
    row.update(extra)
    return json.dumps(row)


print("1. STRETCHES FROM A TRANSCRIPT")
# 0 to 40 in five-minute steps, then an hour away, then 100 to 120.
lines = [line(0, "user", "Build the dispatch board for Acme")]
lines += [line(m) for m in range(5, 41, 5)]
lines += [line(m) for m in (100, 110, 120)]
spans, prompt, logged = session_end.read_session(lines)
check("two stretches", len(spans) == 2, spans)
hours = sum((e - s).total_seconds() for s, e in spans) / 3600
check("an hour of work, not two", abs(hours - 1.0) < 1e-9, hours)
check("the first prompt names it", prompt.startswith("Build the dispatch board"), prompt)

print("2. A REAL CALL, NOT A MENTION")
mention = lines + [line(121, content="call mcp__pm-guidance__log_time later")]
check("a mention is not a call", session_end.read_session(mention)[2] is False)
called = lines + [line(122, content=[{"type": "tool_use", "name": "mcp__pm-guidance__log_time",
                                       "input": {}}])]
check("a tool_use is", session_end.read_session(called)[2] is True)
body, why = session_end.build({"session_id": "x", "cwd": TMP}, called)
check("and the hook then logs nothing", body is None and "logged its own" in why, why)
short = [line(0), line(2)]
check("two minutes is not work", session_end.build({"session_id": "y", "cwd": TMP}, short)[0] is None)

with application.app_context():
    db.create_all()
    db.session.add(User(username="Mbean", email="mb@example.test", first_name="Michael",
                        last_name="Bean", role="ceo", password_hash="x"))
    kenali = Client(name="Kenali Kendrick", email="k@example.test")
    cason = Client(name="Cason Kuper", email="c@example.test")
    mine = Client(name="Michael Bean", email="michael@example.test")
    db.session.add_all([kenali, cason, mine])
    db.session.flush()
    tb = Project(client_id=kenali.id, name="Talent Booker", repo="BuiltByBean/Talent-Booker",
                 phase="mvp")
    kuper = Project(client_id=cason.id, name="Kuper Plumbing", phase="in_production",
                    go_live_date=date(2026, 9, 1))
    ehq = Project(client_id=mine.id, name="EntertainHQ", repo="BuiltByBean/EntertainHQ")
    piped = Project(client_id=kenali.id, name="Side thing", repo="BuiltByBean/piped")
    db.session.add_all([tb, kuper, ehq, piped])
    db.session.flush()
    db.session.add_all([
        AppLink(name="Kuper Plumbing", url="https://kuper.test", project_id=kuper.id,
                github_url="https://github.com/BuiltByBean/KuperPlumbing"),
        AppLink(name="Piped", url="https://piped.test", project_id=piped.id,
                board_group="mine"),
    ])
    db.session.commit()
    ids = dict(tb=tb.id, kuper=kuper.id, ehq=ehq.id)

c = application.test_client()
AUTH = {"Authorization": "Bearer test-key"}


def send(ref, repo, spans, **extra):
    body = {"session_ref": ref, "repo": repo, "folder": repo.split("/")[-1],
            "spans": [[at(a), at(b)] for a, b in spans], "date": "2026-11-03",
            "description": "Build the dispatch board", "source": "test"}
    body.update(extra)
    r = c.post("/api/guidance/time", json=body, headers=AUTH)
    return r.status_code, r.get_json()


print("3. THE REPO NAMES THE PROJECT")
code, ans = send("s1", "git@github.com:BuiltByBean/Talent-Booker.git", [(0, 40), (100, 120)])
check("logged", code == 200 and ans.get("action") == "logged", ans)
check("an hour", ans.get("hours") == 1.0, ans)
check("against Talent Booker", ans.get("project") == "Talent Booker", ans)
check("at the build rate before go-live", ans.get("rate_type") == "mvp_build", ans)
code, ans = send("k1", "https://github.com/BuiltByBean/KuperPlumbing", [(0, 30)])
check("a tile's github_url finds Kuper", ans.get("project") == "Kuper Plumbing", ans)
check("live, so maintenance", ans.get("rate_type") == "maintenance", ans)

print("4. THE SAME SESSION CORRECTS ITSELF")
code, ans = send("s1", "BuiltByBean/Talent-Booker", [(0, 40), (100, 150)])
check("corrected, not added", ans.get("action") == "corrected", ans)
with application.app_context():
    rows = TimeEntry.query.filter_by(session_ref="s1").all()
    check("still one entry", len(rows) == 1, len(rows))
    check("now an hour and a half", rows and rows[0].hours == 1.5, rows and rows[0].hours)

print("5. SIDE BY SIDE IS BILLED ONCE")
code, ans = send("s2", "BuiltByBean/Talent-Booker", [(20, 80)])
check("only the twenty minutes s1 did not have", ans.get("hours") == round(40 / 60, 2), ans)
code, ans = send("s3", "BuiltByBean/Talent-Booker", [(10, 30)])
check("wholly covered time writes nothing", ans.get("action") == "skipped", ans)
with application.app_context():
    check("no row for it", TimeEntry.query.filter_by(session_ref="s3").count() == 0)

print("6. HIS OWN IS NEVER LOGGED")
code, ans = send("e1", "BuiltByBean/EntertainHQ", [(0, 60)])
check("EntertainHQ is skipped", ans.get("action") == "skipped" and "own" in ans.get("reason", ""), ans)
code, ans = send("p1", "BuiltByBean/piped", [(0, 60)])
check("a personal tile is skipped", ans.get("action") == "skipped" and "personal" in ans.get("reason", ""), ans)
with application.app_context():
    check("nothing on his own project", TimeEntry.query.filter_by(project_id=ids["ehq"]).count() == 0)

print("7. NO PROJECT, NO ROW; INVOICED STAYS PUT")
code, ans = send("b1", "BuiltByBean/Built-By-Bean-Website", [(0, 60)])
check("the board's own repo logs nothing", ans.get("action") == "skipped", ans)
with application.app_context():
    entry = TimeEntry.query.filter_by(session_ref="k1").one()
    inv = Invoice(client_id=entry.client_id)
    db.session.add(inv)
    db.session.flush()
    db.session.add(InvoiceLineItem(invoice_id=inv.id, time_entry_id=entry.id))
    db.session.commit()
code, ans = send("k1", "BuiltByBean/KuperPlumbing", [(0, 90)])
check("an invoiced entry is left alone", ans.get("action") == "unchanged", ans)
code, ans = send("", "BuiltByBean/KuperPlumbing", [(0, 90)])
check("no session ref goes the old way and is refused for want of a client", code == 400, (code, ans))

print("8. THE REAL HOOK, AS CLAUDE CODE RUNS IT")
from werkzeug.serving import make_server  # noqa: E402

server = make_server("127.0.0.1", 0, application, threaded=True)
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_port

# A repo of its own with a GitHub remote, so the hook's git lookups are real.
repo_dir = pathlib.Path(TMP) / "Talent-Booker"
repo_dir.mkdir()
subprocess.run(["git", "init", "-q", str(repo_dir)], check=True)
subprocess.run(["git", "-C", str(repo_dir), "remote", "add", "origin",
                "https://github.com/BuiltByBean/Talent-Booker.git"], check=True)
transcript = pathlib.Path(TMP) / "session.jsonl"
transcript.write_text("\n".join([line(300, "user", "Fix the roster export")]
                                + [line(m) for m in range(305, 331, 5)]), encoding="utf-8")
home = pathlib.Path(TMP) / "home"
home.mkdir()
env = dict(os.environ, PM_GUIDANCE_URL=f"http://127.0.0.1:{port}", PM_GUIDANCE_KEY="test-key",
           HOME=str(home), USERPROFILE=str(home))
run = subprocess.run([sys.executable, str(ROOT / "tools" / "hooks" / "session_end.py")],
                     input=json.dumps({"session_id": "hook-1", "transcript_path": str(transcript),
                                       "cwd": str(repo_dir), "hook_event_name": "SessionEnd"}),
                     capture_output=True, text=True, env=env, timeout=60)
check("the hook exits cleanly", run.returncode == 0, run.stderr)
check("and says nothing to a session that has ended", run.stdout == "", run.stdout)
log = (home / ".claude" / "pm-guidance" / "session-time.log")
check("it writes what happened to its log", log.exists() and '"logged"' in log.read_text(encoding="utf-8"),
      log.read_text(encoding="utf-8") if log.exists() else "no log")
with application.app_context():
    entry = TimeEntry.query.filter_by(session_ref="hook-1").one_or_none()
    check("the entry is on the board", entry is not None)
    check("half an hour against Talent Booker",
          entry is not None and entry.hours == 0.5 and entry.project_id == ids["tb"],
          entry and (entry.hours, entry.project_id))
    check("described by the session's first prompt",
          entry is not None and "Fix the roster export" in entry.description)
server.shutdown()

import install  # noqa: E402
os.environ["HOME"] = os.environ["USERPROFILE"] = str(home)
install.main()
settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
end_hooks = settings.get("hooks", {}).get("SessionEnd", [])
check("the installer puts it on SessionEnd",
      any("session_end.py" in h["command"] for e in end_hooks for h in e["hooks"]), end_hooks)
check("next to the other three",
      all(k in settings["hooks"] for k in ("SessionStart", "PostToolUse", "Stop")))

print()
if FAIL:
    print(f"{len(FAIL)} FAILED: " + ", ".join(FAIL))
    sys.exit(1)
print("all passed")
