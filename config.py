import os

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "built-by-bean-project-manager-secret-key-change-me")
    _db_url = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(basedir, "data", "project_manager.db"))
    SQLALCHEMY_DATABASE_URI = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(basedir, "static", "uploads")
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
    # Bible Study
    ESV_API_KEY = os.environ.get("ESV_API_KEY", "")
    APP_URL = os.environ.get("APP_URL", "https://builtbybeans.com")
