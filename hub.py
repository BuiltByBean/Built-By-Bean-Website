"""The wire between a client's app and this board.

One protocol, spoken by three apps. This file is the hub end of it; Kuper and
Talent Booker each carry a copy of `sign` and `verify` that has to agree with
this one exactly, so keep them identical if either changes.

**Signed, not authenticated by URL.** A ticket endpoint that anyone can post to
is a spam board, and one guarded by a secret in the query string is a secret in
every access log and every Referer header. The signature covers the timestamp
and the exact bytes of the body, so neither can be altered without the shared
secret.

**One secret per client.** A leak is then one client's problem, and rotating it
touches nobody else.

**Timestamped, so a captured request cannot be replayed forever.** Five minutes
either way, which is loose enough for real clock drift between two hosts and
tight enough that a stolen request is stale by the time it is useful.

**compare_digest, never ==.** String equality returns as soon as two bytes
differ, and the time it takes is a measurement of how much of the signature was
right, which is enough to forge one a byte at a time.
"""

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request

# How far apart two clocks may be before a request is refused.
MAX_SKEW_SECONDS = 300

TIMESTAMP_HEADER = "X-BBB-Timestamp"
SIGNATURE_HEADER = "X-BBB-Signature"
ORIGIN_HEADER = "X-BBB-Origin"


def canonical(payload):
    """The exact bytes that get signed and sent.

    Serialised once, here, and both signed and posted from the same string.
    Signing a dict and re-serialising it to send is how a signature comes to
    cover different bytes than the ones that travel: key order and whitespace
    are not guaranteed to survive a round trip through json.dumps.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(secret, body, timestamp=None):
    """Return (timestamp, signature) for these exact bytes."""
    if timestamp is None:
        timestamp = str(int(time.time()))
    timestamp = str(timestamp)
    if isinstance(body, str):
        body = body.encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"),
                   timestamp.encode("utf-8") + b"." + body,
                   hashlib.sha256)
    return timestamp, mac.hexdigest()


def verify(secret, body, timestamp, signature):
    """Whether this body really came from the holder of the secret, just now.

    Returns a reason string on failure and None on success, because "it was
    refused" and "why" are different questions and the caller wants to log the
    second one.
    """
    if not secret:
        # An unconfigured client is not an authenticated one. Railway will not
        # store an empty variable, so a slot waiting to be filled holds a
        # placeholder, and anything that cannot tell a placeholder from a
        # credential authenticates as nobody and reports it as a bad key.
        return "no shared secret configured for this origin"
    if not timestamp or not signature:
        return "missing timestamp or signature"
    try:
        drift = abs(time.time() - int(timestamp))
    except (TypeError, ValueError):
        return "timestamp is not a number"
    if drift > MAX_SKEW_SECONDS:
        return f"timestamp is {int(drift)}s away, outside the {MAX_SKEW_SECONDS}s window"
    _ts, expected = sign(secret, body, timestamp)
    if not hmac.compare_digest(expected, signature):
        return "signature does not match"
    return None


# Say who we are. Cloudflare fronts a lot of things and will ban a caller on
# its client signature alone: with no User-Agent set, urllib introduces itself
# as Python-urllib/3.x and the reply is a 403 that reads exactly like a
# rejected key and is nothing of the kind. Kuper lost two days to this once.
USER_AGENT = "BuiltByBean-Hub/1.0"


class DeliveryError(Exception):
    """The far end did not take it. Carries what it said, for the log."""


def post(base_url, path, payload, *, secret, origin_slug, timeout=10):
    """Send one signed payload to a client's app.

    The same bytes are signed and posted. Serialising twice is how a signature
    comes to cover something other than what travelled, so `canonical` is
    called once and the result is used for both.

    Raises DeliveryError on anything that is not a 2xx, with the status and the
    first of the body, because "it failed" without the reason is a log entry
    nobody can act on.
    """
    body = canonical(payload)
    timestamp, signature = sign(secret, body)
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        ORIGIN_HEADER: origin_slug,
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: signature,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")[:500]
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        raise DeliveryError(f"{exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DeliveryError(str(exc)) from exc
