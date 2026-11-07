"""The god door: what every other Claude asks before it builds, and how the
catalogue learns from what they find.

Every repo on this machine gets built by its own session, and every one of
them used to relearn this board's lessons the hard way. These endpoints
hand the catalogue out live - the rules that hold on every build, the
guidance behind any feature, the vendor runbooks - and take knowledge BACK.

The write side is the half that keeps the thing alive. Everything a
session sends becomes a CatalogueProposal and applies on arrival, rewrites
included: until 2026-11-02 a rewrite waited for Michael's yes, 188 of them
piled up unread, and he asked for it to "just adjust properly over time".
What keeps it honest now is the nightly curator (curate_practices.py),
which merges, tightens and retires, and the History tab, where any change
goes back in one press.

Below the catalogue sit the operational writes a session is allowed:
logging an expense or time against a project, filing a project, and
registering the infrastructure it just stood up so the hosting page can
see the cost. Nothing here talks to a client, resolves a ticket, or sends
a contract - those are Michael's, on purpose.

Bearer token on every route, compared in constant time - string equality
returns at the first differing byte, and how long that took is a
measurement. No token configured means the door is closed, not open. The
gate is a blueprint-wide before_request, so a route added later is
protected by default rather than by memory.
"""
import hmac
import html
import json
import re
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, Response, current_app, jsonify, request

from models import (db, Feature, Playbook, PlaybookStep, Product,
                    CatalogueProposal, Client, Project, Expense,
                    ServiceProvider, ServiceMapping, ServiceCostEntry,
                    ProviderInvoice)
from models import AppLink  # the My Apps tile (register_app)
from models import AppBlueprint  # a whole app end to end (app_blueprints.py)
from models import IconConcept  # the icon vocabulary (icon_vocabulary.py)
import app_blueprints
import icon_vocabulary  # one drawing per concept, in every project
import tend_service  # the Tend run's brief, map changes and gaps
import store_versions_service  # the two store pages' live versions for a phone app
from pm.apps_routes import _normalise as _normalise_url, _refresh_icon as _refresh_app_icon

guidance_bp = Blueprint("guidance", __name__, url_prefix="/api/guidance")
# The bank review for the /bank skill, behind this blueprint's gate.
from pm.bank_door_routes import bank_door_bp  # noqa: E402
guidance_bp.register_blueprint(bank_door_bp)
from pm.org_door_routes import org_door_bp  # noqa: E402
guidance_bp.register_blueprint(org_door_bp)
# Files the nightly service makes, onto the web service's volume.
from pm.files_door_routes import files_door_bp  # noqa: E402
guidance_bp.register_blueprint(files_door_bp)
from pm.legal_door_routes import legal_door_bp  # noqa: E402
guidance_bp.register_blueprint(legal_door_bp)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

# Everything but tab, newline and carriage return. Postgres refuses a NUL
# in a text column outright, so one stray byte in a reported lesson was a
# 500 instead of a record - found when the lesson ABOUT stray control
# bytes failed to file because it contained some.
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _slugify(value):
    return _SLUG_STRIP.sub("-", (value or "").strip().lower()).strip("-")[:80]


def _cap(value, bound):
    """Public-facing write discipline: scrub control characters and truncate
    to a bound, never trusting the wire to be reasonable about either."""
    return _CONTROL.sub("", str(value or "")).strip()[:bound]


def _number(value):
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _authorised():
    expect = current_app.config.get("GUIDANCE_API_KEY", "")
    if not expect:
        return False
    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header.startswith("Bearer ") else ""
    return bool(token) and hmac.compare_digest(token, expect)


@guidance_bp.before_request
def _gate():
    if not _authorised():
        return jsonify({"error": "unauthorised"}), 401


# ── Reading ──────────────────────────────────────────────


def _entry(feature):
    return {
        "slug": feature.slug,
        "name": feature.name,
        "kind": feature.kind,
        "category": feature.category_label,
        "summary": feature.summary or "",
        "how_to_build": feature.gold_standard_md or "",
        "what_went_wrong": feature.pitfalls_md or "",
        "worth_copying": (
            feature.reference_project
            + (f" - {feature.reference_path}" if feature.reference_path else "")
        ) if feature.reference_project else "",
    }


@guidance_bp.route("/rules")
def rules():
    rows = (Feature.query.filter_by(is_active=True, kind="rule")
            .order_by(Feature.sort_order, Feature.name).all())
    return jsonify({"rules": [_entry(r) for r in rows]})


# What a session can actually be handed at start. Claude Code keeps a hook's
# output in context only up to about ten thousand characters and swaps
# anything longer for a 2KB preview and a file path. On 2026-11-02 the full
# brief was 485 rules and 986KB, so every session on the machine had been
# starting with the first few rules and nothing else, while the hook
# reported success.
INDEX_BUDGET = 9000


def rules_index(budget=INDEX_BUDGET, rows=None, title="THE HOUSE RULES"):
    """Every rule as one line, name, slug and summary, inside `budget`.

    The whole rule is one get_feature_guidance away. When the index does not
    fit, the summaries go before any rule does, and only past that are rules
    left off, with a count saying how many. `rows` narrows it, for the MVP
    prompt, which prints some rules in full and lists the rest.
    """
    if rows is None:
        rows = (Feature.query.filter_by(is_active=True, kind="rule")
                .order_by(Feature.sort_order, Feature.name).all())
    head = [f"{title}, one line each. Before you build anything a rule "
            "touches, get_feature_guidance with its slug for the whole rule: "
            "how to build it and what went wrong last time.", ""]
    if not rows:
        return "\n".join(head + ["No rules recorded yet."])

    def line(r, with_summary=True):
        summary = " ".join((r.summary or "").split())
        if with_summary and summary:
            return f"- {r.name} [{r.slug}]: {summary[:140]}"
        return f"- {r.name} [{r.slug}]"

    for with_summary in (True, False):
        lines = [line(r, with_summary) for r in rows]
        text = "\n".join(head + lines)
        if len(text) <= budget:
            return text
    kept, size = [], len("\n".join(head))
    for entry in lines:
        if size + len(entry) + 120 > budget:
            break
        kept.append(entry)
        size += len(entry) + 1
    left = len(rows) - len(kept)
    return "\n".join(head + kept + [
        f"... and {left} more. get_feature_guidance with a topic finds them."])


@guidance_bp.route("/brief")
def brief():
    """The rules for a session that is starting. `?full=1` is every rule in
    full, assembled by the same code that writes the MVP build prompts, so
    the two can never say different things; without it, the index that fits
    in the context a session start actually keeps."""
    if request.args.get("full"):
        from pm.mvp_routes import _house_rules
        lines = _house_rules()
        if not lines:
            lines = ["No rules recorded yet."]
        return Response("\n".join(lines), mimetype="text/plain")
    return Response(rules_index(), mimetype="text/plain")


# A session asks in its own words. This looked for those words as one phrase
# until 2026-11-04, so "sign a contract" answered "nothing in the catalogue" with
# e-signature sitting there, and the session built it blind. It also handed back
# every match whole, 76,917 bytes for "dropdown", which is more than a tool's
# answer can carry. Now the words are matched wherever they are, the best
# matches come whole up to SEARCH_WHOLE and the rest by name.
SEARCH_SKIP = frozenset(
    "a about add an and are as at be build building by can do does for from get "
    "how i in into is it make need of on or our should so that the their them to "
    "up use using want we what when where which with would you your".split())
SEARCH_RESULTS = 20
SEARCH_WHOLE = 30000


def _search_stems(phrase):
    """The words that decide a search, each cut to what its forms share."""
    words = [w for w in re.findall(r"[a-z0-9]+(?:[-'][a-z0-9]+)*", phrase)
             if w not in SEARCH_SKIP]
    stems = []
    for word in words or [phrase]:
        stem = re.sub(r"(ing|ed|es|s)$", "", word) if len(word) > 4 else word
        if stem not in stems:
            stems.append(stem)
    return stems


def _search_rank(feature, stems, phrase):
    """(how many of the words it has, how much that says about it)."""
    name = f"{feature.name or ''} {feature.slug or ''}".lower()
    summary = (feature.summary or "").lower()
    body = " ".join((feature.gold_standard_md or "", feature.pitfalls_md or "",
                     feature.reference_project or "")).lower()
    matched = score = 0
    for stem in stems:
        # From the start of a word and no further: "tax" is not in "syntax".
        found = re.compile(r"\b" + re.escape(stem)).search
        weight = 8 if found(name) else 3 if found(summary) else 1 if found(body) else 0
        matched += bool(weight)
        score += weight
    if phrase in ((feature.name or "").lower(), (feature.slug or "").lower()):
        score += 40
    elif phrase in name:
        score += 20
    elif phrase in summary:
        score += 6
    elif phrase in body:
        score += 2
    return matched, score


@guidance_bp.route("/search")
def search():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"error": "give q"}), 400
    phrase = query.lower()
    stems = _search_stems(phrase)
    columns = (Feature.name, Feature.slug, Feature.summary, Feature.gold_standard_md,
               Feature.pitfalls_md, Feature.reference_project)
    rows = (Feature.query.filter_by(is_active=True)
            .filter(db.or_(*[c.ilike(f"%{s}%") for s in stems for c in columns]))
            .all())
    enough = (len(stems) + 1) // 2
    ranked = []
    for row in rows:
        matched, score = _search_rank(row, stems, phrase)
        if matched >= enough:
            ranked.append((-matched, -score, row.kind != "feature",
                           row.sort_order or 0, row.id, row))
    ranked.sort(key=lambda r: r[:5])
    matches, room = [], SEARCH_WHOLE
    for *_, row in ranked[:SEARCH_RESULTS]:
        entry = _entry(row)
        size = len(entry["how_to_build"]) + len(entry["what_went_wrong"])
        if matches and size > room:
            entry.update(how_to_build="", what_went_wrong="", cut=True)
        else:
            room -= size
        matches.append(entry)
    return jsonify({"query": query, "matches": matches})


@guidance_bp.route("/features/<slug>")
def feature_detail(slug):
    feature = Feature.query.filter_by(slug=slug, is_active=True).first()
    if feature is None:
        return jsonify({"error": "no such entry"}), 404
    return jsonify(_entry(feature))


@guidance_bp.route("/playbooks")
def playbooks():
    rows = (Playbook.query.filter_by(is_active=True)
            .order_by(Playbook.sort_order, Playbook.display_name).all())
    return jsonify({"playbooks": [
        {"slug": p.slug, "name": p.display_name, "one_liner": p.one_liner or ""}
        for p in rows]})


@guidance_bp.route("/playbooks/<slug>")
def playbook_detail(slug):
    playbook = Playbook.query.filter_by(slug=slug, is_active=True).first()
    if playbook is None:
        return jsonify({"error": "no such playbook"}), 404
    from pm.products_routes import playbook_lines
    return jsonify({"slug": playbook.slug, "name": playbook.display_name,
                    "runbook": "\n".join(playbook_lines(playbook))})


@guidance_bp.route("/blueprints")
def blueprints():
    rows = (AppBlueprint.query.filter_by(is_active=True)
            .order_by(AppBlueprint.sort_order, AppBlueprint.name).all())
    return jsonify({"blueprints": [
        {"slug": b.slug, "name": b.name, "one_liner": b.one_liner or ""} for b in rows]})


@guidance_bp.route("/blueprints/<slug>")
def blueprint_detail(slug):
    row = AppBlueprint.query.filter_by(slug=slug, is_active=True).first()
    if row is None:
        return jsonify({"error": "no such blueprint"}), 404
    return jsonify({"slug": row.slug, "name": row.name,
                    "blueprint": "\n".join(app_blueprints.blueprint_lines(row))})


@guidance_bp.route("/icons")
def icons():
    """The icon vocabulary. ?concept= narrows it to the concepts whose name,
    slug, icon name or aliases carry every word given; a slug alone answers
    that one concept."""
    words = [w for w in re.split(r"[^a-z0-9]+", (request.args.get("concept") or "").lower()) if w]
    rows = icon_vocabulary.concepts()
    if words:
        exact = [r for r in rows if r["slug"] == "-".join(words)]
        rows = exact or [r for r in rows if all(
            w in " ".join((r["slug"], r["name"], r["icon_name"], r["aliases"])).lower() for w in words)]
    keep = ("slug", "name", "group", "library", "icon_name", "aliases", "used_in_md", "never_md", "svg")
    return jsonify({"viewBox": icon_vocabulary.VIEWBOX, "stroke_width": icon_vocabulary.STROKE,
                    "icons": [{k: r[k] for k in keep} for r in rows],
                    "text": "\n\n".join(icon_vocabulary.entry_text(r) for r in rows)})


# ── The Tend run (.claude/skills/tend) ─────────────────
# Best Practices upkeep as a Claude Code session on Michael's plan, in place
# of the paid nightly curator. tend_service.py says what each of these is.


@guidance_bp.route("/tend")
def tend_brief():
    return jsonify({"brief": tend_service.brief()})


@guidance_bp.route("/tend/runs", methods=["POST"])
def tend_run():
    body = request.get_json(silent=True) or {}
    counts = body.get("counts") if isinstance(body.get("counts"), dict) else {}
    run_id = tend_service.record_run(counts, _cap(body.get("note"), 20000))
    return jsonify({"action": "recorded", "id": run_id})


@guidance_bp.route("/notes/<int:note_id>", methods=["POST"])
def close_note(note_id):
    body = request.get_json(silent=True) or {}
    ok, message = tend_service.close_note(note_id, _cap(body.get("outcome"), 12).lower(),
                                          _cap(body.get("reason"), 1000))
    if not ok:
        return jsonify({"error": message}), 400
    return jsonify({"action": "closed", "id": note_id})


@guidance_bp.route("/maps/<slug>")
def map_read(slug):
    business = tend_service.business_by_slug(slug)
    if business is None:
        return jsonify({"error": f"no business called {slug!r}"}), 404
    return jsonify({"slug": business.slug, "map": tend_service.map_text(business)})


@guidance_bp.route("/maps/<slug>", methods=["POST"])
def map_change(slug):
    body = request.get_json(silent=True) or {}
    result, status = tend_service.change_map(slug, body.get("changes"), _cap(body.get("project"), 120),
                                             _cap(body.get("reason"), 1000))
    return jsonify(result), status


@guidance_bp.route("/gaps", methods=["POST"])
def gaps_file():
    body = request.get_json(silent=True) or {}
    result, status = tend_service.file_gaps(_cap(body.get("blueprint"), 120), body.get("gaps"),
                                            _cap(body.get("project"), 120) or "tend")
    return jsonify(result), status


@guidance_bp.route("/products")
def products():
    rows = (Product.query.filter_by(is_active=True)
            .order_by(Product.sort_order, Product.name).all())
    return jsonify({"products": [
        {"slug": p.slug, "name": p.name, "summary": p.summary or "",
         "category": p.category, "playbook": p.playbook_slug or ""}
        for p in rows]})


@guidance_bp.route("/clients")
def clients():
    """Who the work is for, so a session can name a client and a project the
    way this board knows them rather than guessing at an id."""
    rows = Client.query.order_by(Client.name).all()
    return jsonify({"clients": [
        {"id": c.id, "name": c.name,
         "projects": [{"id": p.id, "name": p.name, "status": p.status}
                      for p in c.projects]}
        for c in rows]})


@guidance_bp.route("/taxes/sales")
def taxes_sales():
    """The sales tax page's figures, read only, from the same ledger
    (sales_tax.build over the board's invoice rows; no Stripe call), so a
    session can check what the page says without a browser (issue #19)."""
    import sales_tax
    from models import Invoice, Project, SalesTaxSetting
    s = SalesTaxSetting.get()
    led = sales_tax.build(s, Client.query.order_by(Client.name, Client.id).all(), Invoice.query.all(),
                          Project.query.all())
    keys = ("sales", "due", "charged", "on_invoices", "billed_back", "short", "left", "to_bill",
            "drafted", "billed", "collected")
    return jsonify({
        "rate": {"rate_percent": s.rate_percent, "taxable_share": s.taxable_share,
                 "of_every_dollar": s.effective_percent},
        "totals": {k: led["totals"].get(k) for k in keys},
        "clients": [dict({k: e.get(k) for k in keys}, name=e["client"].name, exempt=e["exempt"],
                         catchups=[{"number": c.invoice_number, "status": c.status, "total": c.total,
                                    "paid": c.amount_paid} for c in e["catchups"]])
                    for e in led["clients"]],
        "quarters": [{"label": q["label"], "due": q["due"], "charged": q["charged"],
                      "billed_back": q["billed_back"]} for q in led["quarters"]],
    })


@guidance_bp.route("/books/carryover")
def books_carryover():
    """What making the bank line the only thing that books an expense does to
    the rows already written (finance_carryover.py), read only. The session
    that wrote it could not read production's database, and the change may
    not move any company's totals except to remove a double count, so this
    is how the figures were checked before the migration ran."""
    import finance_carryover
    report = finance_carryover.plan(db.session.connection())
    db.session.rollback()
    report["summary"] = finance_carryover.summary(report)
    return jsonify(report)


@guidance_bp.route("/books/search")
def books_search():
    """Every charge that names a word, across every company, read only: bank
    and statement lines, expenses, and receipts (issue #18). A session cannot
    read production's database, and a vendor's accounts and costs were built
    from one bank rule each without anybody looking at what each company was
    actually charged (Michael, 2026-11-05: LegalZoom formed both LLCs, Apple
    was paid for, EntertainHQ has its own Claude plan). ?q= may repeat."""
    from models import BankTransaction, BankConnection, Business, Expense, Receipt, ReceiptMailbox, VendorRule
    words = [w.strip() for w in request.args.getlist("q") if w.strip()][:10]
    if not words:
        return jsonify({"error": "give ?q="}), 400
    names = {b.id: b.name for b in Business.query.all()}
    rules = {r.id: r for r in VendorRule.query.all()}
    out = {}
    for w in words:
        like = f"%{w}%"
        lines = (db.session.query(BankTransaction, BankConnection)
                 .outerjoin(BankConnection, BankTransaction.connection_id == BankConnection.id)
                 .filter(db.or_(BankTransaction.counterparty.ilike(like), BankTransaction.description.ilike(like)))
                 .order_by(BankTransaction.occurred_on).limit(300).all())
        expenses = (Expense.query.filter(Expense.description.ilike(like), Expense.time_entry_id.is_(None))
                    .order_by(Expense.date).limit(300).all())
        receipts = (db.session.query(Receipt, ReceiptMailbox)
                    .outerjoin(ReceiptMailbox, Receipt.mailbox_id == ReceiptMailbox.id)
                    .filter(db.or_(Receipt.sender.ilike(like), Receipt.subject.ilike(like), Receipt.vendor.ilike(like)))
                    .order_by(Receipt.received_on).limit(300).all())
        out[w] = {
            "bank": [{"id": t.id, "date": str(t.occurred_on), "amount": t.amount, "counterparty": t.counterparty,
                      "disposition": t.disposition, "company": names.get(t.business_id),
                      "account": getattr(c, "name", None) or getattr(c, "provider", None),
                      "kind": getattr(c, "kind", None), "rule": (rules[t.rule_id].vendor if t.rule_id in rules else None),
                      "expense_id": t.expense_id} for t, c in lines],
            "expenses": [{"id": e.id, "date": str(e.date), "amount": e.amount, "description": (e.description or "")[:120],
                          "category": e.category, "company": names.get(e.business_id), "paid_by": e.paid_by}
                         for e in expenses],
            "receipts": [{"date": str(r.received_on), "amount": r.amount, "sender": (r.sender or "")[:80],
                          "subject": (r.subject or "")[:100], "vendor": r.vendor,
                          "mailbox_company": names.get(m.business_id) if m is not None else None}
                         for r, m in receipts],
        }
    return jsonify(out)


@guidance_bp.route("/books/mail-search")
def books_mail_search():
    """Every message in every receipt mailbox that names a word, at any date,
    read only (the mailbox is opened read only, nothing is stored). The board
    keeps only the mail it used, so an order older than the books' first
    bank line was nowhere a session could see it (issue #18: Built by Bean's
    own LegalZoom order). Answers date, sender, subject and the amounts the
    receipt reader finds in each."""
    import email
    from email.header import decode_header, make_header
    import receipts_service
    from models import ReceiptMailbox, Business
    word = (request.args.get("q") or "").strip()
    if not word or '"' in word:
        return jsonify({"error": "give ?q= one word or phrase"}), 400
    names = {b.id: b.name for b in Business.query.all()}
    out = []
    for box in ReceiptMailbox.query.order_by(ReceiptMailbox.id).all():
        row = {"mailbox_company": names.get(box.business_id), "messages": []}
        try:
            conn = receipts_service._connect(box)
        except Exception as err:  # noqa: BLE001
            row["error"] = str(err)[:200]
            out.append(row)
            continue
        try:
            if "gmail" in box.imap_host:
                status, data = conn.search(None, "X-GM-RAW", f'"{word} -in:spam -in:trash"')
            else:
                status, data = conn.search(None, "TEXT", word)
            ids = (data[0] or b"").split() if status == "OK" else []
            for mid in ids[-60:]:
                status, parts = conn.fetch(mid, "(BODY.PEEK[])")
                if status != "OK" or not parts or not isinstance(parts[0], tuple):
                    continue
                msg = email.message_from_bytes(parts[0][1])
                parsed = {}
                try:
                    parsed = receipts_service.parse(parts[0][1], any_subject=True) or {}
                except Exception:  # noqa: BLE001
                    parsed = {}
                text = parsed.get("text") or ""
                try:
                    charged = receipts_service.charged_amounts(text)
                except Exception:  # noqa: BLE001
                    charged = []
                row["messages"].append({
                    "date": str(msg.get("Date", ""))[:40],
                    "from": str(make_header(decode_header(msg.get("From", ""))))[:100],
                    "subject": str(make_header(decode_header(msg.get("Subject", ""))))[:140],
                    "amount": parsed.get("amount"), "charged": sorted(charged)[:6] if charged else [],
                })
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
        out.append(row)
    return jsonify({"q": word, "mailboxes": out})


@guidance_bp.route("/costs")
def costs():
    """What each vendor has actually cost, and where that figure came from.

    READ ONLY, and here for a specific failure. Twice in one session the
    board reported a money figure that was wrong, and both times the session
    that shipped it could not tell: the guidance door hands out rules,
    runbooks and clients, and the admin pages need a login, so there was no
    way to check a number on the live board short of asking Michael to go and
    look. He found both. That is the wrong person doing the checking.

    Nothing here writes. It is the same bearer token that already gates the
    catalogue, and it is his own key for his own business figures, so the
    sensitivity is the same as the client list this door already returns.

    `source` is the whole point of the shape, and it has THREE values, not
    two. The first version had two and was wrong about most of the board:

      invoices  typed in off the vendor's bill. The truth.
      synced    read from the vendor's own billing API. Also the truth, and
                the majority: Cloudflare returns its billing history and
                Twilio its usage records, so nobody types those and nobody
                should be asked to.
      derived   neither. Assembled from the ledger by matching a description
                prefix, which is a guess, and is the shape that double
                counted Railway when two things wrote rows that both matched.

    Railway was believed to be the only vendor whose API will not report
    money, which is why it was entered by hand and the only one that could
    break this way. Its API does report bills to an account token (2026-11-01),
    and a Railway provider that names its workspace now pulls them; one
    without still waits to be typed in. Calling a synced figure "derived" reads as "this number is a guess"
    and would have had somebody typing in invoices for two vendors that
    already do it themselves.
    """
    from pm.service_costs_routes import MANUAL_MONTHLY_PROVIDERS
    out = []
    for provider in (ServiceProvider.query
                     .order_by(ServiceProvider.display_name).all()):
        if not provider.syncs:
            continue  # the night's finds report nothing; their money is the bank's
        invoices = (ProviderInvoice.query
                    .filter_by(provider_id=provider.id)
                    .order_by(ProviderInvoice.period_month).all())
        recorded = round(sum(i.amount or 0.0 for i in invoices), 2)

        # The same prefix match the hosting page falls back to, returned
        # beside the recorded total rather than instead of it, so the gap
        # between the two is visible in one response. That gap was the bug.
        derived = (db.session.query(db.func.coalesce(db.func.sum(Expense.amount), 0.0))
                   .filter(Expense.description.ilike(f"{provider.display_name} -%"))
                   .scalar())

        # The same reading Needs attention asks (provider_bills), so the two
        # cannot disagree about a month: they did about Railway (EntertainHQ)'s
        # October, whose bill does not exist until November 16 (fault 8).
        import provider_bills
        missing_months, waiting_months = provider_bills.bill_months(provider)
        missing = [m.strftime("%Y-%m") for m in missing_months]
        waiting = [m.strftime("%Y-%m") for m in waiting_months]

        by_hand = provider.name in MANUAL_MONTHLY_PROVIDERS
        if invoices:
            source = "invoices"
        elif provider.monthly_cost is not None:
            # A fixed amount configured on the provider, booked on the
            # billing day. Anthropic is the case: no API to ask, but the
            # figure was set deliberately, so it is not a guess either.
            source = "flat"
        elif not by_hand:
            source = "synced"
        else:
            source = "derived"

        out.append({
            "name": provider.name,
            "display_name": provider.display_name,
            "is_active": bool(provider.is_active),
            "entered_by_hand": by_hand,
            "lifetime": recorded if invoices else round(float(derived or 0.0), 2),
            "source": source,
            "invoice_total": recorded,
            "invoice_count": len(invoices),
            "derived_total": round(float(derived or 0.0), 2),
            # Only meaningful for a vendor that is typed in. A synced one
            # has nothing outstanding, so an empty list here is a fact rather
            # than a coincidence.
            "months_not_recorded": missing if by_hand else [],
            # A pulled account's month just finished, whose bill its own
            # billing day may not have written yet. Not missing; not here yet.
            "months_not_billed_yet": waiting if by_hand else [],
            "invoices": [{"month": i.period_month.strftime("%Y-%m"),
                          "amount": round(i.amount or 0.0, 2),
                          "note": i.note or ""} for i in invoices],
        })

    # Money IN, per client, off the same local invoice rows every page on the
    # board reads. Here for the same reason the costs are: a session reported
    # $0.00 revenue against $3,500 collected and had no way to see it, because
    # the invoices page needs a login. `invoices` is the count of local rows,
    # and a client with money at Stripe and no rows here is the shape of that
    # bug: the board only ever wrote a row for an invoice it raised itself.
    clients = []
    for client in Client.query.order_by(Client.name).all():
        rows = list(client.invoices)
        if not rows and not client.stripe_customer_id:
            continue
        clients.append({
            "name": client.name,
            "stripe_customer_id": client.stripe_customer_id or "",
            "invoices": len(rows),
            "billed": round(sum(i.total or 0.0 for i in rows), 2),
            # Cash in, tax and all, as the key has always meant; revenue
            # (Client.total_revenue) leaves the tax out since 2026-11-01.
            "paid": round(sum((i.amount_paid or 0.0) - (i.amount_refunded or 0.0)
                              for i in rows if i.status == "paid"), 2),
            # Only draft and open, which is what the invoices page does.
            # Stripe's amount_due is the amount due AT FINALISATION and does
            # not drop to zero when the invoice is paid (amount_remaining is
            # the one that does), so summing it across every status reports
            # everything ever billed as still owed.
            "outstanding": round(sum(i.amount_due or 0.0 for i in rows
                                     if (i.status or "") in ("draft", "open")), 2),
            "by_status": {
                s: sum(1 for i in rows if (i.status or "") == s)
                for s in sorted({(i.status or "") for i in rows})
            },
        })

    return jsonify({"providers": out, "clients": clients})


# ── How the catalogue changes ───────────────────────

# What a session may touch, per kind. Anything else is refused by name,
# because a whitelist that grows by accident is not a whitelist. `steps` on
# a playbook is the one structured field: the checklist under the runbook,
# carried as a list in the payload rather than as text.
TEXT_FIELDS = {
    "feature": ("name", "summary", "category", "gold_standard_md", "pitfalls_md",
                "reference_project", "reference_path"),
    "rule": ("name", "summary", "category", "gold_standard_md", "pitfalls_md",
             "reference_project", "reference_path",
             # A scanner for the rule: a session that learns a lesson can
             # also say how to catch it mechanically.
             "check_pattern", "check_globs", "check_exclude", "check_unless",
             "check_fixture"),
    "playbook": ("display_name", "one_liner", "vendor_url", "client_only_md",
                 "access_grant_md", "your_steps_md", "traps_md", "verify_md",
                 "steps",
                 # What the vendor looks like in a codebase, so the nightly
                 # map check can file a gap when a repo uses it and the map
                 # has no node for it (map_checks.py).
                 "presence_pattern", "presence_globs", "presence_exclude",
                 "presence_fixture"),
    "product": ("name", "summary", "prompt_intro", "playbook_slug"),
    # A whole app end to end (app_blueprints.py). `stages` is its structured
    # field, the build order, carried as a list the way a playbook's steps are.
    "blueprint": ("name", "one_liner", "source_repos", "shape_md", "parts_md",
                  "connections_md", "tweaks_md", "traps_md", "stages"),
    # One concept of the icon vocabulary (icon_vocabulary.py). `svg` is
    # checked and re-written from what parsed (clean_svg), and a drawing
    # already standing for another concept is refused.
    "icon": icon_vocabulary.FIELDS,
}
# No prices through this door, in or out. What something sells for is
# Michael's, typed on the Products page and the SOW.
#
# Only prose takes an append, and the checklist, which grows at the end. A
# name or a path is replaced whole.
APPENDABLE = {"summary", "gold_standard_md", "pitfalls_md", "client_only_md",
              "access_grant_md", "your_steps_md", "traps_md", "verify_md",
              "prompt_intro", "steps", "shape_md", "parts_md", "connections_md",
              "tweaks_md", "stages", "used_in_md", "never_md"}

# The most one proposal's text may carry, and past it the door refuses
# rather than cuts. An append grows a field without limit, so a replace has
# to be able to carry a whole grown field back. The old bound was 6000 and
# it truncated quietly: on 2026-11-01 the App Store runbook's traps had
# reached 14,005 characters, so a rewrite of them would have landed in the
# inbox already missing its tail, and accepting it would have deleted the
# end of the field while the inbox said the change was in.
TEXT_MAX = 60000

# Which prose field a bare lesson lands in when the entry already exists.
LESSON_FIELD = {"feature": "pitfalls_md", "rule": "pitfalls_md",
                "playbook": "traps_md", "product": "summary",
                "blueprint": "traps_md", "icon": "never_md"}


def _fields_for(kind):
    return TEXT_FIELDS.get(kind, ())


def _target(kind, slug):
    if kind in ("feature", "rule"):
        return Feature.query.filter_by(slug=slug).first()
    if kind == "playbook":
        return Playbook.query.filter_by(slug=slug).first()
    if kind == "product":
        return Product.query.filter_by(slug=slug).first()
    if kind == "blueprint":
        return AppBlueprint.query.filter_by(slug=slug).first()
    if kind == "icon":
        # A concept still on its default has no row until the door touches
        # it; this writes one from the default (flushed, so it commits with
        # the change or rolls back with it).
        return icon_vocabulary.row_for(slug)
    return None


def target_label(kind, slug):
    if kind == tend_service.MAP_KIND:
        return tend_service.map_label(slug)
    if kind == "icon":
        # Read, never written: _target would write a concept's row from its
        # default, and a History page is a GET.
        row = icon_vocabulary.get(slug) if slug else None
        return row["name"] if row else (slug or "(new)")
    row = _target(kind, slug) if slug else None
    if row is None:
        return slug or "(new)"
    return getattr(row, "display_name", None) or getattr(row, "name", slug)


def _stamp(project, text):
    return f"({project}, {_today()}) {text}"


def _auto_applies(mode):
    """Everything a session sends applies on arrival."""
    return mode in ("append", "create", "replace", "retire")


# ── The checklist ────────────────────────────────────────
# A playbook's steps are rows, not prose, so they travel as a list in
# payload["steps"]: {title, detail_md, client_channel (email or text),
# client_message_subject, client_message_md}. A step with a client message
# waits on the client. Append adds to the end and replace rewrites the
# list, both on arrival; a create may carry them. History reads the
# checklist as numbered lines, and revert puts back the exact list that
# was there.
STEP_FIELD = "steps"
MAX_STEPS = 40


def normalise_steps(raw):
    """The steps a session sent, checked and trimmed. Returns (list, error)."""
    if not isinstance(raw, list) or not raw:
        return None, "steps must be a non-empty list"
    if len(raw) > MAX_STEPS:
        return None, f"at most {MAX_STEPS} steps at a time"
    out = []
    for i, item in enumerate(raw, 1):
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict):
            return None, f"step {i} must be an object with a title"
        title = _cap(item.get("title"), 200)
        if not title:
            return None, f"step {i} needs a title"
        channel = (item.get("client_channel") or "").strip().lower()
        if channel not in ("", "email", "text"):
            return None, f"step {i}: client_channel must be email or text"
        message = _cap(item.get("client_message_md"), 4000)
        if message and not channel:
            channel = "email"
        # A check a machine can run nightly (step_checks.py): a pass ticks
        # the step on every project running it, and nothing unticks one.
        import step_checks
        kind = (item.get("check_kind") or "").strip().lower() or None
        target = _cap(item.get("check_target"), 300) or None
        pattern = _cap(item.get("check_pattern"), 2000) or None
        bad = step_checks.validate(kind, target, pattern)
        if bad:
            return None, f"step {i}: {bad}"
        out.append({
            "title": title,
            "detail_md": _cap(item.get("detail_md"), 4000),
            "client_channel": channel or None,
            "client_message_subject": _cap(item.get("client_message_subject"), 200),
            "client_message_md": message,
            "check_kind": kind, "check_target": target, "check_pattern": pattern,
        })
    return out, None


def steps_snapshot(playbook):
    return [{"title": s.title, "detail_md": s.detail_md or "",
             "client_channel": s.client_channel,
             "client_message_subject": s.client_message_subject or "",
             "client_message_md": s.client_message_md or "",
             "check_kind": s.check_kind, "check_target": s.check_target,
             "check_pattern": s.check_pattern}
            for s in playbook.steps.all()]


def steps_text(steps):
    """The checklist as History reads it: one numbered line per step."""
    lines = []
    for i, s in enumerate(steps or [], 1):
        flag = "  [waits on the client]" if s.get("client_message_md") else ""
        lines.append(f"{i}. {s.get('title', '')}{flag}")
    return "\n".join(lines)


def _write_steps(playbook, steps, start):
    for offset, s in enumerate(steps):
        db.session.add(PlaybookStep(
            playbook_id=playbook.id, position=start + offset,
            title=s["title"], detail_md=s["detail_md"],
            client_channel=s["client_channel"],
            client_message_subject=s["client_message_subject"],
            client_message_md=s["client_message_md"],
            check_kind=s.get("check_kind"), check_target=s.get("check_target"),
            check_pattern=s.get("check_pattern")))


def _clear_steps(playbook):
    for s in playbook.steps.all():
        db.session.delete(s)
    db.session.flush()


def _apply_steps(proposal, playbook):
    """Append to or rewrite the checklist, snapshotting what was there."""
    payload = json.loads(proposal.payload_json or "{}")
    steps, err = normalise_steps(payload.get("steps"))
    if err:
        return False, err
    current = steps_snapshot(playbook)
    if proposal.mode == "append":
        have = {s["title"].strip().lower() for s in current}
        fresh = [s for s in steps if s["title"].strip().lower() not in have]
        if not fresh:
            return False, "already there"
        last = max([s.position for s in playbook.steps.all()] or [0])
        _write_steps(playbook, fresh, last + 1)
    else:
        _clear_steps(playbook)
        _write_steps(playbook, steps, 1)
    proposal.previous = steps_text(current)
    payload["previous_steps"] = current
    proposal.payload_json = json.dumps(payload)
    return True, ""


def _revert_steps(proposal, playbook):
    payload = json.loads(proposal.payload_json or "{}")
    previous = payload.get("previous_steps")
    if previous is None:
        return False, "nothing recorded to put back"
    _clear_steps(playbook)
    if previous:
        steps, err = normalise_steps(previous)
        if err:
            return False, err
        _write_steps(playbook, steps, 1)
    return True, ""


def _apply_stages(proposal, blueprint):
    """Append to or rewrite a blueprint's build order, snapshotting it."""
    payload = json.loads(proposal.payload_json or "{}")
    stages, err, _ = app_blueprints.normalise_stages(payload.get(app_blueprints.STAGE_FIELD))
    if err:
        return False, err
    current = app_blueprints.stages_snapshot(blueprint)
    if proposal.mode == "append":
        have = {s["title"].strip().lower() for s in current}
        fresh = [s for s in stages if s["title"].strip().lower() not in have]
        if not fresh:
            return False, "already there"
        app_blueprints.write_stages(blueprint, fresh, len(current) + 1)
    else:
        app_blueprints.clear_stages(blueprint)
        app_blueprints.write_stages(blueprint, stages, 1)
    proposal.previous = app_blueprints.stages_text(current)
    payload["previous_stages"] = current
    proposal.payload_json = json.dumps(payload)
    return True, ""


def _revert_stages(proposal, blueprint):
    payload = json.loads(proposal.payload_json or "{}")
    previous = payload.get("previous_stages")
    if previous is None:
        return False, "nothing recorded to put back"
    app_blueprints.clear_stages(blueprint)
    if previous:
        app_blueprints.write_stages(blueprint, previous, 1)
    return True, ""


def _create_from(kind, payload, project):
    """Build the row a `create` proposal describes. Returns (row, error)."""
    name = _cap(payload.get("name") or payload.get("display_name"), 160)
    if not name:
        return None, "a create needs a name"
    slug = _slugify(payload.get("slug") or name)
    if not slug:
        return None, "could not make a slug from that name"
    if _target(kind, slug) is not None:
        return None, "exists"

    if kind in ("feature", "rule"):
        category = payload.get("category")
        if category not in Feature.CATEGORY_LABELS:
            category = "platform"
        last = db.session.query(db.func.max(Feature.sort_order)).scalar() or 0
        pitfalls = _cap(payload.get("what_went_wrong") or payload.get("pitfalls_md"), 4000)
        row = Feature(
            slug=slug, name=name, kind=kind, category=category,
            summary=_cap(payload.get("summary"), 1000),
            gold_standard_md=_cap(payload.get("how_to_build") or payload.get("gold_standard_md"), 4000),
            pitfalls_md=_stamp(project, pitfalls) if pitfalls else "",
            reference_project=_cap(payload.get("reference_project") or project, 120),
            reference_path=_cap(payload.get("path") or payload.get("reference_path"), 300),
            status="built", sort_order=last + 10,
        )
    elif kind == "playbook":
        category = payload.get("category")
        if category not in {c[0] for c in Playbook.CATEGORIES}:
            category = "service"
        last = db.session.query(db.func.max(Playbook.sort_order)).scalar() or 0
        row = Playbook(
            slug=slug, display_name=name, category=category,
            one_liner=_cap(payload.get("one_liner"), 300),
            vendor_url=_cap(payload.get("vendor_url"), 300),
            client_only_md=_cap(payload.get("client_only_md"), 6000),
            access_grant_md=_cap(payload.get("access_grant_md"), 6000),
            your_steps_md=_cap(payload.get("your_steps_md"), 6000),
            traps_md=_cap(payload.get("traps_md"), 6000),
            verify_md=_cap(payload.get("verify_md"), 6000),
            sort_order=last + 10,
        )
        # Give it the vendor's own mark on the way in, or it lands as a
        # monogram and stays one until somebody notices. Never fatal: the
        # runbook is the point, the picture is not, and a vendor's site being
        # down must not fail the write.
        try:
            from pm.playbooks_routes import refresh_playbook_icon
            refresh_playbook_icon(row)
        except Exception:
            pass
    elif kind == "product":
        category = payload.get("category")
        if category not in Product.CATEGORY_LABELS:
            category = "operations"
        last = db.session.query(db.func.max(Product.sort_order)).scalar() or 0
        row = Product(
            slug=slug, name=name, category=category,
            summary=_cap(payload.get("summary"), 2000),
            playbook_slug=_cap(payload.get("playbook_slug"), 60) or None,
            prompt_intro=_cap(payload.get("prompt_intro"), 4000),
            sort_order=last + 10,
        )
    elif kind == "blueprint":
        last = db.session.query(db.func.max(AppBlueprint.sort_order)).scalar() or 0
        app_id, business_id = app_blueprints.match_links(name)
        row = AppBlueprint(
            slug=slug, name=name,
            one_liner=_cap(payload.get("one_liner"), 400),
            source_repos=_cap(payload.get("source_repos"), 400),
            shape_md=_cap(payload.get("shape_md"), TEXT_MAX),
            parts_md=_cap(payload.get("parts_md"), TEXT_MAX),
            connections_md=_cap(payload.get("connections_md"), TEXT_MAX),
            tweaks_md=_cap(payload.get("tweaks_md"), TEXT_MAX),
            traps_md=_cap(payload.get("traps_md"), TEXT_MAX),
            app_id=app_id, business_id=business_id, sort_order=last + 10,
        )
    elif kind == "icon":
        svg, err = icon_vocabulary.clean_svg(payload.get("svg"))
        if err:
            return None, err
        clash = icon_vocabulary.duplicate_of(svg, slug)
        if clash:
            return None, f"that drawing already stands for {clash}; one icon, one meaning"
        group = payload.get("group") if payload.get("group") in dict(icon_vocabulary.GROUPS) else "thing"
        last = db.session.query(db.func.max(IconConcept.sort_order)).scalar() or 0
        row = IconConcept(
            slug=slug, name=name, group=group, svg=svg,
            library=_cap(payload.get("library") or icon_vocabulary.LIBRARY, 80),
            icon_name=_cap(payload.get("icon_name"), 80),
            aliases=_cap(payload.get("aliases"), 400),
            used_in_md=_cap(payload.get("used_in_md"), 6000),
            never_md=_cap(payload.get("never_md"), 6000),
            sort_order=last + 10,
        )
    else:
        return None, "unknown kind"
    db.session.add(row)
    db.session.flush()
    if kind == "blueprint" and payload.get(app_blueprints.STAGE_FIELD):
        stages, err, _ = app_blueprints.normalise_stages(payload.get(app_blueprints.STAGE_FIELD))
        if err:
            return None, err
        app_blueprints.write_stages(row, stages)
    if kind == "playbook" and payload.get("steps"):
        steps, err = normalise_steps(payload.get("steps"))
        if err:
            return None, err
        _write_steps(row, steps, 1)
    return row, None


def apply_proposal(proposal):
    """Put the change into the catalogue. Returns (ok, message).

    Snapshots `previous` on the way, so what this did can be undone exactly,
    including when it is accepted long after it was proposed and the field
    has moved in between.
    """
    if proposal.mode == "create":
        payload = json.loads(proposal.payload_json or "{}")
        row, err = _create_from(proposal.kind, payload, proposal.project or "")
        if err:
            return False, err
        proposal.target_slug = row.slug
        proposal.previous = None
        icon_vocabulary.invalidate()
        return True, ""

    row = _target(proposal.kind, proposal.target_slug)
    if row is None:
        return False, "no such entry"
    if proposal.mode == "retire":
        if not row.is_active:
            return False, "already there"
        proposal.previous = "active"
        row.is_active = False
        icon_vocabulary.invalidate()
        return True, ""
    field = proposal.field
    if field not in _fields_for(proposal.kind):
        return False, f"{field} is not a field a session may change"
    if field == STEP_FIELD:
        return _apply_steps(proposal, row)
    if field == app_blueprints.STAGE_FIELD:
        return _apply_stages(proposal, row)
    old = getattr(row, field)

    if proposal.mode == "append":
        old_text = old or ""
        if proposal.proposed in old_text:
            return False, "already there"
        new = ((old_text.rstrip() + "\n\n") if old_text.strip() else "") \
            + _stamp(proposal.project or "a session", proposal.proposed)
    else:
        new = proposal.proposed
        if field == "category" and new not in Feature.CATEGORY_LABELS:
            return False, ("category must be one of "
                           + ", ".join(Feature.CATEGORY_LABELS))
        if proposal.kind == "icon" and field == "svg":
            new, err = icon_vocabulary.clean_svg(new)
            if err:
                return False, err
            clash = icon_vocabulary.duplicate_of(new, row.slug)
            if clash:
                return False, f"that drawing already stands for {clash}; one icon, one meaning"
            proposal.proposed = new
        if proposal.kind == "icon" and field == "group" and new not in dict(icon_vocabulary.GROUPS):
            return False, "group must be one of " + ", ".join(dict(icon_vocabulary.GROUPS))

    proposal.previous = "" if old is None else str(old)
    setattr(row, field, new)
    if proposal.kind == "icon":
        icon_vocabulary.invalidate()
    return True, ""


def revert_proposal(proposal):
    """Put back what apply_proposal changed. Returns (ok, message)."""
    if proposal.kind == tend_service.MAP_KIND:
        return tend_service.revert_map(proposal)
    if proposal.mode == "create":
        row = _target(proposal.kind, proposal.target_slug)
        if row is None:
            return False, "already gone"
        # Retired rather than deleted: a created rule may already be sitting
        # inside a build prompt somebody generated, and a row that vanishes
        # under a foreign key is a worse outcome than one that goes quiet.
        row.is_active = False
        icon_vocabulary.invalidate()
        return True, ""
    row = _target(proposal.kind, proposal.target_slug)
    if row is None:
        return False, "no such entry"
    if proposal.mode == "retire":
        row.is_active = True
        icon_vocabulary.invalidate()
        return True, ""
    field = proposal.field
    if field == STEP_FIELD:
        return _revert_steps(proposal, row)
    if field == app_blueprints.STAGE_FIELD:
        return _revert_stages(proposal, row)
    if field not in _fields_for(proposal.kind):
        return False, f"{field} is no longer a field here"
    setattr(row, field, proposal.previous or "")
    if proposal.kind == "icon":
        icon_vocabulary.invalidate()
    return True, ""


def _propose(*, kind, slug, field, mode, text, reason, project, payload=None,
             hold=False):
    """Validate, record, and apply. Returns (dict, status).

    `hold` files the change as a curator CANDIDATE instead of applying it.
    The repo sweeper uses it: a section of a repo's CLAUDE.md was written
    for that repo, and as it stands it would ride into every build prompt.
    The curator reads it that night and writes a rule for any project from
    it, folds it into one, or discards it. Nobody has to press anything.
    """
    if kind not in CatalogueProposal.KIND_LABELS:
        return {"error": "kind must be feature, rule, playbook, product, blueprint or icon"}, 400
    if mode not in ("append", "replace", "create", "retire"):
        return {"error": "mode must be append, replace, create or retire"}, 400
    if not project:
        return {"error": "project is required - a change with no provenance "
                         "is a change nobody can weigh"}, 400

    unmatched = []
    if mode == "create":
        payload = payload or {}
        if not (payload.get("name") or payload.get("display_name")):
            return {"error": "a create needs a name"}, 400
        if kind == "blueprint" and payload.get(app_blueprints.STAGE_FIELD):
            stages, err, unmatched = app_blueprints.normalise_stages(payload[app_blueprints.STAGE_FIELD])
            if err:
                return {"error": err}, 400
    else:
        if not slug:
            return {"error": "slug is required unless creating"}, 400
        if _target(kind, slug) is None:
            return {"error": f"no {kind} with slug {slug!r}"}, 404
        if mode == "retire":
            field = "*"
            text = text or reason or "retired"
        elif field not in _fields_for(kind):
            return {"error": f"{field!r} is not a field a session may change "
                             f"on a {kind}; choose from "
                             + ", ".join(_fields_for(kind))}, 400
        if mode == "append" and field not in APPENDABLE:
            return {"error": f"{field} is replaced whole, not appended to"}, 400
        if mode != "retire" and field == STEP_FIELD:
            steps, err = normalise_steps((payload or {}).get("steps"))
            if err:
                return {"error": err}, 400
            payload = {"steps": steps}
            text = text or steps_text(steps)
        if mode != "retire" and field == app_blueprints.STAGE_FIELD:
            stages, err, unmatched = app_blueprints.normalise_stages(
                (payload or {}).get(app_blueprints.STAGE_FIELD))
            if err:
                return {"error": err}, 400
            payload = {app_blueprints.STAGE_FIELD: stages}
            text = text or app_blueprints.stages_text(stages)
        if not text:
            return {"error": "text is required"}, 400

    keeps_payload = mode == "create" or field in (STEP_FIELD, app_blueprints.STAGE_FIELD)
    proposal = CatalogueProposal(
        kind=kind, target_slug=slug or None, field=field or "*", mode=mode,
        proposed=text or "", reason=reason, project=project,
        payload_json=json.dumps(payload) if keeps_payload else None,
    )

    if _auto_applies(mode) and not hold:
        db.session.add(proposal)
        ok, message = apply_proposal(proposal)
        if not ok:
            db.session.rollback()
            if message in ("already there", "exists"):
                return {"action": "unchanged", "slug": slug or proposal.target_slug,
                        "reason": "that is already in the catalogue"}, 200
            return {"error": message}, 400
        proposal.status = "applied"
        proposal.decided_at = datetime.now(timezone.utc)
        db.session.commit()
        out = {"action": "applied", "id": proposal.id,
               "slug": proposal.target_slug,
               "note": "Applied on arrival. The nightly curator may merge or "
                       "tighten it, and it can be reverted from the History "
                       "tab of Best Practices."}
        if unmatched:
            # Said rather than guessed: a stage that links a playbook nobody
            # wrote would read as covered when it is not.
            out["unmatched"] = unmatched
            out["note"] += (" Not linked, because nothing in Best Practices is called "
                            + "; ".join(unmatched) + ".")
        return out, 200

    # Held for the curator: raw material, not yet a change.
    proposal.previous = None
    proposal.status = "candidate"
    db.session.add(proposal)
    db.session.commit()
    return {"action": "candidate", "id": proposal.id, "slug": slug,
            "note": "Filed for tonight's curator, which turns it into a rule "
                    "for any project, folds it into one, or discards it."}, 200


@guidance_bp.route("/proposals", methods=["POST"])
def propose():
    body = request.get_json(silent=True) or {}
    text = str(body.get("text") or "")
    if len(text) > TEXT_MAX:
        return jsonify({"error": f"text is {len(text):,} characters and a "
                                 f"proposal carries at most {TEXT_MAX:,}; "
                                 "nothing was recorded"}), 400
    kind = _cap(body.get("kind"), 10).lower()
    if kind == "features":
        kind = "feature"
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    # A create can carry its fields at the top level too, which is how the
    # bridge sends them.
    if _cap(body.get("mode"), 10) == "create" and not payload:
        payload = {k: v for k, v in body.items()
                   if k not in ("kind", "mode", "reason", "project")}
    result, status = _propose(
        kind=kind,
        slug=_slugify(body.get("slug") or ""),
        field=_cap(body.get("field"), 40),
        mode=_cap(body.get("mode"), 10).lower(),
        text=_cap(text, TEXT_MAX),
        reason=_cap(body.get("reason"), 1000),
        project=_cap(body.get("project"), 120),
        payload=payload,
    )
    return jsonify(result), status


@guidance_bp.route("/lessons", methods=["POST"])
def report_lesson():
    """A lesson learned somewhere else lands in the catalogue.

    The original door, kept for the sessions that use it: append when the
    entry exists, create a rule when it does not. Both now travel as
    proposals, so History holds the whole record of what the field has
    taught this board and any of it can be put back.
    """
    body = request.get_json(silent=True) or {}
    wrong = _cap(body.get("what_went_wrong"), 4000)
    gold = _cap(body.get("how_to_build"), 4000)
    project = _cap(body.get("project"), 120)
    if not wrong or not project:
        return jsonify({"error": "what_went_wrong and project are both "
                                 "required - a lesson is what happened and "
                                 "who it happened to"}), 400

    slug = _slugify(body.get("slug") or "")
    name = _cap(body.get("name"), 160)
    feature = None
    if slug:
        feature = Feature.query.filter_by(slug=slug).first()
    if feature is None and name:
        feature = Feature.query.filter(Feature.name.ilike(name)).first()

    if feature is not None:
        result, status = _propose(kind=feature.kind, slug=feature.slug,
                                  field="pitfalls_md", mode="append", text=wrong,
                                  reason="", project=project)
        if status != 200:
            return jsonify(result), status
        if gold and gold not in (feature.gold_standard_md or ""):
            _propose(kind=feature.kind, slug=feature.slug, field="gold_standard_md",
                     mode="append", text=gold, reason="", project=project)
        action = "appended" if result.get("action") == "applied" else "unchanged"
        return jsonify({"action": action, "slug": feature.slug,
                        "reason": result.get("reason", "")})

    if not name:
        return jsonify({"error": "no matching entry - give a name to create "
                                 "one"}), 400
    kind = "feature" if body.get("kind") == "feature" else "rule"
    result, status = _propose(
        kind=kind, slug="", field="*", mode="create", text="", reason="",
        project=project,
        payload={"name": name, "category": body.get("category"),
                 "summary": body.get("summary"), "what_went_wrong": wrong,
                 "how_to_build": gold, "path": body.get("path")})
    if status != 200:
        return jsonify(result), status
    if result.get("action") == "unchanged":
        return jsonify({"action": "unchanged", "slug": result.get("slug"),
                        "reason": "that entry already exists - name it by "
                                  "slug to append to it"})
    return jsonify({"action": "created", "slug": result["slug"], "kind": kind})


# ── Operational writes: money and projects ───────────────
#
# What a session doing real work for a client is allowed to record here. A
# session that stands up a Railway service for a client should be able to
# say so, log what it cost and what it took, without a human retyping it
# that evening. It is still not allowed to talk to the client, close their
# ticket or send them paper.


def _find_client(ref):
    """A client by id or by name. Returns (client, error)."""
    ref = str(ref or "").strip()
    if not ref:
        return None, "client is required"
    if ref.isdigit():
        client = db.session.get(Client, int(ref))
        return (client, None) if client else (None, f"no client with id {ref}")
    like = f"%{ref}%"
    rows = Client.query.filter(db.or_(Client.name.ilike(like),
                                      Client.company.ilike(like))).all()
    exact = [c for c in rows if c.name.lower() == ref.lower()]
    if len(exact) == 1:
        return exact[0], None
    if len(rows) == 1:
        return rows[0], None
    if not rows:
        return None, f"no client matches {ref!r}"
    return None, ("more than one client matches: "
                  + ", ".join(f"{c.name} (id {c.id})" for c in rows))


def _find_project(client, ref):
    """A project belonging to `client`, by id or name. Returns (project, error)."""
    ref = str(ref or "").strip()
    if not ref:
        return None, "project is required"
    if ref.isdigit():
        project = db.session.get(Project, int(ref))
        if project is None or project.client_id != client.id:
            return None, f"no project with id {ref} for {client.name}"
        return project, None
    rows = Project.query.filter_by(client_id=client.id) \
        .filter(Project.name.ilike(f"%{ref}%")).all()
    exact = [p for p in rows if p.name.lower() == ref.lower()]
    if len(exact) == 1:
        return exact[0], None
    if len(rows) == 1:
        return rows[0], None
    if not rows:
        return None, (f"{client.name} has no project matching {ref!r}; "
                      "their projects are: "
                      + ", ".join(p.name for p in client.projects))
    return None, ("more than one project matches: "
                  + ", ".join(f"{p.name} (id {p.id})" for p in rows))


def _parse_date(raw):
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


@guidance_bp.route("/projects", methods=["POST"])
def upsert_project():
    body = request.get_json(silent=True) or {}
    project_ref = _cap(body.get("project"), 120)
    client, err = _find_client(body.get("client"))
    if err:
        return jsonify({"error": err}), 400
    name = _cap(body.get("name") or project_ref, 200)
    if not name:
        return jsonify({"error": "name is required"}), 400
    provenance = _cap(body.get("source"), 120)

    project = None
    if project_ref:
        project, _ = _find_project(client, project_ref)
    if project is None:
        project = Project.query.filter_by(client_id=client.id) \
            .filter(Project.name.ilike(name)).first()

    created = project is None
    if created:
        project = Project(client_id=client.id, name=name)
        db.session.add(project)
    description = _cap(body.get("description"), 4000)
    if description:
        project.description = description
    status = _cap(body.get("status"), 20)
    if status in ("active", "paused", "completed", "archived"):
        project.status = status
    if provenance:
        stamp = f"({provenance}, {_today()}) filed through the guidance API"
        if stamp not in (project.notes or ""):
            project.notes = ((project.notes or "").rstrip() + "\n\n" + stamp).strip()
    db.session.commit()
    return jsonify({"action": "created" if created else "updated",
                    "id": project.id, "name": project.name,
                    "client": client.name})


@guidance_bp.route("/expenses", methods=["POST"])
def log_expense():
    body = request.get_json(silent=True) or {}
    amount = _number(body.get("amount"))
    if amount is None or amount <= 0:
        return jsonify({"error": "amount must be a positive number"}), 400
    description = _cap(body.get("description"), 500)
    if not description:
        return jsonify({"error": "description is required"}), 400
    when = _parse_date(body.get("date"))
    if when is None:
        return jsonify({"error": "date must be YYYY-MM-DD"}), 400

    client = project = None
    if body.get("client"):
        client, err = _find_client(body.get("client"))
        if err:
            return jsonify({"error": err}), 400
        if body.get("project"):
            project, err = _find_project(client, body.get("project"))
            if err:
                return jsonify({"error": err}), 400

    # Whose books. Omitted is the business the board bills from; a name or
    # id names another (EntertainHQ LLC keeps its own).
    business_id = None
    ref = _cap(body.get("business"), 200)
    if ref:
        from models import Business
        biz = (db.session.get(Business, int(ref)) if ref.isdigit() else
               Business.query.filter(db.or_(Business.name.ilike(f"%{ref}%"),
                                            Business.short_name.ilike(f"%{ref}%"))).first())
        if biz is None:
            return jsonify({"error": f"no business matches {ref!r}"}), 400
        business_id = biz.id

    # Only the bank line makes an expense (docs/finances_plan.md item 8,
    # 2026-11-04). What a session knows becomes a tag the bank line for this
    # charge takes when it arrives, so its expense lands on the right client
    # and project with nothing typed. A charge already booked takes it now.
    import bank_feed
    from models import ExpenseTag
    source = _cap(body.get("source"), 120)
    amount = round(amount, 2)
    vendor = _cap(body.get("vendor"), 200) or description
    same = ExpenseTag.query.filter_by(amount=amount, occurred_on=when, description=description,
                                      client_id=client.id if client else None,
                                      project_id=project.id if project else None).first()
    if same is not None:
        # A session retries like any API client: the same tag twice is one.
        return jsonify({"action": "already tagged", "id": same.id, "amount": amount,
                        "date": when.isoformat(), "taken": same.line_id is not None})
    tag = ExpenseTag(
        amount=amount, occurred_on=when, vendor=vendor, description=description,
        category=_cap(body.get("category"), 50) or "misc",
        client_id=client.id if client else None,
        project_id=project.id if project else None,
        business_id=business_id, paid_by=_cap(body.get("paid_by"), 120) or None,
        source=source or "")
    db.session.add(tag)
    db.session.flush()
    line = bank_feed.apply_tag(tag)
    db.session.commit()
    return jsonify({"action": "tagged", "id": tag.id, "amount": amount, "date": when.isoformat(),
                    "taken": line is not None,
                    "note": ("Booked on the bank line it matched." if line is not None else
                             "Waiting for the bank line: it books the expense when the charge arrives.")})


# There is no time door. /time took hours from sessions (log_time) and from the
# SessionEnd hook, which measured a transcript, until Michael, 2026-11-05: "I'm
# not going to have Claude assign arbitrary time values to work ... That would
# be lying to my customers." Claude never logs time; a person tracks their own
# on the Time page. Without a route the door answers 404, so an old bridge that
# still offers log_time records nothing.


def _upsert_mapping(body, client, project):
    """The cost mapping for one provider resource. Returns (mapping, created, error)."""
    provider_ref = _cap(body.get("provider"), 50).lower()
    provider = ServiceProvider.query.filter(
        db.or_(ServiceProvider.name.ilike(provider_ref),
               ServiceProvider.display_name.ilike(provider_ref))).first()
    if provider is None:
        names = ", ".join(p.name for p in ServiceProvider.query.all())
        return None, False, (f"no provider {provider_ref!r}; this board "
                             f"tracks: {names}")
    identifier = _cap(body.get("resource_identifier"), 300)
    if not identifier:
        return None, False, ("resource_identifier is required - the id "
                             "the provider knows the thing by")
    mapping = ServiceMapping.query.filter_by(
        provider_id=provider.id, resource_identifier=identifier).first()
    created = mapping is None
    if created:
        mapping = ServiceMapping(provider_id=provider.id,
                                 resource_identifier=identifier)
        db.session.add(mapping)
    mapping.client_id = client.id
    mapping.project_id = project.id if project else mapping.project_id
    label = _cap(body.get("label"), 300)
    if label:
        mapping.resource_label = label
    monthly = _number(body.get("monthly_cost"))
    if monthly is not None:
        mapping.monthly_cost = monthly
    mapping.is_active = True
    mapping.provider = provider
    return mapping, created, None


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_REPO = re.compile(r"^[\w.-]+/[\w.-]+$")


def _repo_url(raw):
    """`BuiltByBean/Talent-Booker` or a full address, as a link."""
    raw = _cap(raw, 500)
    if not raw:
        return None
    if _REPO.match(raw):
        return "https://github.com/" + raw
    return _normalise_url(raw)[:500] or None


def _host(url):
    return (url or "").split("//", 1)[-1].split("/", 1)[0].lower()


# The address a platform hands out before a real domain is attached. It is a
# stepping stone, never the app's name, and it must never take a card back
# from a domain somebody paid for.
_TEMP_HOSTS = (".up.railway.app", ".railway.app", ".onrender.com", ".fly.dev",
               ".vercel.app", ".netlify.app", ".herokuapp.com", ".pages.dev")


def _is_temp_host(host):
    return any(host.endswith(t) for t in _TEMP_HOSTS)


def better_address(current, incoming):
    """Which of two addresses the card should show.

    A real domain beats a platform's temporary one, whichever came second: a
    session re-registering the Railway address after the domain was attached
    must not put the temporary one back on the card. Between two real domains
    the shorter host wins, which is the apex over a subdomain (entertainhq.com
    over app.entertainhq.com), and equals go to the newer, so a move to a new
    domain still lands. Returns the address to keep.
    """
    if not current:
        return incoming
    a, b = _host(current), _host(incoming)
    if a == b:
        return incoming
    if _is_temp_host(b) and not _is_temp_host(a):
        return current
    if _is_temp_host(a) and not _is_temp_host(b):
        return incoming
    return current if len(a) < len(b) else incoming


def _upsert_app(body, client, project):
    """The My Apps tile for a deployed thing, created or updated. One card per
    app, and idempotent: the same host edits the same card, and so does the
    same PROJECT, because a project is one deployed thing whatever address it
    answers on this week. Before 2026-09-10 a second registration under the
    same project with a new name made a second card, which is how Robinson &
    Co. came to have one card on its Railway address and another on its real
    domain, and EntertainHQ one on the apex and one on app. A tile with no
    host and no project match is matched by name among the unattached rows,
    for the ones typed in by hand before this route existed. Returns (link,
    created, icon, error); `icon` is True when a favicon was fetched, False
    when the site offered none, None when an icon was already there and left
    alone."""
    url = _normalise_url(_cap(body.get("url"), 500))
    if not url.startswith(("http://", "https://")):
        return None, False, None, ("url is required - the public address that was just "
                                   "verified, e.g. https://acme.example.com")
    # A name is never HTML. One arrived as "Robinson &amp; Co." and was shown
    # that way, ampersand and all.
    name = html.unescape(_cap(body.get("app_name") or body.get("name"), 120)) \
        or (project.name if project else client.name)
    host = _host(url)
    link = None
    for row in AppLink.query.filter(AppLink.url.ilike(f"%{host}%")).all():
        if row.host.lower() == host:
            link = row
            break
    if link is None and project is not None:
        link = (AppLink.query.filter(AppLink.project_id == project.id)
                .order_by(AppLink.id).first())
    if link is None:
        link = AppLink.query.filter(AppLink.project_id.is_(None),
                                    AppLink.name.ilike(name)).first()
    created = link is None
    if created:
        link = AppLink()
        db.session.add(link)
    url = better_address(None if created else link.url, url)
    moved = created or link.url != url
    link.name = name
    link.url = url[:500]
    description = _cap(body.get("description"), 2000)
    if description:
        link.description = description
    repo = _repo_url(body.get("github_url") or body.get("repo"))
    if repo:
        link.github_url = repo
    railway_url = _normalise_url(_cap(body.get("railway_url"), 500))
    if railway_url:
        link.railway_url = railway_url[:500]
    # A phone app's store ids. Either one on its own is fine (a web-only app
    # has neither); a changed id is asked about right away, and a store that
    # does not answer never fails the registration.
    stores_were = (link.app_store_bundle_id, link.play_package)
    bundle = _cap(body.get("app_store_bundle_id") or body.get("bundle_id"), 200)
    if bundle:
        link.app_store_bundle_id = bundle
    package = _cap(body.get("play_package") or body.get("package"), 200)
    if package:
        link.play_package = package
    if project is not None:
        link.project_id = project.id
    db.session.flush()
    if (link.app_store_bundle_id, link.play_package) != stores_were:
        try:
            store_versions_service.refresh(link)
        except Exception:
            pass
    # The icon is the app's own, fetched once (see apps_routes). An icon somebody uploaded
    # by hand is never replaced by a fetch, and a failed fetch never fails the registration:
    # the tile with initials is still the tile, which is the whole point of this route.
    icon = None
    given = bool(link.icon_file) and link.icon_source is None
    # refresh_icon: the app's icon changed (a rebrand) - go and get it again, unless it
    # was uploaded by hand, which was a choice and is never fetched over.
    refresh = bool(body.get("refresh_icon")) and not given
    if (moved and not given) or not link.icon_file or refresh:
        try:
            icon = bool(_refresh_app_icon(link))
        except Exception:
            icon = False
    return link, created, icon, None


def _app_summary(link, created, icon):
    stores = store_versions_service.summary(link)
    return {"action": "created" if created else "updated", "id": link.id,
            "name": link.name, "url": link.url,
            "icon": ("fetched" if icon else ("kept" if link.icon_file else "none")),
            "project": link.project.name if link.project else None,
            "stores": ({"verdict": stores["verdict"],
                        "versions": {label: row for label, row in stores["rows"]}}
                       if stores else None)}


@guidance_bp.route("/hosting-resources", methods=["POST"])
def register_hosting_resource():
    """The infrastructure a session just stood up, mapped to the build it
    belongs to - which is what lets the hosting page hold that build's fee
    against what it actually costs. With a `url`, the same call puts the
    thing on My Apps (rule: a build is not stood up until it is there);
    without one, the reply says so, because a green mapping used to read
    as "the board knows about this app" when it did not."""
    body = request.get_json(silent=True) or {}
    client, err = _find_client(body.get("client"))
    if err:
        return jsonify({"error": err}), 400
    project = None
    if body.get("project"):
        project, err = _find_project(client, body.get("project"))
        if err:
            return jsonify({"error": err}), 400
    mapping, created, err = _upsert_mapping(body, client, project)
    if err:
        return jsonify({"error": err}), 400
    out = {"action": "registered" if created else "updated",
           "id": mapping.id, "provider": mapping.provider.display_name,
           "client": client.name,
           "project": project.name if project else None, "app": None}
    if body.get("url"):
        if (mapping.provider.name or "").lower() == "railway" and not body.get("railway_url") \
                and _UUID.match(mapping.resource_identifier or ""):
            body = dict(body, railway_url="https://railway.com/project/" + mapping.resource_identifier)
        link, app_created, icon, err = _upsert_app(body, client, project)
        if err:
            db.session.rollback()
            return jsonify({"error": err}), 400
        out["app"] = _app_summary(link, app_created, icon)
    else:
        out["note"] = ("no url given, so My Apps was not touched: pass url (the public "
                       "address, once verified) or call register_app")
    db.session.commit()
    return jsonify(out)


@guidance_bp.route("/apps", methods=["POST"])
def register_app():
    """A deployed thing onto My Apps, the moment its public address is verified -
    the one point where every field is known to be true rather than intended. With
    provider + resource_identifier it files the hosting mapping in the same call."""
    body = request.get_json(silent=True) or {}
    client, err = _find_client(body.get("client"))
    if err:
        return jsonify({"error": err}), 400
    project = None
    if body.get("project"):
        project, err = _find_project(client, body.get("project"))
        if err:
            return jsonify({"error": err}), 400
    mapping = None
    if body.get("provider") or body.get("resource_identifier"):
        mapping, _m_created, err = _upsert_mapping(body, client, project)
        if err:
            return jsonify({"error": err}), 400
        if (mapping.provider.name or "").lower() == "railway" and not body.get("railway_url") \
                and _UUID.match(mapping.resource_identifier or ""):
            body = dict(body, railway_url="https://railway.com/project/" + mapping.resource_identifier)
    link, created, icon, err = _upsert_app(body, client, project)
    if err:
        db.session.rollback()
        return jsonify({"error": err}), 400
    db.session.commit()
    out = _app_summary(link, created, icon)
    out["client"] = client.name
    out["mapping"] = mapping.id if mapping else None
    return jsonify(out)


@guidance_bp.route("/apps/services", methods=["POST"])
def app_services():
    """The services an app's code uses, for the catalog (issue #23). The
    nightly audit reads them off every repo it downloads; this is the same
    write for a session that has read a repo itself. By `github` (owner/name),
    `url` (the tile's host) or `name` (exactly); `services` is a list of vendor
    names. Answers the tile and what it now holds."""
    import catalog_service
    from models import AppLink
    body = request.get_json(silent=True) or {}
    names = body.get("services")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        return jsonify({"error": "services is a list of vendor names"}), 400
    tile = None
    repo = (body.get("github") or "").strip().strip("/").lower()
    if repo:
        tile = next((t for t in AppLink.query.all()
                     if (t.github_url or "").lower().rstrip("/").endswith("/" + repo)), None)
    if tile is None and body.get("url"):
        host = (body.get("url") or "").lower().replace("https://", "").replace("http://", "").strip("/")
        tile = next((t for t in AppLink.query.all() if t.host and t.host.lower() == host), None)
    if tile is None and body.get("name"):
        tile = AppLink.query.filter(AppLink.name == body["name"].strip()).first()
    if tile is None:
        return jsonify({"error": "no tile matches"}), 404
    catalog_service.set_services(tile, names)
    db.session.commit()
    return jsonify({"tile": tile.name, "services": tile.services})


@guidance_bp.route("/apps/retire", methods=["POST"])
def retire_app():
    """The other half of register_app: something torn down comes off the board.

    Michael, 2026-11-05: two Railway projects were deleted and their My Apps
    tiles stayed, because only a signed-in press on the tile could take one off
    and nothing a session could call did. By any of `url` (the tile's host),
    `name` (exactly) or `railway_project` (the Railway project id): every tile
    that matches is deleted as the page's own delete does it, icon file
    included, with its nightly site check; every hosting mapping for that
    Railway project is switched off, not deleted, so the months it was billed
    for keep their split; and the board's rows for that project's services
    go. A project on the board is never touched: it holds money and time.
    The answer carries every removed tile whole, which is what it takes to
    register it again. The work is app_retire.retire, which the nightly
    Railway read also calls for a project gone from Railway.
    """
    import app_retire
    body = request.get_json(silent=True) or {}
    reason = _cap(body.get("reason"), 300)
    url = _normalise_url(_cap(body.get("url"), 500)) if body.get("url") else ""
    name = html.unescape(_cap(body.get("name") or body.get("app_name"), 120))
    rail = _cap(body.get("railway_project"), 64).lower()
    if not reason:
        return jsonify({"error": "reason is required: say why it is coming off"}), 400
    if not (url or name or rail):
        return jsonify({"error": "give url, name or railway_project"}), 400
    if rail and not _UUID.match(rail):
        return jsonify({"error": "railway_project is the Railway project id, a UUID"}), 400
    done = app_retire.retire(url=url, name=name, railway_project=rail)
    if not (done["removed_apps"] or done["mappings_switched_off"] or done["railway_rows_removed"]):
        db.session.rollback()
        return jsonify({"error": "nothing on the board matches", "removed_apps": []}), 404
    db.session.commit()
    current_app.logger.info("guidance: retired %s (%s); mappings off %s; railway rows %s",
                            [r["name"] for r in done["removed_apps"]], reason,
                            [m["id"] for m in done["mappings_switched_off"]],
                            done["railway_rows_removed"])
    return jsonify(dict(done, reason=reason))
