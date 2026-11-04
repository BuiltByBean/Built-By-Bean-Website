"""The bank review through the door, for the /bank skill on Michael's plan.

    GET  /api/guidance/bank/review?limit=150   the waiting lines and all a
                                               session needs to judge them
    POST /api/guidance/bank/decide             {"decisions": [...]} settles them

Nested under the guidance blueprint (pm/guidance_routes.py registers it), so
its bearer-token gate covers these routes by construction rather than by
memory. bank_review.py says what each one holds.
"""
from flask import Blueprint, jsonify, request

import bank_review
from models import db

bank_door_bp = Blueprint("bank_door", __name__, url_prefix="/bank")


@bank_door_bp.route("/review")
def review():
    # The board's own suggestion first, so the session starts from it.
    bank_review.suggest_free()
    db.session.commit()
    return jsonify(bank_review.review_payload(request.args.get("limit", type=int) or 150))


@bank_door_bp.route("/decide", methods=["POST"])
def decide():
    body = request.get_json(silent=True) or {}
    decisions = body.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        return jsonify({"error": "send {\"decisions\": [{id, disposition, ...}]}"}), 400
    results, alike = bank_review.decide_many(decisions[:300])
    from models import BankTransaction
    return jsonify({"results": results, "settled_alike": alike,
                    "still_waiting": BankTransaction.query.filter_by(disposition="review").count()})
