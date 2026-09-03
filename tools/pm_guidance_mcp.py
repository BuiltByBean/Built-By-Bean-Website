"""The bridge between every Claude session and the project manager.

Registered at user scope in Claude Code, so a fresh session in a
brand-new repo carries these tools without any wiring: the rules that
hold on every build, the guidance behind any feature, the vendor
runbooks, the door to report a lesson back - and now the way the
catalogue grows on its own: a session that finds a runbook step has moved
or a better file to copy proposes the change, and the board applies it or
holds it for Michael by the shape of the change. Below that, the
operational writes a session doing real client work needs: the project it
is on, the time and money it spent, the infrastructure it stood up.

The board it talks to is the deployed one, because the live catalogue is
the only copy that every machine and every session agrees on.

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

SERVER_INFO = {"name": "pm-guidance", "version": "2.0.0"}

SOURCE = {
    "type": "string",
    "description": "The project or repo this session is working in - the "
                   "provenance every record carries",
}

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
    {
        "name": "suggest_update",
        "description": (
            "Propose a change to the catalogue itself - a playbook step that "
            "has moved, a feature's gold standard or file worth copying, a "
            "rule whose wording needs work, a product that now exists. "
            "Policy by shape: an APPEND or a CREATE applies on arrival and "
            "can be reverted from the inbox; a REPLACE waits in the inbox "
            "until Michael accepts it and touches no build prompt before "
            "then. Fields by kind - feature/rule: name, summary, "
            "gold_standard_md, pitfalls_md, reference_project, "
            "reference_path, typical_value (feature only). playbook: "
            "display_name, one_liner, vendor_url, client_only_md, "
            "access_grant_md, your_steps_md, traps_md, verify_md. product: "
            "name, summary, prompt_intro, playbook_slug, price, "
            "monthly_price. For a create, put the new entry's fields in "
            "payload (name plus any of the above)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string",
                         "enum": ["feature", "rule", "playbook", "product"]},
                "slug": {"type": "string",
                         "description": "The entry's slug (not for create)"},
                "field": {"type": "string",
                          "description": "The field to change (not for create)"},
                "mode": {"type": "string",
                         "enum": ["append", "replace", "create"]},
                "text": {"type": "string",
                         "description": "The text to append, or the full "
                                        "replacement"},
                "reason": {"type": "string",
                           "description": "Why, in a sentence - what was "
                                          "found that makes this right"},
                "project": {"type": "string",
                            "description": "The project this was learned in"},
                "payload": {"type": "object",
                            "description": "For create: the new entry's fields"},
            },
            "required": ["kind", "mode", "project"],
        },
    },
    {
        "name": "get_clients",
        "description": (
            "Every client on the board and their projects, so time, money "
            "and infrastructure can be filed against the names the board "
            "actually uses. Call before the first log_* of a session."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "upsert_project",
        "description": (
            "File a project against a client, or update its description or "
            "status. Use when a build starts that the board does not know "
            "about yet. Status: active, paused, completed, archived."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "client": {"type": "string",
                           "description": "Client name or id"},
                "name": {"type": "string", "description": "Project name"},
                "description": {"type": "string"},
                "status": {"type": "string"},
                "source": SOURCE,
            },
            "required": ["client", "name", "source"],
        },
    },
    {
        "name": "log_expense",
        "description": (
            "Record money spent - a domain bought, a service paid for, an "
            "API credit - optionally against a client and project so the "
            "hosting page can count it as the cost of running that build."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "In dollars"},
                "description": {"type": "string"},
                "category": {"type": "string",
                             "description": "e.g. software, hosting, domain, "
                                            "api, misc"},
                "client": {"type": "string",
                           "description": "Client name or id, if any"},
                "project": {"type": "string",
                            "description": "Project name or id, if any"},
                "date": {"type": "string", "description": "YYYY-MM-DD, "
                                                          "default today"},
                "source": SOURCE,
            },
            "required": ["amount", "description", "source"],
        },
    },
    {
        "name": "log_time",
        "description": (
            "Record hours worked on a client's project. rate_type: "
            "maintenance (default), new_feature, or mvp_build."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "client": {"type": "string"},
                "project": {"type": "string"},
                "hours": {"type": "number"},
                "description": {"type": "string"},
                "rate_type": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "source": SOURCE,
            },
            "required": ["client", "project", "hours", "source"],
        },
    },
    {
        "name": "register_hosting_resource",
        "description": (
            "Tell the board about infrastructure just stood up for a client "
            "- a Railway service, a Cloudflare domain, a Twilio number - "
            "mapped to their project, so its cost is held against that "
            "build's hosting fee. Provider is the board's name for the "
            "vendor (railway, cloudflare, twilio...)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string"},
                "resource_identifier": {
                    "type": "string",
                    "description": "The id the provider knows it by"},
                "client": {"type": "string"},
                "project": {"type": "string"},
                "label": {"type": "string",
                          "description": "A human name for it"},
                "monthly_cost": {"type": "number",
                                 "description": "If the provider bills flat"},
            },
            "required": ["provider", "resource_identifier", "client"],
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
                 "Content-Type": "application/json",
                 # Named, because Cloudflare's browser integrity check 403s
                 # Python's default urllib agent outright (error 1010) - the
                 # token never even gets looked at. Learned the day this
                 # bridge first called the deployed board.
                 "User-Agent": "pm-guidance-bridge/2.0"},
        data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:500]
        try:
            detail = json.loads(detail).get("error", detail)
        except ValueError:
            pass
        return None, f"the board answered {err.code}: {detail}"
    except Exception as err:  # noqa: BLE001 - the loop must never die
        return None, f"could not reach the board at {BASE}: {err}"


def _post(path, args):
    payload = {k: v for k, v in args.items() if v not in (None, "")}
    text, err = _http("POST", path, payload)
    if err:
        return None, err
    return json.loads(text), None


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
    lines.append(f"  slug: {entry['slug']}")
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
    data, err = _post("/api/guidance/lessons", args)
    if err:
        return err
    action = data.get("action", "?")
    slug = data.get("slug", "?")
    if action == "appended":
        return f"Appended to the catalogue entry '{slug}'."
    if action == "created":
        return (f"Created catalogue entry '{slug}' as a {data.get('kind')}. "
                "Every future build prompt now carries it.")
    return f"Already recorded on '{slug}' - nothing written twice."


def tool_suggest_update(args):
    data, err = _post("/api/guidance/proposals", args)
    if err:
        return err
    action = data.get("action")
    if action == "applied":
        return (f"Applied to '{data.get('slug')}'. {data.get('note', '')}")
    if action == "pending":
        return (f"Filed for '{data.get('slug')}' as proposal "
                f"#{data.get('id')}. {data.get('note', '')}")
    if action == "unchanged":
        return f"Nothing to do: {data.get('reason', 'already in the catalogue')}."
    return json.dumps(data)


def tool_get_clients(_args):
    text, err = _http("GET", "/api/guidance/clients")
    if err:
        return err
    lines = []
    for c in json.loads(text).get("clients", []):
        lines.append(f"{c['name']} (id {c['id']})")
        for p in c.get("projects", []):
            lines.append(f"    - {p['name']} (id {p['id']}, {p['status']})")
    return "\n".join(lines) or "No clients on the board yet."


def tool_upsert_project(args):
    data, err = _post("/api/guidance/projects", args)
    if err:
        return err
    return (f"{data['action'].capitalize()} project '{data['name']}' for "
            f"{data['client']} (id {data['id']}).")


def tool_log_expense(args):
    data, err = _post("/api/guidance/expenses", args)
    if err:
        return err
    return f"Logged ${data['amount']:,.2f} on {data['date']} (expense {data['id']})."


def tool_log_time(args):
    data, err = _post("/api/guidance/time", args)
    if err:
        return err
    billable = data.get("billable") or 0
    return (f"Logged {data['hours']}h on {data['project']} (entry {data['id']}"
            + (f", ${billable:,.2f} billable" if billable else ", not billable")
            + ").")


def tool_register_hosting_resource(args):
    data, err = _post("/api/guidance/hosting-resources", args)
    if err:
        return err
    where = f" on {data['project']}" if data.get("project") else ""
    return (f"{data['action'].capitalize()} {data['provider']} resource for "
            f"{data['client']}{where} (mapping {data['id']}). The hosting "
            "page will hold its cost against the fee.")


HANDLERS = {
    "get_rules": tool_get_rules,
    "get_feature_guidance": tool_get_feature_guidance,
    "get_playbook": tool_get_playbook,
    "report_lesson": tool_report_lesson,
    "suggest_update": tool_suggest_update,
    "get_clients": tool_get_clients,
    "upsert_project": tool_upsert_project,
    "log_expense": tool_log_expense,
    "log_time": tool_log_time,
    "register_hosting_resource": tool_register_hosting_resource,
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
