"""Repairing stored file names that point at nothing (volume_files.py).

    POST /api/guidance/files/heal

The web service's timer runs `heal_here` at boot and daily; the door lets a
session ask for it now. Nested under the guidance blueprint so its bearer gate
covers it by construction.
"""
import os

from flask import Blueprint, current_app, jsonify

files_door_bp = Blueprint("files_door", __name__, url_prefix="/files")


def heal_here():
    """Every stored file name the board points at, checked against the disk.

    A fetched icon that is gone is fetched again now; one that was uploaded by
    hand cannot be, so the tile goes back to its letter rather than a broken
    image. A receipt whose file is gone is let go (the mail is still in the
    mailbox and the next read takes it in again), and its expense goes back to
    Missing so the hunt finds the receipt again. Returns a one-line summary.
    """
    from models import AppLink, Business, BusinessNode, Expense, Playbook, Receipt, db
    from pm.apps_routes import _refresh_icon

    def gone(sub, name):
        return bool(name) and not os.path.exists(os.path.join(current_app.config["UPLOAD_FOLDER"], sub, name))

    refetched = cleared = receipts = expenses = 0
    for link in AppLink.query.filter(AppLink.icon_file.isnot(None)).all():
        if not gone("app_icons", link.icon_file):
            continue
        if link.icon_source and _refresh_icon(link):
            refetched += 1
        else:
            link.icon_file = None
            link.icon_source = None
            cleared += 1
    for model, sub, col in ((BusinessNode, "service_icons", "icon_file"),
                            (Playbook, "playbook_icons", "icon_file"),
                            (Business, "business_logos", "logo_file")):
        for row in model.query.filter(getattr(model, col).isnot(None)).all():
            if gone(sub, getattr(row, col)):
                setattr(row, col, None)
                cleared += 1
    # A receipt kept on S3 (before the volume) is not on this disk and is not
    # lost; leave receipts alone wherever S3 is still configured.
    if not os.environ.get("AWS_S3_BUCKET"):
        for r in Receipt.query.filter(Receipt.filename.isnot(None)).all():
            if gone("receipts", r.filename):
                db.session.delete(r)
                receipts += 1
        for e in Expense.query.filter(Expense.receipt_filename.isnot(None)).all():
            if gone("receipts", e.receipt_filename):
                e.receipt_filename = None
                e.receipt_original_name = None
                expenses += 1
    db.session.commit()
    return (f"{refetched} icons fetched again, {cleared} pictures cleared, "
            f"{receipts} receipts to read again, {expenses} expenses back on Missing")


@files_door_bp.route("/heal", methods=["POST"])
def heal():
    return jsonify({"summary": heal_here()})
