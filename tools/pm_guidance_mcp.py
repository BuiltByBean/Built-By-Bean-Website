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
        "name": "get_blueprint",
        "description": (
            "A whole app the owner has built, end to end: what it is, its "
            "parts, how they talk to each other, the build order with the "
            "playbooks and features each stage needs, what changes per "
            "project, and the traps between systems. Call this at the START "
            "of a new project that resembles one, so the whole plan is lined "
            "up before the first table. With no name it lists them."),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {
                "type": "string",
                "description": "Blueprint name or slug, e.g. entertainhq; empty to list"}},
        },
    },
    {
        "name": "get_icons",
        "description": (
            "The owner's icon vocabulary: one drawing per concept "
            "(notifications, clients, delete, sign out ...), the same in "
            "every project, with the SVG, its library name, other names for "
            "the concept and what it must never be confused with. Call it "
            "before drawing any icon, and use one icon macro that draws from "
            "it. With no concept it gives the whole vocabulary. A concept "
            "that is missing goes in with suggest_update kind icon (payload: "
            "name, group nav|action|status|thing, svg, icon_name, aliases, "
            "used_in_md, never_md) before it is used; a drawing already "
            "standing for another concept is refused."),
        "inputSchema": {
            "type": "object",
            "properties": {"concept": {
                "type": "string",
                "description": "A concept or a word for one, e.g. delete or invoices; empty for all"}},
        },
    },
    {
        "name": "tend_brief",
        "description": (
            "For the Tend run only (.claude/skills/tend): everything Best "
            "Practices upkeep works from, in one read. The notes waiting, the "
            "rule list with where each rule is broken, features, playbooks, "
            "blueprints with their repos and closed gaps, and the repos the "
            "sweeper watches."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "close_note",
        "description": (
            "For the Tend run: mark one waiting note as decided, after you have "
            "folded it into an entry, added an entry from it, or set it aside "
            "as true of one repo only."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "The note's number from tend_brief"},
                "outcome": {"type": "string", "enum": ["folded", "added", "discarded"]},
                "reason": {"type": "string", "description": "One sentence: where it went, or why not"},
            },
            "required": ["id", "outcome"],
        },
    },
    {
        "name": "get_map",
        "description": (
            "A business's map as text: every person, surface, service and "
            "outcome on it with its id, and every line between them with why."),
        "inputSchema": {
            "type": "object",
            "properties": {"business": {"type": "string", "description": "Business slug or name"}},
            "required": ["business"],
        },
    },
    {
        "name": "change_map",
        "description": (
            "Change a business's map with a list of operations, applied all or "
            "nothing and recorded on History with a Revert. Each change is "
            "{op, ...}: add_node {kind (audience, surface, service, outcome), "
            "name, role, status, url, surface_kind, playbook}; update_node "
            "{node (id or name), any of those fields}; remove_node {node}; "
            "add_edge {from, to, why}; remove_edge {from, to}."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "business": {"type": "string"},
                "changes": {"type": "array", "items": {"type": "object"}},
                "reason": {"type": "string", "description": "What in the repo or blueprint says so"},
                "project": {"type": "string", "description": "Who made the change, e.g. tend"},
            },
            "required": ["business", "changes", "project"],
        },
    },
    {
        "name": "file_gaps",
        "description": (
            "File what one app should catch up on, found by comparing it with "
            "the other apps' blueprints. Each gap is {title, detail_md, kind "
            "(gap: another app already does it; enhancement: none do yet), "
            "from (the blueprint that has it)}. A gap Michael closed as done "
            "or not wanted is never reopened."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "blueprint": {"type": "string", "description": "The app that has the gap"},
                "gaps": {"type": "array", "items": {"type": "object"}},
                "project": {"type": "string"},
            },
            "required": ["blueprint", "gaps"],
        },
    },
    {
        "name": "tend_finished",
        "description": (
            "For the Tend run: record the run on the History tab, with counts "
            "of rules added, folded, merged, tightened and retired, notes set "
            "aside, and a short note of what else changed."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "counts": {"type": "object", "description": "{added, folded, merged, tightened, retired, discarded}"},
                "note": {"type": "string"},
            },
            "required": ["counts"],
        },
    },
    {
        "name": "bank_review",
        "description": (
            "For the /bank skill only (.claude/skills/bank): the bank lines no "
            "rule has settled yet, each with the board's own suggestion, plus "
            "the companies, categories, projects, every rule and the recent "
            "lines settled by hand. Read this before bank_decide."),
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "How many lines, newest first (default 150)"}},
        },
    },
    {
        "name": "bank_decide",
        "description": (
            "For the /bank skill: settle waiting bank lines. Each decision is "
            "{id, disposition (expense, personal, contribution, draw, transfer, "
            "income), business_id, category, project_id, vendor, pattern, keep, "
            "owner_name}. With keep and a pattern it becomes a rule, and every "
            "waiting line like it is settled too. Only settle what you are sure of."),
        "inputSchema": {
            "type": "object",
            "properties": {"decisions": {"type": "array", "items": {"type": "object"}}},
            "required": ["decisions"],
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
            "Every mode applies on arrival: APPEND, CREATE, REPLACE, and "
            "RETIRE (switches an entry off; give slug and reason). A nightly "
            "curator merges, tightens and prunes, and any change can be "
            "reverted from the History tab of Best Practices, so write for "
            "any project, not the one you are in. A FEATURE is something a client "
            "would ask for by name, and it is what the MVP Builder picks from "
            "and the client reads: a short plain name (Online booking, not a "
            "sentence and not a lesson) and a one-sentence summary in the "
            "client's words, with the lesson in gold_standard_md or "
            "pitfalls_md. A way of building goes in a RULE instead. Nothing "
            "here carries a price. Fields by kind - feature/rule: name, "
            "summary, category (intake, scheduling, records, money, comms, "
            "documents, portal, platform, ui, classics), gold_standard_md, "
            "pitfalls_md, reference_project, reference_path, and for a rule the "
            "scanner that catches it mechanically: check_pattern (a regex one "
            "line of offending code matches), check_globs (files it applies "
            "to, e.g. templates/**/*.html), check_exclude, check_unless (skip "
            "files mentioning this), check_fixture (a line it MUST match). "
            "playbook: "
            "display_name, one_liner, vendor_url, client_only_md, "
            "access_grant_md, your_steps_md, traps_md, verify_md, and "
            "steps, the numbered checklist under the runbook: pass it as "
            "payload.steps, a list of {title, detail_md, client_channel "
            "(email or text), client_message_subject, client_message_md} "
            "where a step with a client message is one that waits on the "
            "client; append adds steps to the end, replace rewrites the "
            "whole list. product: name, summary, prompt_intro, "
            "playbook_slug. blueprint (a whole app end to end): name, "
            "one_liner, source_repos, shape_md, parts_md, connections_md, "
            "tweaks_md, traps_md, and stages, the build order: "
            "payload.stages, a list of {title, detail_md, playbooks: [names "
            "or slugs], features: [names or slugs]}; a name that matches "
            "nothing is reported back and left out. When you change how an "
            "app with a blueprint is put together, append to it. icon (one "
            "concept of the icon vocabulary, see get_icons): name, group "
            "(nav, action, status or thing), svg (Heroicons outline shapes "
            "in viewBox 0 0 24 24; a drawing another concept already has is "
            "refused), library, icon_name, aliases, used_in_md, never_md; "
            "its slug is the concept. For a "
            "create, put the new entry's fields in payload (name plus any of "
            "the above, steps included for a playbook, stages for a "
            "blueprint)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string",
                         "enum": ["feature", "rule", "playbook", "product", "blueprint", "icon"]},
                "slug": {"type": "string",
                         "description": "The entry's slug (not for create)"},
                "field": {"type": "string",
                          "description": "The field to change (not for create)"},
                "mode": {"type": "string",
                         "enum": ["append", "replace", "create", "retire"]},
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
        "name": "get_costs",
        "description": (
            "What each vendor has actually cost, read only. Use it to CHECK "
            "a money figure on the live board instead of asking Michael to "
            "go and look: a session shipped a wrong Railway total twice and "
            "could not see it, because the admin pages need a login. Read "
            "`source` before quoting any number. \"invoices\" is typed off "
            "the vendor's bill and \"synced\" is read from the vendor's own "
            "billing API - both are the truth. Only \"derived\" is a guess "
            "assembled from the ledger. Do NOT ask him to enter invoices for "
            "a synced vendor; Railway is the only one without a money API "
            "and the only one that is typed in."),
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
            "Tag money spent - a domain bought, a service paid for, an "
            "API credit - with the client and project it was for. It makes "
            "no expense: only the bank line does, and the line for this "
            "charge takes the tag when it arrives (same amount to the cent, "
            "within ten days), so the expense lands on that project."),
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
                "business": {"type": "string",
                             "description": "Whose books: business name or id. "
                                            "Default Built by Bean; EntertainHQ "
                                            "LLC keeps its own"},
                "paid_by": {"type": "string",
                            "description": "An owner who paid it from their own "
                                           "pocket, by name; the books count it "
                                           "as that owner's money put in"},
                "date": {"type": "string", "description": "YYYY-MM-DD, "
                                                          "default today"},
                "source": SOURCE,
            },
            "required": ["amount", "description", "source"],
        },
    },
    {
        "name": "register_hosting_resource",
        "description": (
            "Tell the board about infrastructure just stood up for a client "
            "- a Railway service, a Cloudflare domain, a Twilio number - "
            "mapped to their project, so its cost is held against that "
            "build's hosting fee. Provider is the board's name for the "
            "vendor (railway, cloudflare, twilio...). Pass url (the public "
            "address, once verified) and the same call puts the app on My "
            "Apps; without it the tile is NOT created - the reply says so."),
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
                "url": {"type": "string",
                        "description": "The public address this serves, once "
                                       "verified - creates or updates the My Apps tile"},
                "app_name": {"type": "string",
                             "description": "The tile's name (default: the project)"},
                "github_url": {"type": "string",
                               "description": "owner/repo or the full address"},
                "description": {"type": "string"},
            },
            "required": ["provider", "resource_identifier", "client"],
        },
    },
    {
        "name": "register_app",
        "description": (
            "Put a deployed thing on the board's My Apps page - the moment its "
            "public URL is verified, from the same session that verified it. "
            "Idempotent on the address: a second call edits the tile rather than "
            "duplicating it. Give provider + resource_identifier too and the "
            "hosting mapping is filed in the same call. A build is not stood up "
            "until it is here."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The tile's name"},
                "url": {"type": "string",
                        "description": "The public address, e.g. https://acme.example.com"},
                "client": {"type": "string"},
                "project": {"type": "string"},
                "repo": {"type": "string",
                         "description": "owner/repo on GitHub, or the full address"},
                "description": {"type": "string"},
                "railway_url": {"type": "string",
                                "description": "The deploy that serves it (derived from a "
                                               "Railway project id when omitted)"},
                "provider": {"type": "string",
                             "description": "railway, cloudflare... to file the hosting "
                                            "mapping in the same call"},
                "resource_identifier": {"type": "string",
                                        "description": "The id the provider knows it by"},
                "monthly_cost": {"type": "number"},
                "refresh_icon": {"type": "boolean",
                                 "description": "Fetch the icon again (after a rebrand)"},
            },
            "required": ["name", "url", "client"],
        },
    },
    {
        "name": "retire_app",
        "description": (
            "Take something torn down off the board: the other half of "
            "register_app. By url (the tile's host), name, or railway_project "
            "(the Railway project id): its My Apps tile and site check are "
            "deleted, its hosting mappings switched off (billed months keep "
            "their split), and the board's rows for that Railway project's "
            "services removed. A board project is never touched. Call it the "
            "moment a deploy is deleted. The answer carries each removed tile "
            "whole, enough to register it again."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The tile's public address"},
                "name": {"type": "string", "description": "The tile's name, exactly"},
                "railway_project": {"type": "string",
                                    "description": "The Railway project id (a UUID)"},
                "reason": {"type": "string", "description": "Why it is coming off"},
            },
            "required": ["reason"],
        },
    },
    {
        "name": "get_legal",
        "description": (
            "The Legal library: the laws behind each product's decisions, "
            "with a proof copy of each official document, what the law "
            "requires, the decision and where it is recorded, its status "
            "(backed, gap, needs a lawyer, watch, does not apply), the apps "
            "and the functions and routes it touches, and when it was last "
            "checked. Ask it before building or changing anything that "
            "sends, charges, cancels, deletes, texts, signs or stores "
            "personal data. With gaps=true it answers the gaps per product. "
            "Nothing it returns is legal advice."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words to search: a law, a topic, an app, a decision"},
                "slug": {"type": "string", "description": "One entry's slug, for the whole entry with its sources"},
                "app": {"type": "string", "description": "Only entries that touch this app (its tile's name)"},
                "product": {"type": "string", "description": "Only entries filed by this product, e.g. entertainhq"},
                "status": {"type": "string", "enum": ["backed", "gap", "lawyer", "watch", "not_applicable"]},
                "topic": {"type": "string", "description": "A topic slug: email, texting, billing, renewal, deletion..."},
                "gaps": {"type": "boolean", "description": "true: the gaps view per product instead of the entries"},
            },
        },
    },
    {
        "name": "file_legal",
        "description": (
            "File a product's legal register into the Legal library: the "
            "decisions, each with the law behind it (name, citation, the "
            "official source's id, title, site, URL, the date it was "
            "fetched, its sha256 and where the product's repo keeps the "
            "copy), what it requires, the decision and where it is "
            "recorded, its status, the lawyer's question where it needs "
            "one, the issues, and the apps it touches with their functions "
            "and routes. Applies on arrival; the board then fetches its own "
            "copy of each new source onto its volume. EntertainHQ's "
            "`python scripts/legal_library.py export` prints the exact "
            "shape. Only government sites are accepted as sources."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": SOURCE,
                "product": {"type": "string", "description": "The product's slug, e.g. entertainhq"},
                "entries": {"type": "array", "items": {"type": "object"},
                            "description": "The entries, in the export's shape"},
                "register_json": {"type": "string",
                                  "description": "Alternatively the whole export as a JSON string"},
            },
            "required": ["project"],
        },
    },
    {
        "name": "legal_recheck",
        "description": (
            "Re-check the Legal library's sources: the board fetches every "
            "official document again (or the ones named) and compares it "
            "with its stored copy; each source and entry is stamped with "
            "the result, and the run is kept. Runs on demand now; the "
            "overnight job will call the same code later. Waits up to "
            "`wait` seconds for the run and reports what changed, what was "
            "unreachable and what must be read by hand."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": SOURCE,
                "sources": {"type": "array", "items": {"type": "string"},
                            "description": "Source ids to re-check; empty for every source"},
                "wait": {"type": "integer", "description": "Seconds to wait for the run (default 90, at most 240)"},
            },
            "required": ["project"],
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
    if entry.get("cut"):
        lines.append("  Left short to fit. Search for its slug to read it whole.")
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


def tool_get_blueprint(args):
    name = (args.get("name") or "").strip().lower().replace(" ", "-")
    listing, list_err = _http("GET", "/api/guidance/blueprints")
    if list_err:
        return list_err
    rows = json.loads(listing).get("blueprints", [])
    if not name:
        if not rows:
            return "No blueprints yet."
        return "\n".join(f"{b['slug']}: {b['name']}. {b['one_liner']}" for b in rows)
    slug = next((b["slug"] for b in rows if name in (b["slug"], b["name"].lower().replace(" ", "-"))), name)
    text, err = _http("GET", f"/api/guidance/blueprints/{slug}")
    if err is None:
        return json.loads(text)["blueprint"]
    return f"No blueprint called {name!r}. There are: " + (", ".join(b["slug"] for b in rows) or "none yet")


def tool_get_icons(args):
    concept = (args.get("concept") or "").strip()
    path = "/api/guidance/icons" + (f"?concept={urllib.parse.quote(concept)}" if concept else "")
    text, err = _http("GET", path)
    if err:
        return err
    data = json.loads(text)
    if not data.get("icons"):
        return (f"No icon concept matches {concept!r}. Add it with suggest_update kind icon "
                "before drawing one.")
    head = (f"Every drawing: viewBox {data['viewBox']}, fill none, stroke currentColor, "
            f"stroke-width {data['stroke_width']}, round caps and joins.\n\n")
    return head + data["text"]


def tool_tend_brief(_args):
    text, err = _http("GET", "/api/guidance/tend")
    return err or json.loads(text)["brief"]


def tool_close_note(args):
    note_id = args.get("id")
    data, err = _post(f"/api/guidance/notes/{int(note_id or 0)}", args)
    return err or f"Note #{note_id} closed as {args.get('outcome')}."


def tool_get_map(args):
    slug = (args.get("business") or "").strip().lower().replace(" ", "-")
    text, err = _http("GET", f"/api/guidance/maps/{slug}")
    return err or json.loads(text)["map"]


def tool_change_map(args):
    slug = (args.get("business") or "").strip().lower().replace(" ", "-")
    data, err = _post(f"/api/guidance/maps/{slug}", args)
    if err:
        return err
    return "Applied, with a Revert on History: " + "; ".join(data.get("changed") or [])


def tool_file_gaps(args):
    data, err = _post("/api/guidance/gaps", args)
    if err:
        return err
    return (f"{data.get('blueprint')}: {data.get('added', 0)} new, {data.get('updated', 0)} "
            f"updated, {data.get('left_closed', 0)} left closed as Michael decided.")


def tool_tend_finished(args):
    data, err = _post("/api/guidance/tend/runs", args)
    return err or "Recorded on the History tab."


def tool_bank_review(args):
    limit = int(args.get("limit") or 150)
    text, err = _http("GET", f"/api/guidance/bank/review?limit={limit}")
    if err:
        return err
    data = json.loads(text)
    out = [f"{data['waiting']} lines waiting; {len(data['lines'])} shown, newest first.", "",
           "COMPANIES (id | name | owners):"]
    out += [f"  {c['id']} | {c['name']}" + (f" (DBA of {c['dba_of']})" if c.get("dba_of") else "")
            + f" | {', '.join(c['owners']) or 'none on file'}" for c in data["companies"]]
    out += ["", "CATEGORIES: " + ", ".join(data["categories"]), "",
            "PROJECTS (id | name | client):"]
    out += [f"  {p['id']} | {p['name']} | {p['client']}" for p in data["projects"]]
    out += ["", "RULES ALREADY KNOWN (pattern -> vendor, disposition, company, category):"]
    out += [f"  {r['pattern']} -> {r['vendor']}, {r['disposition']}, {r['business_id']}, {r['category']}"
            + (" (personal cards only)" if r.get("applies_to") == "personal" else "") for r in data["rules"]]
    out += ["", "RECENTLY SETTLED BY HAND, NO RULE (counterparty | amount | as | account):"]
    out += [f"  {s['counterparty']} | {s['amount']:.2f} | {s['disposition']} | {s['account']}"
            for s in data["settled_by_hand"]]
    out += ["", "WAITING (id | date | amount | account | counterparty | bank text | merchant type | pattern hint):"]
    for l in data["lines"]:
        out.append(f"  {l['id']} | {l['date']} | {l['amount']:.2f} | {l['account']} | {l['counterparty']} | "
                   f"{l['bank_text']} | {l['merchant_category']} | {l['pattern_hint']}")
        s = l.get("suggestion")
        if s:
            out.append(f"      board suggests: {s.get('disposition')} / {s.get('vendor')} / company "
                       f"{s.get('business_id')} / {s.get('category')} / pattern '{s.get('pattern') or ''}' "
                       f"({s.get('confidence')}, {s.get('source') or 'earlier'}: {s.get('why')})")
    return "\n".join(out)


def tool_bank_decide(args):
    data, err = _post("/api/guidance/bank/decide", args)
    if err:
        return err
    lines = [f"{r['id']}: " + (r.get("error") or r.get("skipped") or
                               f"{r['settled']}" + (" (rule written)" if r.get("rule") else ""))
             for r in data.get("results", [])]
    return ("\n".join(lines) + f"\n{data.get('settled_alike', 0)} more settled by the rules written. "
            f"{data.get('still_waiting', 0)} still waiting.")


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
    if action in ("pending", "candidate"):
        return (f"Filed for '{data.get('slug')}' as note "
                f"#{data.get('id')}. {data.get('note', '')}")
    if action == "unchanged":
        return f"Nothing to do: {data.get('reason', 'already in the catalogue')}."
    return json.dumps(data)


def tool_get_costs(_args):
    text, err = _http("GET", "/api/guidance/costs")
    if err:
        return err
    lines = []
    for p in json.loads(text).get("providers", []):
        if not p.get("invoice_count") and not p.get("derived_total"):
            continue
        lines.append("%s: $%.2f (%s)" % (
            p.get("display_name") or p.get("name"),
            p.get("lifetime") or 0.0, p.get("source")))
        if p.get("source") == "synced":
            lines.append("    From the vendor's own billing API. Nothing to "
                         "enter and nobody to ask.")
        elif p.get("source") == "derived" and p.get("derived_total"):
            lines.append("    NOT A FACT. Assembled from the ledger, which "
                         "double counts a month written by two things.")
        for inv in p.get("invoices", []):
            lines.append("    %s  $%8.2f  %s" % (
                inv.get("month"), inv.get("amount") or 0.0, inv.get("note") or ""))
        if p.get("invoice_count"):
            lines.append("    %d invoices, $%.2f. The ledger would have said "
                         "$%.2f." % (p["invoice_count"], p.get("invoice_total") or 0.0,
                                     p.get("derived_total") or 0.0))
        missing = p.get("months_not_recorded") or []
        if missing:
            lines.append("    NOT RECORDED: " + ", ".join(missing))
    return "\n".join(lines) or "No vendor has cost anything yet."


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
    if data.get("taken"):
        return (f"Tagged ${data['amount']:,.2f} on {data['date']} (tag {data['id']}): "
                "its bank line was already in and now carries it.")
    return (f"Tagged ${data['amount']:,.2f} on {data['date']} (tag {data['id']}). The bank line "
            "for this charge books the expense when it arrives.")


def _app_line(app):
    icon = {"fetched": "icon fetched", "kept": "icon kept",
            "none": "no icon offered - it shows initials"}.get(app.get("icon"), "")
    return (f"My Apps: {app['action']} tile '{app['name']}' (id {app['id']}) "
            f"at {app['url']}" + (f", {icon}" if icon else "") + ".")


def tool_register_hosting_resource(args):
    data, err = _post("/api/guidance/hosting-resources", args)
    if err:
        return err
    where = f" on {data['project']}" if data.get("project") else ""
    line = (f"{data['action'].capitalize()} {data['provider']} resource for "
            f"{data['client']}{where} (mapping {data['id']}). The hosting "
            "page will hold its cost against the fee.")
    if data.get("app"):
        line += " " + _app_line(data["app"])
    elif data.get("note"):
        line += " NOT on My Apps: " + data["note"] + "."
    return line


def tool_register_app(args):
    data, err = _post("/api/guidance/apps", args)
    if err:
        return err
    line = _app_line(data)
    if data.get("mapping"):
        line += f" Hosting mapping {data['mapping']} filed."
    return line


def tool_retire_app(args):
    data, err = _post("/api/guidance/apps/retire", args)
    if err:
        return err
    apps = data.get("removed_apps") or []
    parts = [("Off My Apps: " + ", ".join(f"{a['name']} ({a['url']})" for a in apps))
             if apps else "No tile matched"]
    if data.get("mappings_switched_off"):
        parts.append(f"{len(data['mappings_switched_off'])} hosting mapping(s) switched off")
    if data.get("railway_rows_removed"):
        parts.append("Railway rows removed: " + ", ".join(data["railway_rows_removed"]))
    return ". ".join(parts) + ". Removed tiles, whole: " + json.dumps(apps)


def tool_get_legal(args):
    if args.get("gaps"):
        text, err = _http("GET", "/api/guidance/legal/gaps")
        if err:
            return err
        return json.loads(text).get("text", text)
    slug = (args.get("slug") or "").strip()
    if slug:
        text, err = _http("GET", "/api/guidance/legal/" + urllib.parse.quote(slug))
        if err:
            return err
        return json.loads(text).get("text", text)
    params = {k: v for k, v in (("q", args.get("query")), ("app", args.get("app")),
                                ("status", args.get("status")), ("product", args.get("product")),
                                ("topic", args.get("topic"))) if v}
    text, err = _http("GET", "/api/guidance/legal" + ("?" + urllib.parse.urlencode(params) if params else ""))
    if err:
        return err
    return json.loads(text).get("text", text)


def tool_file_legal(args):
    body = {"project": args.get("project") or ""}
    if args.get("register_json"):
        try:
            body.update(json.loads(args["register_json"]))
        except ValueError as exc:
            return f"register_json is not JSON: {exc}"
    if args.get("product"):
        body["product"] = args["product"]
    if args.get("entries"):
        body["entries"] = args["entries"]
    if not body.get("entries"):
        return "Give entries (or register_json with them)."
    data, err = _post("/api/guidance/legal", body)
    if err:
        return err
    line = (f"Filed {len(data.get('entries') or [])} entries for {data.get('product')}: {data.get('made')} new, "
            f"{data.get('updated')} updated, {data.get('sources')} sources; copies {data.get('copies')}.")
    if data.get("unmatched_apps"):
        line += " No My Apps tile matched: " + ", ".join(data["unmatched_apps"]) + " (kept by name)."
    return line + " " + data.get("disclaimer", "")


def tool_legal_recheck(args):
    import time as _time
    payload = {"project": args.get("project") or ""}
    if args.get("sources"):
        payload["sources"] = args["sources"]
    data, err = _post("/api/guidance/legal/recheck", payload)
    if err:
        return err
    run = data.get("run") or {}
    run_id = run.get("id")
    wait = min(int(args.get("wait") or 90), 240)
    waited = 0
    while run.get("status") == "running" and waited < wait:
        _time.sleep(5)
        waited += 5
        text, err = _http("GET", f"/api/guidance/legal/checks/{run_id}")
        if err:
            return err
        run = json.loads(text).get("run") or run
    detail = run.get("detail") or {}
    changed = [k for k, v in detail.items() if v.get("status") == "changed"]
    gone = [k for k, v in detail.items() if v.get("status") == "unreachable"]
    hand = [k for k, v in detail.items() if v.get("status") == "by_hand"]
    lines = [f"Re-check {run_id}: {run.get('status')}; {run.get('checked')} checked, {run.get('changed')} changed, "
             f"{run.get('unreachable')} unreachable, {run.get('by_hand')} to read by hand."]
    if run.get("status") == "running":
        lines.append("Still running; ask again with get_legal (gaps=true) or the board's Checks tab.")
    if changed:
        lines.append("CHANGED (read each against its copy and update the entry): " + ", ".join(changed))
    if gone:
        lines.append("Unreachable: " + ", ".join(gone))
    if hand:
        lines.append("Read by hand (the site refuses scripts): " + ", ".join(hand))
    if run.get("note"):
        lines.append(run["note"])
    return "\n".join(lines)


HANDLERS = {
    "get_rules": tool_get_rules,
    "get_feature_guidance": tool_get_feature_guidance,
    "get_playbook": tool_get_playbook,
    "get_blueprint": tool_get_blueprint,
    "get_icons": tool_get_icons,
    "tend_brief": tool_tend_brief,
    "close_note": tool_close_note,
    "get_map": tool_get_map,
    "change_map": tool_change_map,
    "file_gaps": tool_file_gaps,
    "tend_finished": tool_tend_finished,
    "bank_review": tool_bank_review,
    "bank_decide": tool_bank_decide,
    "report_lesson": tool_report_lesson,
    "suggest_update": tool_suggest_update,
    "get_clients": tool_get_clients,
    "get_costs": tool_get_costs,
    "upsert_project": tool_upsert_project,
    "log_expense": tool_log_expense,
    "register_hosting_resource": tool_register_hosting_resource,
    "register_app": tool_register_app,
    "retire_app": tool_retire_app,
    "get_legal": tool_get_legal,
    "file_legal": tool_file_legal,
    "legal_recheck": tool_legal_recheck,
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
