"""The wire between this board and the e-signature portal.

SignaDoc holds the signing ceremony, the audit chain and the sealed PDF. This
board holds the client, the project and the paperwork that produced the
document. Neither should try to be the other, so what crosses between them is
deliberately small: a PDF and where its signature lines are, going out; a
status and a sealed file, coming back.

**Authenticated by key, not by URL.** SignaDoc is passwordless for people
because identity there is proven control of an inbox, which is also the
attribution evidence behind every signature. This board has no inbox, so it
presents a shared key and acts as the owner account. Only the sender half of
that API opens to a key: signing still needs the person whose address was
verified, which is the entire point of the evidence.

**Nothing is mirrored that can be asked for.** Envelope status lives in
SignaDoc and is read back on demand. Copying it here would give two answers to
one question, and the wrong one would be the one on screen.
"""

import base64
import json
import os
import urllib.error
import urllib.request

# Cloudflare and friends will refuse a caller on its client signature alone,
# and urllib introducing itself as Python-urllib gets a 403 that reads exactly
# like a rejected key and is nothing of the kind.
USER_AGENT = "BuiltByBean-PM/1.0"

TIMEOUT = 30

# What a signature line on our paperwork becomes in the portal. Anything not
# named here is a plain text box, which is the safe way to be wrong.
FIELD_TYPES = {
    "Signature": "signature",
    "Initials": "initials",
    "Date": "date",
}


class SignaDocError(Exception):
    """The portal did not take it, or could not be reached. Carries why."""


def base_url():
    return (os.environ.get("SIGNADOC_URL") or "").rstrip("/")


def _api_key():
    return os.environ.get("SIGNADOC_API_KEY") or ""


def configured():
    """Whether sending for signature is switched on at all.

    Both halves are needed, and a missing one is a setup problem rather than an
    error worth raising at every page load, so callers ask first and the
    templates say so plainly.
    """
    return bool(base_url() and _api_key())


def _request(method, path, payload=None, raw=False):
    url = base_url() + path
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {_api_key()}",
        "User-Agent": USER_AGENT,
        **({"Content-Type": "application/json"} if body else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
            return data if raw else json.loads(data.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", "")
        except Exception:
            pass
        if exc.code == 401:
            raise SignaDocError("SignaDoc refused the API key.") from exc
        raise SignaDocError(detail or f"SignaDoc returned {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SignaDocError(f"Could not reach SignaDoc: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SignaDocError("SignaDoc sent back something that was not JSON.") from exc


# ── Placing the signature fields ─────────────────────────


def fields_for(anchors, page_w, page_h, signer_id="client"):
    """Turn signature-line positions in millimetres into portal fields.

    The generators here draw the signature block themselves, so they know
    exactly where every line landed and can say so. That beats the alternative
    of searching the finished PDF for something that looks like a signature
    line, which works until a document is worded slightly differently.

    The portal stores coordinates as fractions of the page from a top-left
    origin, which is also how fpdf measures, so this is a division and a
    page-numbering fix: fpdf counts pages from one, the portal from zero.
    """
    fields = []
    for i, a in enumerate(anchors):
        label = a["label"]
        fields.append({
            "id": f"f{i}",
            "signerId": signer_id,
            "type": FIELD_TYPES.get(label, "text"),
            "label": label,
            "page": max(0, a["page"] - 1),
            "x": round(a["x"] / page_w, 5),
            "y": round(a["y"] / page_h, 5),
            "w": round(a["w"] / page_w, 5),
            "h": round(a["h"] / page_h, 5),
            "required": label != "Title",
        })
    return fields


# ── Sending ──────────────────────────────────────────────


def send_for_signature(pdf_bytes, *, title, filename, signer_name, signer_email,
                       fields, message="", sender_name="Built by Bean LLC",
                       sender_email=None, send=True):
    """Raise an envelope in the portal and send it. Returns the portal's reply.

    One call rather than upload-place-send, because a partial envelope after a
    failed second call is worse than no envelope at all, and the portal knows
    to discard a draft it could not send.
    """
    if not configured():
        raise SignaDocError(
            "SignaDoc is not configured — set SIGNADOC_URL and SIGNADOC_API_KEY."
        )
    payload = {
        "title": title[:140],
        "message": message[:2000],
        "filename": filename,
        "senderName": sender_name,
        "pdfBase64": base64.b64encode(pdf_bytes).decode("ascii"),
        "signingOrder": "parallel",
        "signers": [{"id": "client", "name": signer_name, "email": signer_email}],
        "fields": fields,
        "send": bool(send),
    }
    if sender_email:
        payload["senderEmail"] = sender_email
    return _request("POST", "/api/envelopes/import", payload)


def list_envelopes():
    """Every envelope the portal holds, with live status."""
    return _request("GET", "/api/envelopes")


def get_envelope(envelope_id):
    return _request("GET", f"/api/envelopes/{envelope_id}")


def sealed_pdf(envelope_id):
    """The signed, sealed file. Only exists once every signer is done."""
    return _request("GET", f"/api/envelopes/{envelope_id}/pdf?which=sealed", raw=True)


def void_envelope(envelope_id, reason=""):
    return _request("POST", f"/api/envelopes/{envelope_id}/void", {"reason": reason[:500]})


def resend(envelope_id, signer_id, email=True):
    """A fresh signing link for one signer, optionally emailed again.

    Links expire after fourteen days, so this is what turns "they never got
    round to it" back into something they can click.
    """
    return _request(
        "POST", f"/api/envelopes/{envelope_id}/signers/{signer_id}/notify",
        {"email": bool(email)},
    )


def envelope_url(envelope_id):
    """Where the sender goes to watch this envelope in the portal."""
    return f"{base_url()}/envelopes/{envelope_id}"
