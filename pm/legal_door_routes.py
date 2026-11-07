"""The Legal library's door (issue #42): what a session reaches through the bridge.

    GET  /api/guidance/legal                 the library as text (?q= words, ?app=, ?status=, ?product=, ?topic=)
    GET  /api/guidance/legal/gaps            the gaps per product as text
    GET  /api/guidance/legal/<slug>          one entry, text and JSON
    POST /api/guidance/legal                 file a product's register (file_legal): applies on arrival, and the
                                             board then fetches its own copy of each new source in the background
    POST /api/guidance/legal/recheck         start a re-check (legal_recheck): every source, or the named ones
    GET  /api/guidance/legal/checks/<id>     how a run went
    GET  /api/guidance/legal/checks          the last runs

Nested under the guidance blueprint so its bearer gate covers it by construction.
Every answer carries the disclaimer: nothing in the library is legal advice.
"""
import threading

from flask import Blueprint, current_app, jsonify, request

import legal_library
from models import LegalCheck, LegalEntry

legal_door_bp = Blueprint("legal_door", __name__, url_prefix="/legal")


def _entry_json(e):
    return {
        "slug": e.slug, "title": e.title, "product": e.product, "topic": e.topic, "jurisdiction": e.jurisdiction,
        "status": e.status, "status_label": e.status_label, "laws_md": e.laws_md or "",
        "requires_md": e.requires_md or "", "decision_md": e.decision_md or "",
        "recorded_in_md": e.recorded_in_md or "", "notes_md": e.notes_md or "",
        "lawyer_question": e.lawyer_question or "", "issues": e.issue_list,
        "last_checked_at": e.last_checked_at.isoformat() + "Z" if e.last_checked_at else None,
        "check_result": e.check_result,
        "apps": [{"app": t.app_name, "tile_id": t.app_id, "functions": t.functions, "routes": t.routes,
                  "note": t.note or ""} for t in e.touches],
        "sources": [{"key": lk.source.key, "title": lk.source.title, "url": lk.source.url, "site": lk.source.site,
                     "citation": lk.citation or "", "fetched_at": lk.source.fetched_at.isoformat() + "Z"
                     if lk.source.fetched_at else None, "sha256": lk.source.sha256 or "",
                     "last_check": lk.source.last_check, "fetch_how": lk.source.fetch_how,
                     "copy": bool(legal_library.copy_path(lk.source))} for lk in e.links],
    }


@legal_door_bp.route("", methods=["GET"])
def library():
    a = request.args
    text = legal_library.library_text(q=a.get("q", ""), app=a.get("app"), status=a.get("status"),
                                      product=a.get("product"), topic=a.get("topic"))
    return jsonify({"text": text, "disclaimer": legal_library.DISCLAIMER})


@legal_door_bp.route("/gaps", methods=["GET"])
def gaps():
    return jsonify({"text": legal_library.gaps_text(), "disclaimer": legal_library.DISCLAIMER})


@legal_door_bp.route("/checks", methods=["GET"])
def checks():
    runs = LegalCheck.query.order_by(LegalCheck.id.desc()).limit(10).all()
    return jsonify({"runs": [legal_library.run_summary(r) for r in runs]})


@legal_door_bp.route("/checks/<int:run_id>", methods=["GET"])
def check(run_id):
    from models import db
    run = db.session.get(LegalCheck, run_id)
    if run is None:
        return jsonify({"error": "no such run"}), 404
    return jsonify({"run": legal_library.run_summary(run)})


@legal_door_bp.route("/recheck", methods=["POST"])
def recheck():
    body = request.get_json(silent=True) or {}
    keys = body.get("sources") or None
    if keys is not None and not isinstance(keys, list):
        return jsonify({"error": "sources must be a list of source ids"}), 400
    by = str(body.get("project") or "a session")[:120]
    run_id = legal_library.start_recheck(current_app._get_current_object(), keys=keys, by=by)
    from models import db
    run = db.session.get(LegalCheck, run_id)
    return jsonify({"run": legal_library.run_summary(run), "disclaimer": legal_library.DISCLAIMER}), 202


@legal_door_bp.route("", methods=["POST"])
def file_register():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "a JSON body with product and entries"}), 400
    try:
        summary = legal_library.upsert(body, filed_by=str(body.get("project") or body.get("filed_by") or "")[:120])
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    # The board's own copies, fetched after the answer: ninety documents do not fit in a request.
    app = current_app._get_current_object()

    def copies():
        with app.app_context():
            try:
                legal_library.take_missing_copies()
            except Exception:  # noqa: BLE001 - a copy that fails is retried by the next filing or re-check
                app.logger.exception("legal: taking copies failed")

    if not app.config.get("LEGAL_COPIES_INLINE"):
        threading.Thread(target=copies, name="legal-copies", daemon=True).start()
        summary["copies"] = "being fetched onto the board's volume"
    else:
        taken, failed = legal_library.take_missing_copies()
        summary["copies"] = f"{taken} taken, {failed} failed"
    summary["disclaimer"] = legal_library.DISCLAIMER
    return jsonify(summary), 201


@legal_door_bp.route("/<slug>", methods=["GET"])
def entry(slug):
    e = LegalEntry.query.filter_by(slug=legal_library._slug(slug), is_active=True).first()
    if e is None:
        return jsonify({"error": "no such entry"}), 404
    return jsonify({"text": legal_library.entry_text(e), "entry": _entry_json(e),
                    "disclaimer": legal_library.DISCLAIMER})
