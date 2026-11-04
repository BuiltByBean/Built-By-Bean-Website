"""Best Practices tends itself. Run nightly, after the repo sweep.

    python curate_practices.py

Michael, 2026-11-02: "stop this waiting on a yes thing. Just have it adjust
properly over time. Think of this best practices as Claude learning how I
like things done and how I like to build, functionally and visually. It
should evolve and adjust, add new, delete or prune, over the years to come,
based on my core projects' repos."

What had happened without this: every session filed what it learned and
nothing ever took anything away, so the rules reached 485, the brief every
session is handed at start reached 986KB (which Claude Code then cut to a
2KB preview), and 188 rewrites and swept notes sat waiting on a press
nobody was going to make one at a time. A catalogue that only grows is not
learning; it is hoarding.

So each night Claude reads it as an editor would:

  1. NOTES. Every candidate (a section the sweeper read in a core repo's
     CLAUDE.md, or an older proposal that used to wait) becomes a new rule
     written for any project, an addition to the rule it belongs to, a
     change applied as proposed, or nothing, because it was only true of
     that one repo.
  2. PLAN. The whole rule list, one line each, with where each rule came
     from and how many core repos still break it, is read for rules that
     say the same thing (merge), rules that are too long to be read
     (tighten), and rules that no longer earn a place (retire: true of one
     repo or vendor, superseded, contradicted by something Michael said
     later, or a thing nobody would get wrong).
  3. REWRITE. Each merge and tighten is rewritten from the full text of the
     rules involved, and what a merge absorbs is retired with a pointer.

Every change goes through the same door a session uses, attributed to
"curator", so each one is on the History tab with a Revert, and a retired
rule is switched off rather than deleted. Each night is capped, so a bad
night is a small night, and the list converges over a week or two rather
than being rewritten in one pass.

ANTHROPIC_API_KEY on the cost-sync service turns it on. Without one the
run is recorded as skipped, and the candidates simply wait for the first
night that has one.
"""
import json
import os
import sys
from datetime import datetime, timezone

MODEL = os.environ.get("CURATOR_MODEL", "claude-opus-5-5")
# Where the list should settle. Not a quota: a rule that earns its place
# stays. It is the size at which the one-line index still fits the context
# a session start keeps (guidance_routes.INDEX_BUDGET).
TARGET_RULES = int(os.environ.get("CURATOR_TARGET", "120"))
NOTES_PER_NIGHT = 90
NOTES_PER_CALL = 15
MAX_MERGES = 15
MAX_RETIRES = 25
MAX_TIGHTEN = 15
EDITS_PER_CALL = 5
NOTE_CHARS = 4000
CURATOR = "curator"

SYSTEM = """You are the editor of Best Practices: the rules Michael Bean's \
software is built by. Michael runs Built by Bean, a one-person software \
studio, and builds several products of his own (EntertainHQ, Talent Booker, \
Data Dungeon and others). Every Claude session that works in any of his \
repos is handed this list before it builds, and every MVP build prompt \
carries it. It is how Claude learns how he likes things done: how he \
builds functionally, and how he likes things to look and behave.

What a rule is. A way of building that holds across his projects whatever \
the product: a name that states the claim ("Numbers wear their commas"), \
a one-line summary of what it covers, how to build it right, and what went \
wrong when it was not. A lesson true of one repo's own code, or one \
vendor's setup screens, is not a rule: the first belongs in that repo's \
CLAUDE.md and the second in a playbook.

How to edit.
- Prefer folding into an existing rule over adding one. Two rules saying \
the same thing in different words is the commonest fault in this list.
- Write for any project, in Michael's plain voice: short sentences, \
concrete, no jargon for its own sake, and never an em dash.
- "How to build it" is imperative and short: what to do, the way a senior \
engineer would say it to a new one.
- "What went wrong" keeps the incidents that teach: what happened, why it \
was easy to do, the check that catches it. Condense; drop dates and \
project names unless they carry the lesson. Never invent an incident.
- What Michael said himself outranks what a session inferred, and \
something he said later outranks something he said earlier.
- Retire a rule only when it is a duplicate (merge it instead), only true \
of one repo or vendor, superseded or contradicted by a newer rule or by \
Michael, or a thing no competent builder would get wrong. A rule that core \
repos still break is alive.
- Doing nothing is a fine answer. Never change a rule just to have \
changed it."""

CATEGORIES = ["intake", "scheduling", "records", "money", "comms",
              "documents", "portal", "platform", "ui", "classics"]


def _obj(props, required=None):
    return {"type": "object", "properties": props,
            "required": required or list(props), "additionalProperties": False}


_S = {"type": "string"}
NOTES_SCHEMA = _obj({"decisions": {"type": "array", "items": _obj({
    "id": {"type": "integer"},
    "action": {"type": "string", "enum": ["discard", "create", "add_to", "apply"]},
    "slug": _S, "name": _S, "summary": _S,
    "category": {"type": "string", "enum": CATEGORIES},
    "how_to_build": _S, "what_went_wrong": _S, "why": _S,
})}})
PLAN_SCHEMA = _obj({
    "merges": {"type": "array", "items": _obj({
        "keep": _S, "absorb": {"type": "array", "items": _S}, "why": _S})},
    "tighten": {"type": "array", "items": _obj({"slug": _S, "why": _S})},
    "retire": {"type": "array", "items": _obj({"slug": _S, "why": _S})},
})
REWRITE_SCHEMA = _obj({"rules": {"type": "array", "items": _obj({
    "slug": _S, "name": _S, "summary": _S,
    "gold_standard_md": _S, "pitfalls_md": _S,
})}})


class CuratorError(Exception):
    pass


def _client():
    import anthropic
    return anthropic.Anthropic(max_retries=4, timeout=900)


def ask(client, run, prompt, schema, max_tokens=48000):
    """One request, its JSON parsed. Streamed, because a rewrite of five
    long rules can run past a non-streaming request's timeout."""
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=[{"type": "text", "text": SYSTEM,
                 "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": "high",
                       "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        message = stream.get_final_message()
    usage = message.usage
    run.input_tokens += (usage.input_tokens or 0) \
        + (getattr(usage, "cache_read_input_tokens", 0) or 0) \
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
    run.output_tokens += usage.output_tokens or 0
    if message.stop_reason == "refusal":
        raise CuratorError("the model declined")
    if message.stop_reason == "max_tokens":
        raise CuratorError("the answer ran past max_tokens")
    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except ValueError as err:
        raise CuratorError(f"unreadable answer: {err}") from err


# ── What the model is shown ──────────────────────────────


def _active_rules():
    from models import Feature
    return (Feature.query.filter_by(is_active=True, kind="rule")
            .order_by(Feature.sort_order, Feature.name).all())


def _broken_in():
    """{rule id: number of repos the nightly audit found breaking it}."""
    from models import db, RuleAudit
    rows = (db.session.query(RuleAudit.rule_id, db.func.count(RuleAudit.id))
            .filter(RuleAudit.violations > 0).group_by(RuleAudit.rule_id).all())
    return dict(rows)


def _one_line(text, bound):
    text = " ".join((text or "").split())
    return text if len(text) <= bound else text[:bound - 3] + "..."


def rule_index(rules, broken=None):
    broken = broken or {}
    out = []
    for r in rules:
        size = len(r.gold_standard_md or "") + len(r.pitfalls_md or "")
        bits = [r.slug, r.name, _one_line(r.summary, 160), f"{size:,} chars",
                f"from {r.reference_project or 'unknown'}",
                (r.created_at.strftime("%Y-%m") if r.created_at else "?")]
        if broken.get(r.id):
            bits.append(f"broken in {broken[r.id]} repos")
        if r.check_pattern:
            bits.append("has a scanner")
        out.append(" | ".join(bits))
    return "\n".join(out)


def _features_index():
    from models import Feature
    rows = (Feature.query.filter_by(is_active=True, kind="feature")
            .order_by(Feature.name).all())
    return "\n".join(f"{f.slug} | {f.name}" for f in rows)


def note_text(p):
    """A candidate as the model reads it."""
    payload = {}
    if p.payload_json:
        try:
            payload = json.loads(p.payload_json)
        except ValueError:
            payload = {}
    if p.mode == "create":
        body = (payload.get("what_went_wrong") or payload.get("pitfalls_md")
                or payload.get("how_to_build") or "")
        head = f"A section headed {payload.get('name') or payload.get('display_name')!r}"
    else:
        body = p.proposed or ""
        head = f"A proposed {p.mode} of {p.field} on the {p.kind} [{p.target_slug}]"
    body = body[:NOTE_CHARS]
    return (f"NOTE #{p.id} from {p.project or 'a session'}"
            f"{' (' + p.reason + ')' if p.reason else ''}\n{head}:\n{body}")


def full_rule(r):
    return (f"[{r.slug}] {r.name}\nSummary: {r.summary or ''}\n"
            f"From: {r.reference_project or 'unknown'}\n"
            f"How to build it:\n{r.gold_standard_md or '(nothing)'}\n"
            f"What went wrong:\n{r.pitfalls_md or '(nothing)'}")


# ── Doing it ─────────────────────────────────────────────


def _change(run, kind, slug, field, mode, text, reason, project=CURATOR, payload=None):
    from pm.guidance_routes import _propose
    result, status = _propose(kind=kind, slug=slug, field=field, mode=mode,
                              text=text, reason=reason[:1000], project=project,
                              payload=payload)
    return status == 200 and result.get("action") == "applied", result


def _decide(p, status, reason=""):
    from models import db
    p.status = status
    p.decided_at = datetime.now(timezone.utc)
    if reason:
        p.reason = ((p.reason or "") + f" Curator: {reason}").strip()[:4000]
    db.session.commit()


def _repo_of(p):
    project = p.project or ""
    return project.replace(" (swept)", "") if project else CURATOR


def _overtaken(p):
    """A held rewrite of a field that has changed since it was written.

    A replace is the whole field and `apply` writes it exactly as it was filed,
    so one that sat for days carries none of what arrived after it, and applying
    it deletes all of that with History reading as if a rule had been improved.
    On 2026-11-04 twenty-two runbook rewrites from three days earlier were in this
    queue, written before sessions had filed new lessons on the same fields. An
    append adds to whatever is there and is never overtaken.
    """
    from models import CatalogueProposal as C
    if p.mode != "replace":
        return False
    return C.query.filter(
        C.id != p.id, C.kind == p.kind, C.target_slug == p.target_slug,
        C.field == p.field, C.status.in_(("applied", "accepted")),
        C.decided_at >= p.created_at).first() is not None


OVERTAKEN = "the field has changed since this was written; applying it would delete what came after"


def handle_notes(client, run, log):
    from models import db, CatalogueProposal, Feature
    from pm.guidance_routes import apply_proposal
    held = (CatalogueProposal.query.filter_by(status="candidate")
            .order_by(CatalogueProposal.created_at, CatalogueProposal.id)
            .limit(NOTES_PER_NIGHT).all())
    notes = []
    for p in held:
        if _overtaken(p):
            _decide(p, "discarded", OVERTAKEN)
            run.discarded += 1
            log.append(f"set aside #{p.id}: {p.target_slug} {p.field} has moved")
        else:
            notes.append(p)
    for start in range(0, len(notes), NOTES_PER_CALL):
        batch = notes[start:start + NOTES_PER_CALL]
        by_id = {p.id: p for p in batch}
        prompt = (
            "These notes arrived since last night. Decide each one.\n"
            "- discard: only true of the repo it came from, already said by "
            "a rule, or not a lesson.\n"
            "- add_to: it belongs in an existing rule (slug) or how-to; put "
            "only what is NEW in how_to_build and what_went_wrong, condensed, "
            "and leave the other fields empty.\n"
            "- create: a way of building that holds across projects and no "
            "rule covers. Write the whole rule for any project.\n"
            "- apply: a proposed change to an entry that is right as it "
            "stands; it is applied exactly as proposed.\n"
            "Fill every field; use empty strings where a field does not "
            "apply. `why` is one short sentence.\n\n"
            f"THE RULES NOW (slug | name | summary | size | from | added | "
            f"evidence):\n{rule_index(_active_rules(), _broken_in())}\n\n"
            f"THE HOW-TOS (slug | name):\n{_features_index()}\n\n"
            "THE NOTES:\n\n" + "\n\n".join(note_text(p) for p in batch))
        answer = ask(client, run, prompt, NOTES_SCHEMA)
        for d in answer.get("decisions", []):
            p = by_id.pop(d.get("id"), None)
            if p is None:
                continue
            action, why = d.get("action"), _one_line(d.get("why"), 300)
            if action == "apply" and p.mode != "create":
                # Again here: an earlier decision tonight can have moved it.
                if _overtaken(p):
                    _decide(p, "discarded", OVERTAKEN)
                    run.discarded += 1
                    continue
                ok, message = apply_proposal(p)
                if ok:
                    p.project = f"{p.project} (curated)"[:120]
                    _decide(p, "applied", why)
                    run.folded += 1
                    log.append(f"applied #{p.id} to {p.target_slug}")
                else:
                    db.session.rollback()
                    _decide(p, "discarded", f"could not apply: {message}")
                    run.discarded += 1
                continue
            if action == "add_to":
                target = Feature.query.filter_by(slug=d.get("slug"), is_active=True).first()
                if target is None:
                    action = "create" if d.get("name") else "discard"
                else:
                    did = False
                    for field, text in (("gold_standard_md", d.get("how_to_build")),
                                        ("pitfalls_md", d.get("what_went_wrong"))):
                        if (text or "").strip():
                            ok, _ = _change(run, target.kind, target.slug, field,
                                            "append", text.strip(), why,
                                            project=f"{CURATOR}, from {_repo_of(p)}")
                            did = did or ok
                    _decide(p, "curated" if did else "discarded", why)
                    if did:
                        run.folded += 1
                        log.append(f"folded #{p.id} into {target.slug}")
                    else:
                        run.discarded += 1
                    continue
            if action == "create" and (d.get("name") or "").strip():
                ok, result = _change(
                    run, "rule", "", "*", "create", "", why,
                    project=f"{CURATOR}, from {_repo_of(p)}",
                    payload={"name": d["name"].strip(), "summary": d.get("summary"),
                             "category": d.get("category"),
                             "how_to_build": d.get("how_to_build"),
                             "what_went_wrong": d.get("what_went_wrong"),
                             "reference_project": _repo_of(p)})
                if ok:
                    p.target_slug = result.get("slug")
                    _decide(p, "curated", why)
                    run.added += 1
                    log.append(f"added {result.get('slug')} from #{p.id}")
                    continue
                why = f"{why} (not added: {result.get('error') or result.get('reason')})"
            _decide(p, "discarded", why)
            run.discarded += 1
        # A note the answer skipped stays a candidate for tomorrow.


def plan(client, run, rules):
    count = len(rules)
    prompt = (
        f"There are {count} rules. The list reads best at about "
        f"{TARGET_RULES} or fewer, but no rule that earns its place goes to "
        "make a number. Read the whole list and say, for tonight:\n"
        f"- merges (at most {MAX_MERGES}): groups that say the same thing or "
        "one thing in parts. `keep` is the slug that survives, `absorb` the "
        "slugs folded into it.\n"
        f"- tighten (at most {MAX_TIGHTEN}): rules whose text is far longer "
        "than what they teach. Look at the size column.\n"
        f"- retire (at most {MAX_RETIRES}): rules that no longer earn a place, "
        "for the reasons in your instructions.\n"
        "A slug appears in at most one of these. Empty lists are a fine "
        "answer. `why` is one short sentence.\n\n"
        "THE RULES (slug | name | summary | size | from | added | evidence):\n"
        + rule_index(rules, _broken_in()))
    answer = ask(client, run, prompt, PLAN_SCHEMA, max_tokens=24000)
    live = {r.slug for r in rules}
    used = set()
    merges, tighten, retire = [], [], []
    for m in answer.get("merges", [])[:MAX_MERGES]:
        keep = m.get("keep")
        absorb = [s for s in dict.fromkeys(m.get("absorb") or [])
                  if s in live and s != keep and s not in used]
        if keep in live and keep not in used and absorb:
            used.update([keep, *absorb])
            merges.append({"keep": keep, "absorb": absorb, "why": m.get("why", "")})
    for t in answer.get("tighten", [])[:MAX_TIGHTEN]:
        if t.get("slug") in live and t["slug"] not in used:
            used.add(t["slug"])
            tighten.append(t)
    for r in answer.get("retire", [])[:MAX_RETIRES]:
        if r.get("slug") in live and r["slug"] not in used:
            used.add(r["slug"])
            retire.append(r)
    return merges, tighten, retire


SCANNER = ("check_pattern", "check_globs", "check_exclude", "check_unless",
           "check_fixture")


def rewrite(client, run, jobs, log):
    """jobs: [{"keep": slug, "absorb": [slugs], "why": str}]; a tighten is a
    job with nothing to absorb."""
    from models import Feature
    for start in range(0, len(jobs), EDITS_PER_CALL):
        batch = jobs[start:start + EDITS_PER_CALL]
        rows = {j["keep"]: Feature.query.filter_by(slug=j["keep"]).first() for j in batch}
        parts = []
        for j in batch:
            keep = rows[j["keep"]]
            if j["absorb"]:
                others = [Feature.query.filter_by(slug=s).first() for s in j["absorb"]]
                parts.append(f"MERGE into [{keep.slug}] ({j['why']}):\n\n"
                             + "\n\n".join(full_rule(r) for r in [keep, *others] if r))
            else:
                parts.append(f"TIGHTEN [{keep.slug}] ({j['why']}):\n\n{full_rule(keep)}")
        prompt = (
            "Rewrite each rule below as one rule, under the slug it names. "
            "For a merge, the result says everything the rules being merged "
            "taught, once. For a tighten, the same lesson in far fewer words. "
            "Keep the incidents that teach, condensed. The name states the "
            "claim; the summary is one line under 120 characters.\n\n"
            + "\n\n----------\n\n".join(parts))
        answer = ask(client, run, prompt, REWRITE_SCHEMA)
        for out in answer.get("rules", []):
            job = next((j for j in batch if j["keep"] == out.get("slug")), None)
            keep = rows.get(out.get("slug"))
            if job is None or keep is None:
                continue
            if not ((out.get("gold_standard_md") or "").strip()
                    or (out.get("pitfalls_md") or "").strip()):
                continue
            why = _one_line(job["why"], 300)
            for field in ("name", "summary", "gold_standard_md", "pitfalls_md"):
                new = (out.get(field) or "").strip()
                if new and new != (getattr(keep, field) or "").strip():
                    _change(run, "rule", keep.slug, field, "replace", new, why)
            for slug in job["absorb"]:
                other = Feature.query.filter_by(slug=slug).first()
                if other is None:
                    continue
                for field in SCANNER:
                    if getattr(other, field) and not getattr(keep, field):
                        _change(run, "rule", keep.slug, field, "replace",
                                getattr(other, field), f"Scanner kept from {slug}")
                _change(run, "rule", slug, "*", "retire", "",
                        f"Merged into {keep.slug}. {why}")
            if job["absorb"]:
                run.merged += 1
                log.append(f"merged {', '.join(job['absorb'])} into {keep.slug}")
            else:
                run.tightened += 1
                log.append(f"tightened {keep.slug}")


def curate(app, client=None):
    """One night. Returns the CuratorRun's id (the row itself belongs to a
    session that closes with the app context)."""
    from models import db, CuratorRun
    with app.app_context():
        run = CuratorRun(model=MODEL, status="running")
        db.session.add(run)
        run.rules_before = len(_active_rules())
        db.session.commit()
        if client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                run.status = "skipped"
                run.note = "No ANTHROPIC_API_KEY on the cost-sync service."
                run.finished_at = datetime.now(timezone.utc)
                run.rules_after = run.rules_before
                db.session.commit()
                print("curator skipped: no ANTHROPIC_API_KEY", flush=True)
                return run.id
            client = _client()
        log, failures = [], []
        for name, step in (("notes", lambda: handle_notes(client, run, log)),
                           ("plan", lambda: _plan_and_do(client, run, log))):
            try:
                step()
            except Exception as err:  # noqa: BLE001 - one step never stops the other
                db.session.rollback()
                failures.append(f"{name}: {str(err)[:200]}")
                print(f"curator {name} failed: {str(err)[:300]}", flush=True)
        run.rules_after = len(_active_rules())
        run.status = "failed" if len(failures) == 2 else ("partial" if failures else "ok")
        run.note = "\n".join(failures + log)[:20000]
        run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        print(f"curator {run.status}: {run.added} added, {run.folded} folded, "
              f"{run.merged} merged, {run.tightened} tightened, {run.retired} "
              f"retired, {run.discarded} notes discarded; rules "
              f"{run.rules_before} -> {run.rules_after}", flush=True)
        return run.id


def _plan_and_do(client, run, log):
    rules = _active_rules()
    if not rules:
        return
    merges, tighten, retire = plan(client, run, rules)
    jobs = merges + [{"keep": t["slug"], "absorb": [], "why": t.get("why", "")}
                     for t in tighten]
    rewrite(client, run, jobs, log)
    for r in retire:
        ok, _ = _change(run, "rule", r["slug"], "*", "retire", "",
                        _one_line(r.get("why"), 300) or "Retired by the curator")
        if ok:
            run.retired += 1
            log.append(f"retired {r['slug']}")


def main():
    from app import create_app
    curate(create_app())
    return 0


if __name__ == "__main__":
    sys.exit(main())
