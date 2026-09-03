import os
import secrets
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))

# Railway sets this in every deployed environment; it is absent locally.
_IN_PRODUCTION = bool(os.environ.get("RAILWAY_ENVIRONMENT"))


def _session_secret():
    """The Flask session-signing key.

    This must never fall back to a literal. The repo is public, so a committed
    default would let anyone forge a signed session cookie for any user —
    including an admin — without knowing a password. A missing key is a hard
    failure in production; locally we mint a random per-process key, so
    sessions just don't survive a restart, which is fine for development.
    """
    key = os.environ.get("SECRET_KEY", "")
    if key:
        return key
    if _IN_PRODUCTION:
        raise RuntimeError(
            "SECRET_KEY is not set. Refusing to start with a default signing key; "
            "set SECRET_KEY in the Railway service variables."
        )
    return secrets.token_hex(32)


class Config:
    SECRET_KEY = _session_secret()

    # Session hardening. Cookies are HTTPS-only in production; locally we serve
    # plain http, where forcing Secure would silently drop the session.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _IN_PRODUCTION
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = _IN_PRODUCTION
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)
    _db_url = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(basedir, "data", "project_manager.db"))
    SQLALCHEMY_DATABASE_URI = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Where uploaded files (receipts, documents, generated PDFs) are stored when
    # not using S3. Set UPLOAD_FOLDER=/data/uploads in prod and mount a persistent
    # volume at /data so files survive redeploys. Defaults to the local static dir.
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(basedir, "static", "uploads"))
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB
    ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "jpg", "jpeg", "png", "webp", "gif", "xlsx", "csv", "txt"}
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    # Mail (contact form)
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "mbean@builtbybeans.com")
    MAIL_USE_TLS = True
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_USERNAME", "")
    # Time tracking is built and kept — routes, models, data all intact — but
    # not shown. Set FEATURE_TIME_TRACKING=1 to bring back the nav entry, the
    # header timer, the hours figures and the time tab on projects, tickets
    # and clients.
    FEATURE_TIME_TRACKING = os.environ.get("FEATURE_TIME_TRACKING", "").strip().lower() in (
        "1", "true", "yes", "on")

    # Bible Study
    ESV_API_KEY = os.environ.get("ESV_API_KEY", "")
    APP_URL = os.environ.get("APP_URL", "https://builtbybeans.com")

    # The god door (pm/guidance_routes.py): other Claude sessions read the
    # catalogue and report lessons back through /api/guidance with this as
    # a bearer token. Empty means the door answers 401 to everything -
    # closed, never open by default.
    GUIDANCE_API_KEY = os.environ.get("GUIDANCE_API_KEY", "")
