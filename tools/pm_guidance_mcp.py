"""The bridge between every Claude session and the project manager.

Registered at user scope in Claude Code, so a fresh session in a
brand-new repo carries these tools without any wiring: the rules that
hold on every build, the guidance behind any feature, the vendor
runbooks, and the door to report a lesson back. The board it talks to is
the deployed one, because the live catalogue is the only copy that every
machine and every session agrees on.

Zero dependencies on purpose - this runs before any project has a venv,
so it can only lean on the standard library. Speaks MCP over stdio:
newline-delimited JSON-RPC, protocol chatter on stdout and nothing else,
diagnostics to stderr.

Environment:
    PM_GUIDANCE_URL   the board (default https://builtbybeans.com)
    PM_GUIDANCE_KEY   the bearer token for /api/guidance
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("PM_GUIDANCE_URL", "https://builtbybeans.com").rstrip("/")
KEY = os.environ.get("PM_GUIDANCE_KEY", "")

SERVER_INFO = {"name": "pm-guidance", "version": "1.0.0"}

TOOLS = [
    {
        "name": "get_rules",
        "description": (
            "The house rules from the Built By Bean project manager: every "
            "way of building that must not be broken, learned across every "
            "past project. Call this BEFORE building UI, forms, migrations, "
            "deploys or anything user-facing, and follow what it says over "
            "habit."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_feature_guidance",
        "description": (
            "Search the project manager's catalogue for how a feature or "
            "pattern should be built: the gold standard, what went wrong "
            "last time, and which past project's file is worth copying. "
            "Call this before building anything that might have been built "
            "before - tagging, booking, sync, auth, uploads, dropdowns."),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {
                "type": "string",
                "description": "What is about to be built, in a few words"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_playbook",
        "description": (
            "The operational runbook for setting up a vendor - Stripe, "
            "Twilio, Railway, Cloudflare and the rest: what only the client "
            "can do, the access to ask for, the steps, the traps, and how "
            "to verify. Call this before any vendor setup."),
        "inputSchema": {
            "type": "object",
            "properties": {"vendor": {
                "type": "string",
                "description": "Vendor name or slug, e.g. stripe"}},
            "required": ["vendor"],
        },
    },
    {
        "name": "report_lesson",
        "description": (
            "File a lesson back to the project manager the moment something "
            "costs real time: what went wrong and the rule that prevents "
            "it. If an existing catalogue entry covers the area, name it "
            "and the lesson is appended; otherwise a new entry is created "
            "and every future build's prompt will carry it."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": ("The entry to append to, or the name "
                                    "for a new one")},
                "what_went_wrong": {
                    "type": "string",
                    "description": ("The failure and the rule that prevents "
                                    "it, in a few sentences")},
                "how_to_build": {
                    "type": "string",
                    "description": "The right way, if it is worth stating"},
                "kind": {
                    "type": "string", "enum": ["rule", "feature"],
                    "description": ("rule for a way of building (default), "
                                    "feature for a sellable capability")},
                "category": {
                    "type": "string",
                    "description": ("One of: intake, scheduling, records, "
                                    "money, comms, documents, portal, "
                                    "platform, ui")},
                "project": {
                    "type": "string",
                    "description": "The project the lesson was learned in"},
                "path": {
                    "type": "string",
                    "description": "File worth copying, if there is one"},
            },
            "required": ["name", "what_went_wrong", "project"],
        },
    },
]


def _http(method, path, payload=None):
    if not KEY:
        return (None, "PM_GUIDANCE_KEY is not set for this MCP server. Tell "
                      "the user: the pm-guidance bridge needs its key - "
                      "re-add it with claude mcp add and the -e flag.")
    req = urllib.request.Request(
        BASE + path, method=method,
        headers={"Authorization": f"Bearer {KEY}",
                 "Content-Type": "application/json"},
        data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:500]
        return None, f"the board answered {err.code}: {detail}"
    except Exception as err:  # noqa: BLE001 - the loop must never die
        return None, f"could not reach the board at {BASE}: {err}"


def _entry_text(entry):
    lines = [f"== {entry['name']} [{entry['kind']}] ({entry['category']})"]
    if entry.get("summary"):
        lines.append(f"  {entry['summary']}")
    if entry.get("how_to_build"):
        lines.append("  How it should be built:")
        lines.extend("    " + l for l in entry["how_to_build"].splitlines())
    if entry.get("what_went_wrong"):
        lines.append("  What went wrong last time:")
        lines.extend("    " + l for l in entry["what_went_wrong"].splitlines())
    if entry.get("worth_copying"):
        lines.append(f"  The one worth copying: {entry['worth_copying']}")
    return "\n".join(lines)


def tool_get_rules(_args):
    text, err = _http("GET", "/api/guidance/brief")
    return err or text


def tool_get_feature_guidance(args):
    query = (args.get("query") or "").strip()
    if not query:
        return "Give a query."
    text, err = _http("GET", "/api/guidance/search?"
                      + urllib.parse.urlencode({"q": query}))
    if err:
        return err
    data = json.loads(text)
    if not data.get("matches"):
        return (f"Nothing in the catalogue matches {query!r}. If this gets "
                "built and teaches a lesson, report_lesson it so the next "
                "build starts warmer.")
    return "\n\n".join(_entry_text(m) for m in data["matches"])


def tool_get_playbook(args):
    vendor = (args.get("vendor") or "").strip().lower().replace(" ", "-")
    if not vendor:
        return "Name a vendor."
    text, err = _http("GET", f"/api/guidance/playbooks/{vendor}")
    if err is None:
        return json.loads(text)["runbook"]
    listing, list_err = _http("GET", "/api/guidance/playbooks")
    if list_err:
        return err
    names = ", ".join(p["slug"] for p in json.loads(listing)["playbooks"])
    return f"No runbook for {vendor!r}. There are runbooks for: {names}"


def tool_report_lesson(args):
    payload = {k: v for k, v in args.items() if v}
    text, err = _http("POST", "/api/guidance/lessons", payload)
    if err:
        return err
    data = json.loads(text)
    action = data.get("action", "?")
    slug = data.get("slug", "?")
    if action == "appended":
        return f"Appended to the catalogue entry '{slug}'."
    if action == "created":
        return (f"Created catalogue entry '{slug}' as a {data.get('kind')}. "
                "Every future build prompt now carries it.")
    return f"Already recorded on '{slug}' - nothing written twice."


HANDLERS = {
    "get_rules": tool_get_rules,
    "get_feature_guidance": tool_get_feature_guidance,
    "get_playbook": tool_get_playbook,
    "report_lesson": tool_report_lesson,
}


def _reply(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            _reply(msg_id, {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            })
        elif method == "tools/list":
            _reply(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            name = params.get("name", "")
            handler = HANDLERS.get(name)
            if handler is None:
                _reply(msg_id, error={"code": -32602,
                                      "message": f"no tool named {name}"})
                continue
            try:
                text = handler(params.get("arguments") or {})
                _reply(msg_id, {"content": [{"type": "text", "text": text}],
                                "isError": False})
            except Exception as err:  # noqa: BLE001 - report, never die
                _reply(msg_id, {"content": [{"type": "text",
                                             "text": f"tool failed: {err}"}],
                                "isError": True})
        elif method == "ping":
            _reply(msg_id, {})
        elif msg_id is not None:
            _reply(msg_id, error={"code": -32601,
                                  "message": f"unknown method {method}"})
        # Notifications (no id) that we do not care about fall through.


if __name__ == "__main__":
    main()
