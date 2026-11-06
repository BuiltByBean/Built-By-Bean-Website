"""Vendor keys are sealed in the database, opened only when a sync needs them.

Found 2026-11-05 while connecting Twilio accounts (issue #14):
`ServiceProvider.credentials_json` held every vendor secret (Twilio API key
secrets, Cloudflare and Railway tokens, AWS keys) as plain JSON, so anyone
who could read the database or a backup could read every key. The pages had
already stopped drawing a saved secret back (#13); this is the other half.

What is sealed: the SECRET fields of a provider's credentials (`SECRET_FIELDS`).
The account ids, workspace ids and regions stay readable, because they are not
secrets and the board reads them to know what an account is (provider_bills,
the edit form).

The key is derived (HKDF) from the app's own `SECRET_KEY`, which the web
service and cost-sync share: their fingerprints were compared before this was
written, so nothing new had to be set and the nightly sync can open what the
web sealed. Changing SECRET_KEY means every sealed key has to be pasted again,
and the sync says so in words (`SealError`) rather than syncing nothing.

A value saved before this, or by a test, is plain and is read as it is; the
migration `c7e2a9f4b136` seals what production already holds.
"""
import base64
import json
import os

PREFIX = "enc:v1:"
SECRET_FIELDS = ("aws_secret_access_key", "api_token", "auth_token", "api_key_secret")


class SealError(RuntimeError):
    """A sealed key that this service cannot open."""


def _secret():
    try:
        from flask import current_app, has_app_context
        if has_app_context() and current_app.config.get("SECRET_KEY"):
            return str(current_app.config["SECRET_KEY"])
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get("SECRET_KEY", "")


def _fernet(secret=None):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    secret = secret if secret is not None else _secret()
    if not secret:
        raise SealError("No SECRET_KEY to seal or open vendor keys with.")
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"bbb-vendor-keys",
               info=b"service-provider-credentials-v1").derive(secret.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(raw))


def seal(value, secret=None):
    if not isinstance(value, str) or not value or value.startswith(PREFIX):
        return value
    return PREFIX + _fernet(secret).encrypt(value.encode("utf-8")).decode("ascii")


def unseal(value, secret=None):
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    from cryptography.fernet import InvalidToken
    try:
        return _fernet(secret).decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise SealError("Could not open the saved key: this service's SECRET_KEY is not the one it "
                        "was saved with. Paste the key in again with Edit.") from None


def is_sealed(value):
    return isinstance(value, str) and value.startswith(PREFIX)


def seal_creds(creds, secret=None):
    return {k: (seal(v, secret) if k in SECRET_FIELDS else v) for k, v in (creds or {}).items()}


def unseal_creds(creds, secret=None):
    return {k: (unseal(v, secret) if k in SECRET_FIELDS else v) for k, v in (creds or {}).items()}


def dumps(creds):
    """The column's text for these credentials, secrets sealed."""
    return json.dumps(seal_creds(creds))


def loads(text):
    """The credentials as a sync needs them, secrets opened. {} for nothing."""
    if not text:
        return {}
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    return unseal_creds(raw if isinstance(raw, dict) else {})
