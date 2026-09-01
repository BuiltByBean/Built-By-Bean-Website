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
    current_app,
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


# Who signs on behalf of Built by Bean. Here rather than inline so the name on
# a contract and the address the signing request goes to cannot drift apart.
COUNTERSIGNER_NAME = "Michael Bean"
COUNTERSIGNER_EMAIL = os.environ.get("COUNTERSIGNER_EMAIL", "michaelbean21@gmail.com")


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
                   source_document=None, countersigner=False):
    """Send a PDF out for signature and record where it went.

    Raises SignaDocError if the portal will not take it, having written
    nothing: an envelope that was never sent should not leave a row here
    claiming it was.

    `countersigner` is for a document Michael signs too. The envelope then
    carries both parties in sequence with him first, so the portal emails only
    him and invites the client the moment he is done. The row still records
    the client as the signer, because the client is who the document is
    waiting on for all but the first few minutes of its life.
    """
    signers = None
    order = "parallel"
    if countersigner:
        signers = [
            {"id": "bbb", "name": COUNTERSIGNER_NAME, "email": COUNTERSIGNER_EMAIL},
            {"id": "client", "name": signer_name, "email": signer_email},
        ]
        order = "sequential"

    reply = signadoc.send_for_signature(
        pdf_bytes,
        title=title,
        filename=filename,
        signer_name=signer_name,
        signer_email=signer_email,
        message=message,
        fields=fields or DEFAULT_FIELDS,
        signers=signers,
        signing_order=order,
    )
    links = reply.get("links") or [{}]
    # The client's link is the one worth keeping: it is what gets resent when
    # somebody says they never got it. Michael's own link is surfaced
    # separately by the caller so he can sign immediately.
    link = next((l for l in links if l.get("signerId") == "client"), links[0])
    own_link = next((l for l in links if l.get("signerId") == "bbb"), None)
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
    # Michael's own signing link, carried on the object rather than stored.
    # It is useful for about five minutes and a signing URL that outlives its
    # use is a signing URL sitting in a database.
    if own_link:
        row.own_signing_url = own_link.get("url")
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
    except Exception:
        # A best-effort status refresh must never take the page down with it.
        # SignaDocError covers the portal saying no; this covers the portal
        # address being wrong, which raises ValueError long before any request
        # is made and would otherwise 500 the contracts list.
        current_app.logger.exception("SignaDoc refresh failed")
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

    A countersigned document has not gone to the client at all yet — it is
    waiting on Michael — and saying "sent to them" would be the same lie one
    step earlier.
    """
    own = getattr(row, "own_signing_url", None)
    if own:
        return (f"Ready for your signature. Sign it here and it goes to "
                f"{row.signer_name} the moment you are done: {own}")
    if row.mail_mode == "smtp":
        return f"Sent to {row.signer_email} — they have a one-click link to sign."
    return (f"Envelope created for {row.signer_name}. SignaDoc has no mail server "
            f"configured, so copy the signing link below and send it to them.")


def send_generated(pdf_bytes, *, filename, title, kind, fields,
                   client=None, project=None, document=None,
                   countersigner=False):
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
            source_document=document, countersigner=countersigner,
        )
    except SignaDocError as exc:
        flash(f"Could not send it for signature: {exc} The PDF downloaded instead.", "error")
        return None

    flash(sent_message(row), "success")
    return row


# ── Add-ons and addendums ────────────────────────────────
#
# Two short documents that attach to a Statement of Work rather than replacing
# it: one sells a product on top of an existing build, one amends what is
# already signed. Both live here rather than in app.py because everything they
# need - the client picker, sending, the signature-request record - is here.

import contract_docs
from models import Client


def _clients_for_picker():
    """Everyone a contract can be written for, and the email on file."""
    clients = Client.query.order_by(Client.name).all()
    return ([(c.id, c.name) for c in clients],
            {str(c.id): {"name": c.name, "email": (c.email or "").strip()}
             for c in clients})


def _prior_contracts(client_id=None):
    """What an addendum could be amending, newest first.

    Both sources, because a contract is either something this board sent for
    signature or a PDF that was uploaded against the client after being signed
    somewhere else, and an addendum has to be able to name either.
    """
    out = []
    reqs = SignatureRequest.query.order_by(SignatureRequest.created_at.desc())
    if client_id:
        reqs = reqs.filter(SignatureRequest.client_id == client_id)
    for r in reqs.all():
        when = r.created_at.date().isoformat() if r.created_at else ""
        out.append({"client_id": r.client_id, "title": r.title, "date": when,
                    "label": f"{r.title}{' - ' + when if when else ''}"})
    docs = Document.query.order_by(Document.uploaded_at.desc())
    for d in docs.all():
        cid = getattr(d, "client_id", None)
        if client_id and cid != client_id:
            continue
        name = (getattr(d, "original_name", None) or "").rsplit(".", 1)[0]
        if not name:
            continue
        when = d.uploaded_at.date().isoformat() if d.uploaded_at else ""
        out.append({"client_id": cid, "title": name, "date": when,
                    "label": f"{name}{' - ' + when if when else ''}"})
    return out


def _script_font(pdf_family_owner):
    """The signature face, if it was ever added to this document."""
    return None


def _deliver(pdf_bytes, filename, title, kind, own, client_anchors, page_w, page_h,
             client, project=None):
    """Show it first, then send it if asked, otherwise hand back the download.

    Unless the form says the document has already been read, this stops here
    and puts it on screen. Nothing about the document changes between the
    preview and the send - pressing Send replays the same form through the same
    route, with `previewed` set.
    """
    if not request.form.get("previewed"):
        token = stash_preview(
            pdf_bytes, form=request.form, endpoint=request.endpoint, kind=kind,
            filename=filename, title=title,
            client_name=client.name if client else "")
        return redirect(url_for("contracts.preview", token=token))

    fields = signadoc.fields_for(client_anchors, page_w, page_h)
    if own:
        fields = signadoc.fields_for(own, page_w, page_h, signer_id="bbb") + fields
    sent = send_generated(
        pdf_bytes, filename=filename, title=title, kind=kind, fields=fields,
        countersigner=bool(own), client=client, project=project,
    )
    if token := request.form.get("preview_token"):
        drop_preview(token)
    if sent:
        return redirect(url_for("contracts.contract_detail", id=sent.id))
    resp = Response(pdf_bytes, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def _safe(name):
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:60]


@contracts_bp.route("/new/add-on", methods=["GET"])
@login_required
def addon_form():
    options, lookup = _clients_for_picker()
    return render_template("pm/contracts/addon_form.html",
                           today=datetime.now(timezone.utc).date().isoformat(),
                           client_options=options, client_lookup=lookup,
                           products=contract_docs.PRODUCTS,
                           product_choices=contract_docs.PRODUCT_CHOICES)


@contracts_bp.route("/new/add-on", methods=["POST"])
@login_required
def generate_addon():
    client = db.session.get(Client, request.form.get("client_id", type=int) or 0)
    key = (request.form.get("product") or "other").strip()
    base = contract_docs.PRODUCTS.get(key, contract_docs.PRODUCTS["other"])

    def lines(field, fallback):
        raw = (request.form.get(field) or "").strip()
        return [l.strip(" -\t") for l in raw.splitlines() if l.strip()] if raw else fallback

    name = (request.form.get("product_name") or base["name"]).strip()
    summary = (request.form.get("summary") or base["summary"]).strip()
    if not client or not name or not summary:
        flash("Choose a client, and give the add-on a name and a description.", "warning")
        return redirect(url_for("contracts.addon_form"))

    date_str = _fmt(request.form.get("date"))
    pdf_bytes, own, cli, w, h = contract_docs.build_addon(
        client_name=client.name, product_key=key, product_name=name, summary=summary,
        includes=lines("includes", base["includes"]),
        client_provides=lines("client_provides", base["client_provides"]),
        lead_time=(request.form.get("lead_time") or base["lead_time"]).strip(),
        third_party=(request.form.get("third_party") or base["third_party"]).strip(),
        one_time_fee=(request.form.get("one_time_fee") or "").strip(),
        monthly_fee=(request.form.get("monthly_fee") or "").strip(),
        date_str=date_str,
        reference=(request.form.get("reference") or
                   "the Statement of Work between the same parties").strip(),
        notes=(request.form.get("notes") or "").strip(),
        countersign=bool(request.form.get("send_for_signature")),
    )
    return _deliver(pdf_bytes, f"{_safe(client.name)}_AddOn_{_safe(name)}.pdf",
                    f"Add-On Agreement - {name}", "addon", own, cli, w, h, client)


@contracts_bp.route("/new/addendum", methods=["GET"])
@login_required
def addendum_form():
    options, lookup = _clients_for_picker()
    return render_template("pm/contracts/addendum_form.html",
                           today=datetime.now(timezone.utc).date().isoformat(),
                           client_options=options, client_lookup=lookup,
                           prior=_prior_contracts())


@contracts_bp.route("/new/addendum", methods=["POST"])
@login_required
def generate_addendum():
    client = db.session.get(Client, request.form.get("client_id", type=int) or 0)
    title = (request.form.get("original_title") or "").strip()
    description = (request.form.get("description") or "").strip()
    if not client or not title or not description:
        flash("Choose a client, say which contract this amends, and describe the change.",
              "warning")
        return redirect(url_for("contracts.addendum_form"))

    date_str = _fmt(request.form.get("date"))
    pdf_bytes, own, cli, w, h = contract_docs.build_addendum(
        client_name=client.name, original_title=title,
        original_date=_fmt(request.form.get("original_date")),
        description=description,
        fee_change=(request.form.get("fee_change") or "").strip(),
        date_str=date_str,
        effective=_fmt(request.form.get("effective")),
        countersign=bool(request.form.get("send_for_signature")),
    )
    return _deliver(pdf_bytes, f"{_safe(client.name)}_Addendum.pdf",
                    f"Addendum - {title}", "addendum", own, cli, w, h, client)


def _fmt(raw):
    """A form date as "September 01, 2026", or whatever was typed."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        return datetime.strptime(raw, "%Y-%m-%d").strftime("%B %d, %Y")
    except ValueError:
        return raw


# ── Preview before sending ───────────────────────────────
#
# Held on the volume rather than in memory: there are two gunicorn workers and
# the request that reads a preview back is not the one that wrote it.

import json as _json


def _preview_folder():
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "previews")
    os.makedirs(path, exist_ok=True)
    return path


def _sweep_previews(max_age_hours=6):
    """Drop anything left behind by somebody who closed the tab."""
    folder = _preview_folder()
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_hours * 3600
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


def stash_preview(pdf_bytes, *, form, endpoint, kind, filename, title, client_name,
                  page_count=None):
    """Hold a built document and the form that made it. Returns the token."""
    _sweep_previews()
    token = uuid.uuid4().hex
    folder = _preview_folder()
    with open(os.path.join(folder, token + ".pdf"), "wb") as fh:
        fh.write(pdf_bytes)
    meta = {
        "endpoint": endpoint, "kind": kind, "filename": filename, "title": title,
        "client_name": client_name, "size": len(pdf_bytes), "pages": page_count,
        # Every field, so pressing Send replays exactly what was previewed
        # rather than rebuilding from something that has since been edited.
        "form": {k: form.getlist(k) for k in form.keys()},
        "created": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(folder, token + ".json"), "w", encoding="utf-8") as fh:
        _json.dump(meta, fh)
    return token


def load_preview(token):
    """The stashed metadata, or None if it has been sent or swept."""
    if not token or not token.isalnum() or len(token) != 32:
        return None
    path = os.path.join(_preview_folder(), token + ".json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return _json.load(fh)


def drop_preview(token):
    folder = _preview_folder()
    for ext in (".pdf", ".json"):
        try:
            os.remove(os.path.join(folder, token + ext))
        except OSError:
            pass


@contracts_bp.route("/preview/<token>")
@login_required
def preview(token):
    meta = load_preview(token)
    if not meta:
        flash("That preview has expired. Fill the form in again.", "warning")
        return redirect(url_for("contracts.contracts_index"))
    form = {k: (v[0] if len(v) == 1 else v) for k, v in meta["form"].items()}
    return render_template("pm/contracts/preview.html", token=token, meta=meta,
                           form=form, sending=bool(form.get("send_for_signature")))


@contracts_bp.route("/preview/<token>/file.pdf")
@login_required
def preview_file(token):
    """The document itself, inline so the browser renders it in the page."""
    if not load_preview(token):
        abort(404)
    path = os.path.join(_preview_folder(), token + ".pdf")
    if not os.path.exists(path):
        abort(404)
    with open(path, "rb") as fh:
        data = fh.read()
    resp = Response(data, mimetype="application/pdf")
    # inline, not attachment: an attachment opens a save dialog instead of
    # showing anybody the document they asked to read.
    resp.headers["Content-Disposition"] = "inline; filename=preview.pdf"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@contracts_bp.route("/preview/<token>/discard", methods=["POST"])
@login_required
def preview_discard(token):
    drop_preview(token)
    flash("Preview discarded. Nothing was sent.", "info")
    return redirect(url_for("contracts.contracts_index"))
