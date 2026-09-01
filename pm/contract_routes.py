"""Contracts sent out for signature, and what became of them.

The signing portal owns the envelope. These pages own the join: which client,
which project, which document. Status is read back from the portal whenever a
page here is opened, and the portal wins every disagreement — a status cached
here exists so a list draws before the network does, not so anything is decided
from it.

The one thing that is written back is the finished article. When an envelope
completes, the sealed PDF is pulled once and filed against the client like any
other document, because a signed contract that lives only in another system is
a signed contract nobody here can find.
"""

import os
import uuid
from datetime import datetime, timezone

from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, abort, Response,
)
from flask_login import login_required

import signadoc_service as signadoc
from signadoc_service import SignaDocError
from models import db, Document, SignatureRequest

contracts_bp = Blueprint("contracts", __name__, url_prefix="/admin/pm/contracts")

# Where a signature block goes on a document this board did not draw. Fractions
# of the page, top-left origin; page -1 is the last one. Bottom third, left of
# centre for the signature and right of it for the date, which is where a
# signature block sits on almost every contract ever written.
DEFAULT_FIELDS = [
    {"id": "sig", "signerId": "client", "type": "signature", "label": "Signature",
     "page": -1, "x": 0.12, "y": 0.78, "w": 0.34, "h": 0.035, "required": True},
    {"id": "dat", "signerId": "client", "type": "date", "label": "Date",
     "page": -1, "x": 0.55, "y": 0.78, "w": 0.22, "h": 0.035, "required": True},
]


# ── Where PDFs live ──────────────────────────────────────
#
# The same two places app.py keeps uploads: S3 when it is configured, the
# upload folder otherwise. Repeated here rather than reached for because those
# helpers are closures inside create_app and this blueprint is not.


def _s3():
    bucket = os.environ.get("AWS_S3_BUCKET")
    access = os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not (bucket and access and secret):
        return None, None
    import boto3
    return boto3.client(
        "s3",
        region_name=os.environ.get("AWS_S3_REGION", "us-east-2"),
        aws_access_key_id=access,
        aws_secret_access_key=secret,
    ), bucket


def _folder():
    from flask import current_app
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "documents")
    os.makedirs(path, exist_ok=True)
    return path


def read_pdf(stored_name):
    client, bucket = _s3()
    if client:
        return client.get_object(Bucket=bucket, Key=f"documents/{stored_name}")["Body"].read()
    with open(os.path.join(_folder(), stored_name), "rb") as fh:
        return fh.read()


def write_pdf(data):
    """Store the bytes and return the name they were stored under."""
    stored_name = f"{uuid.uuid4().hex}.pdf"
    client, bucket = _s3()
    if client:
        client.put_object(Bucket=bucket, Key=f"documents/{stored_name}",
                          Body=data, ContentType="application/pdf")
    else:
        with open(os.path.join(_folder(), stored_name), "wb") as fh:
            fh.write(data)
    return stored_name


def file_document(data, original_name, *, client_id=None, project_id=None):
    """Put a PDF where documents live and record it. Returns the Document."""
    doc = Document(
        client_id=client_id, project_id=project_id,
        filename=write_pdf(data), original_name=original_name, file_size=len(data),
    )
    db.session.add(doc)
    return doc


# ── Sending ──────────────────────────────────────────────


def _now():
    return datetime.now(timezone.utc)


def _parsed(stamp):
    """A portal timestamp as a datetime, or None if it sent something odd."""
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def create_request(*, pdf_bytes, filename, title, kind, signer_name, signer_email,
                   message="", fields=None, client=None, project=None,
                   source_document=None):
    """Send a PDF out for signature and record where it went.

    Raises SignaDocError if the portal will not take it, having written
    nothing: an envelope that was never sent should not leave a row here
    claiming it was.
    """
    reply = signadoc.send_for_signature(
        pdf_bytes,
        title=title,
        filename=filename,
        signer_name=signer_name,
        signer_email=signer_email,
        message=message,
        fields=fields or DEFAULT_FIELDS,
    )
    link = (reply.get("links") or [{}])[0]
    row = SignatureRequest(
        envelope_id=reply["id"],
        title=title[:200],
        kind=kind,
        client_id=client.id if client else None,
        project_id=project.id if project else None,
        source_document_id=source_document.id if source_document else None,
        signer_name=signer_name[:120],
        signer_email=signer_email[:200],
        signer_ref=link.get("signerId"),
        signing_url=link.get("url"),
        status=reply.get("status", "sent"),
        mail_mode=reply.get("mailMode"),
        sent_at=_parsed(reply.get("sentAt")) or _now(),
        synced_at=_now(),
    )
    db.session.add(row)
    db.session.commit()
    return row


# ── Reading the portal back ──────────────────────────────


def _apply(row, envelope):
    """Write the portal's answer onto our row. Returns whether it changed."""
    status = envelope.get("status")
    if not status or status == row.status:
        row.synced_at = _now()
        return False

    row.status = status
    row.synced_at = _now()
    if status == "completed":
        row.completed_at = _parsed(envelope.get("completedAt")) or _now()
        _file_signed_copy(row)
    return True


def _file_signed_copy(row):
    """Pull the sealed PDF once and keep it here too.

    Failing to fetch it is not failing to sign it. The status stands either
    way; the copy can be fetched again next time the page is opened, which is
    what signed_document_id being empty means.
    """
    if row.signed_document_id:
        return
    try:
        data = signadoc.sealed_pdf(row.envelope_id)
    except SignaDocError:
        return
    if not data.startswith(b"%PDF-"):
        return
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in row.title).strip()
    doc = file_document(
        data, f"{safe or 'Contract'} (signed).pdf",
        client_id=row.client_id, project_id=row.project_id,
    )
    db.session.flush()  # the Document needs an id before it can be pointed at
    row.signed_document_id = doc.id


def refresh_open_requests():
    """Ask the portal about everything still in flight.

    One call for all of them rather than one per row: the portal returns every
    envelope with its status, and a list page should not fan out.

    Returns the number of rows that changed, or None if the portal could not be
    asked — which the pages report rather than swallow, because a status that
    quietly stopped updating is worse than one that says it is stale.
    """
    open_rows = SignatureRequest.query.filter(
        SignatureRequest.status.in_(("draft", "sent"))
    ).all()
    if not open_rows:
        return 0
    if not signadoc.configured():
        return None
    try:
        envelopes = signadoc.list_envelopes()
    except SignaDocError:
        return None

    by_id = {e.get("id"): e for e in envelopes if isinstance(e, dict)}
    changed = 0
    for row in open_rows:
        envelope = by_id.get(row.envelope_id)
        if envelope and _apply(row, envelope):
            changed += 1
    db.session.commit()
    return changed


# ── Pages ────────────────────────────────────────────────


@contracts_bp.route("/")
@login_required
def contracts_index():
    stale = refresh_open_requests() is None
    rows = SignatureRequest.query.order_by(SignatureRequest.created_at.desc()).all()
    counts = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return render_template(
        "pm/contracts/index.html",
        requests=rows,
        counts=counts,
        stale=stale,
        configured=signadoc.configured(),
    )


@contracts_bp.route("/<int:id>")
@login_required
def contract_detail(id):
    row = db.session.get(SignatureRequest, id) or abort(404)
    refresh_open_requests()

    envelope, error = None, None
    if signadoc.configured():
        try:
            envelope = signadoc.get_envelope(row.envelope_id)
        except SignaDocError as exc:
            error = str(exc)
    else:
        error = "SignaDoc is not configured — set SIGNADOC_URL and SIGNADOC_API_KEY."

    return render_template(
        "pm/contracts/detail.html",
        req=row,
        envelope=envelope,
        error=error,
    )


@contracts_bp.route("/<int:id>/resend", methods=["POST"])
@login_required
def contract_resend(id):
    row = db.session.get(SignatureRequest, id) or abort(404)
    if not row.signer_ref:
        flash("No signer reference on this request — open it in SignaDoc instead.", "warning")
        return redirect(url_for("contracts.contract_detail", id=id))
    try:
        reply = signadoc.resend(row.envelope_id, row.signer_ref, email=True)
    except SignaDocError as exc:
        flash(f"Could not send a new link: {exc}", "error")
        return redirect(url_for("contracts.contract_detail", id=id))

    row.signing_url = reply.get("url") or row.signing_url
    row.mail_mode = reply.get("mailMode") or row.mail_mode
    db.session.commit()
    if reply.get("emailed") and reply.get("mailMode") == "smtp":
        flash(f"A fresh signing link is on its way to {row.signer_email}.", "success")
    else:
        flash("A fresh signing link is ready below — SignaDoc has no mail server, "
              "so send it to them yourself.", "warning")
    return redirect(url_for("contracts.contract_detail", id=id))


@contracts_bp.route("/<int:id>/void", methods=["POST"])
@login_required
def contract_void(id):
    row = db.session.get(SignatureRequest, id) or abort(404)
    reason = (request.form.get("reason") or "").strip()
    try:
        signadoc.void_envelope(row.envelope_id, reason)
    except SignaDocError as exc:
        flash(f"Could not void it: {exc}", "error")
        return redirect(url_for("contracts.contract_detail", id=id))
    row.status = "voided"
    row.synced_at = _now()
    db.session.commit()
    flash("Voided. The signing link no longer works.", "success")
    return redirect(url_for("contracts.contract_detail", id=id))


@contracts_bp.route("/<int:id>/signed.pdf")
@login_required
def contract_signed_pdf(id):
    """The sealed file, straight from the portal.

    Served through here rather than linked to, because the portal will not hand
    it over without a session and this board already has one.
    """
    row = db.session.get(SignatureRequest, id) or abort(404)
    if row.status != "completed":
        abort(404)
    try:
        data = signadoc.sealed_pdf(row.envelope_id)
    except SignaDocError as exc:
        flash(f"Could not fetch the signed PDF: {exc}", "error")
        return redirect(url_for("contracts.contract_detail", id=id))
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in row.title)
    return Response(data, content_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{safe}_SIGNED.pdf"',
    })


# ── Sending a document that already exists here ──────────


@contracts_bp.route("/send/<int:document_id>", methods=["GET", "POST"])
@login_required
def send_document(document_id):
    doc = db.session.get(Document, document_id) or abort(404)
    if not doc.original_name.lower().endswith(".pdf"):
        flash("Only PDFs can be sent for signature.", "warning")
        return redirect(url_for("pm.dashboard"))

    client = doc.client or (doc.project.client if doc.project else None)

    if request.method == "POST":
        name = (request.form.get("signer_name") or "").strip()
        email = (request.form.get("signer_email") or "").strip()
        title = (request.form.get("title") or "").strip() or doc.original_name
        message = (request.form.get("message") or "").strip()
        if not name or not email:
            flash("The signer needs a name and an email address.", "warning")
            return redirect(url_for("contracts.send_document", document_id=document_id))
        try:
            data = read_pdf(doc.filename)
        except Exception as exc:  # boto3 raises its own error types, not OSError
            flash(f"Could not read that document: {exc}", "error")
            return redirect(url_for("contracts.send_document", document_id=document_id))
        try:
            row = create_request(
                pdf_bytes=data, filename=doc.original_name, title=title,
                kind="document", signer_name=name, signer_email=email,
                message=message, client=client,
                project=doc.project, source_document=doc,
            )
        except SignaDocError as exc:
            flash(f"SignaDoc would not take it: {exc}", "error")
            return redirect(url_for("contracts.send_document", document_id=document_id))
        flash(sent_message(row), "success")
        return redirect(url_for("contracts.contract_detail", id=row.id))

    return render_template(
        "pm/contracts/send.html",
        document=doc, client=client, configured=signadoc.configured(),
    )


def sent_message(row):
    """What to tell the user once it has gone, which depends on whether it did.

    Without SMTP the portal writes the email to its outbox instead of sending
    it, and saying "sent" then would be a lie the client discovers a week later
    when they ask where the contract is.
    """
    if row.mail_mode == "smtp":
        return f"Sent to {row.signer_email} — they have a one-click link to sign."
    return (f"Envelope created for {row.signer_name}. SignaDoc has no mail server "
            f"configured, so copy the signing link below and send it to them.")


def send_generated(pdf_bytes, *, filename, title, kind, fields,
                   client=None, project=None, document=None):
    """Send a document this board just generated, if the form asked for it.

    Returns the SignatureRequest when it went out, and None when it was not
    asked for or could not be done — in which case the caller still hands the
    PDF over. Losing somebody's contract to a failed API call would be much
    the worse of the two outcomes, so a failure here flashes what went wrong
    and lets the download happen anyway.
    """
    if not request.form.get("send_for_signature"):
        return None

    name = (request.form.get("signer_name") or "").strip()
    email = (request.form.get("signer_email") or "").strip()
    if not name or not email:
        flash("Sending for signature needs a signer name and email — "
              "the PDF downloaded instead.", "warning")
        return None

    try:
        row = create_request(
            pdf_bytes=pdf_bytes, filename=filename, title=title, kind=kind,
            signer_name=name, signer_email=email,
            message=(request.form.get("signer_message") or "").strip(),
            fields=fields, client=client, project=project,
            source_document=document,
        )
    except SignaDocError as exc:
        flash(f"Could not send it for signature: {exc} The PDF downloaded instead.", "error")
        return None

    flash(sent_message(row), "success")
    return row
