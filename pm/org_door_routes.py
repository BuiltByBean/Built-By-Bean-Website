"""A business's org through the god door, for sessions.

    GET  /api/guidance/org?business=<name|slug|id>    the org, as the hub answers it
    POST /api/guidance/org/import                      {business, origin, people,
                                                        departments, responsibilities}

The import is how EntertainHQ's org first reached the board (2026-11-04): its
rows were read from its own database by a session and sent here, because this
repo is public and an org's responsibilities do not belong in a file in it.
Same rule as the hub's import: into an empty org, or over an earlier import
nobody has edited since, keyed by the app's ids. Nested under the guidance
blueprint so its bearer gate covers these routes by construction.
"""
from flask import Blueprint, jsonify, request

import org_service
from models import Business, db

org_door_bp = Blueprint("org_door", __name__, url_prefix="/org")


def _find(word):
    word = str(word or "").strip()
    if not word:
        return None
    if word.isdigit():
        return db.session.get(Business, int(word))
    low = word.lower()
    for b in Business.query.all():
        if low in {(b.hub_slug or "").lower(), (b.name or "").lower(), (b.short_name or "").lower()}:
            return b
    return None


@org_door_bp.route("")
def read():
    business = _find(request.args.get("business"))
    business = org_service.org_home(business) if business is not None else None
    if business is None:
        return jsonify({"error": "no such business",
                        "businesses": [b.name for b in org_service.org_businesses()]}), 404
    return jsonify(org_service.payload(business))


@org_door_bp.route("/import", methods=["POST"])
def import_():
    data = request.get_json(silent=True) or {}
    business = _find(data.get("business"))
    if business is None:
        return jsonify({"error": "no such business"}), 404
    business = org_service.org_home(business)
    origin = data.get("origin") or business.hub_slug or "app"
    try:
        counts = org_service.import_org(business, data, origin)
    except org_service.Refused as err:
        db.session.rollback()
        return jsonify({"error": str(err)}), err.status
    return jsonify({"imported": counts, "business": business.name})
