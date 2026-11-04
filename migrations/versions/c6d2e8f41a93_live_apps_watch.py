"""Live apps watch: Railway services, site checks, domains, step checks

docs/automation_gaps.md items 7, 9, 18, 19, 20 and 4 (store versions).

New tables: railway_services, site_checks, domain_watches. New columns:
app_links.store_differ_since and repo_versions, playbooks.presence_* (the
Product.presence_* signature, reused), playbook_steps.check_*. Seeds the
signature for every vendor a repo can be seen using, and the checks on the
Railway checklist a machine can see, each only where the field is empty.

Every create is guarded on the table or column not existing, because
create_all runs on boot and wins the race for tables.

Revision ID: c6d2e8f41a93
Revises: c8f2d5a1e9b3
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "c6d2e8f41a93"
down_revision = "c8f2d5a1e9b3"
branch_labels = None
depends_on = None


CODE_GLOBS = ("**/requirements*.txt, **/package.json, **/*.py, **/*.js, **/*.ts, **/*.tsx, "
              "**/*.gradle, **/Podfile, **/pyproject.toml, **/.env.example, **/app.json")
EXCLUDE = "test, docs/, migrations/"

# slug: (pattern, fixture). Dependencies and environment names, never prose,
# so a README that mentions a vendor is not a sighting.
SIGNATURES = {
    "stripe": (r"""(?i)(^\s*stripe\s*[=<>~]|["']stripe["']\s*:|^\s*import stripe|from stripe |@stripe/|STRIPE_SECRET_KEY)""",
               "stripe==9.1.0"),
    "twilio": (r"""(?i)(^\s*twilio\s*[=<>~]|["']twilio["']\s*:|from twilio|TWILIO_ACCOUNT_SID)""",
               "twilio>=8.0"),
    "resend": (r"""(?i)(^\s*resend\s*[=<>~]|["']resend["']\s*:|^\s*import resend|RESEND_API_KEY)""",
               "resend==2.4.0"),
    "sentry": (r"""(?i)(sentry[-_]sdk|["']@sentry/|SENTRY_DSN)""",
               "sentry-sdk[flask]==2.0"),
    "postmark": (r"""(?i)(postmarker|["']postmark["']\s*:|POSTMARK_(SERVER|API)_TOKEN)""",
                 "POSTMARK_SERVER_TOKEN="),
    "aws": (r"""(?i)(^\s*boto3\s*[=<>~]|["']@aws-sdk/|AWS_ACCESS_KEY_ID)""",
            "boto3==1.34"),
    "firebase": (r"""(?i)(firebase[-_]admin|["']firebase["']\s*:|@capacitor-firebase/)""",
                 "firebase-admin==6.5"),
    "revenuecat": (r"""(?i)(purchases-capacitor|react-native-purchases|REVENUECAT_)""",
                   '"@revenuecat/purchases-capacitor": "^9.0.0",'),
    "capacitor": (r"""["']@capacitor/core["']\s*:""",
                  '"@capacitor/core": "^6.1.0",'),
    "apns": (r"""(?i)(aioapns|["']apns2?["']\s*:|APNS_(KEY|TEAM|TOPIC))""",
             "APNS_KEY_ID="),
    "google-maps-platform-places-api-new": (
        r"""(?i)(places\.googleapis\.com|maps\.googleapis\.com|GOOGLE_(MAPS|PLACES)_API_KEY)""",
        "GOOGLE_MAPS_API_KEY="),
    "pwned-passwords": (r"""api\.pwnedpasswords\.com""",
                        'URL = "https://api.pwnedpasswords.com/range/"'),
    "signadoc": (r"""SIGNADOC_(URL|KEY|API)""", "SIGNADOC_URL="),
    "llm-apis": (r"""(?i)(^\s*(anthropic|openai)\s*[=<>~]|["'](@anthropic-ai/sdk|openai)["']\s*:|ANTHROPIC_API_KEY|OPENAI_API_KEY)""",
                 "anthropic==0.40.0"),
    "esv-api": (r"""api\.esv\.org""", 'ESV = "https://api.esv.org/v3/passage/text/"'),
    "youtube-api": (r"""googleapis\.com/youtube""", 'API = "https://www.googleapis.com/youtube/v3"'),
    "openstreetmap": (r"""(?i)(nominatim\.openstreetmap|tile\.openstreetmap\.org)""",
                      'TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"'),
    "mercury": (r"""api\.mercury\.com""", 'BASE = "https://api.mercury.com/api/v1"'),
    "quickbooks-online": (r"""(?i)(intuit-oauth|quickbooks\.api\.intuit\.com)""", "intuit-oauth==1.2"),
    "gmail-smtp": (r"""smtp\.gmail\.com""", 'MAIL_SERVER = "smtp.gmail.com"'),
    "tripleseat": (r"""(?i)api\.tripleseat\.com""", 'BASE = "https://api.tripleseat.com/v1"'),
}

# Steps on the Railway checklist a machine can see, by title.
RAILWAY_CHECKS = {
    "Create the project and the service": ("railway", "service", None),
    "Run migrations before cutover, not in the start command": ("railway", "pre_deploy", None),
    "Point the health check at a route that proves the database and the volume": ("railway", "healthcheck", None),
    "Add the custom domain and its DNS records": ("railway", "custom_domain", None),
    "Confirm the deploy came from the commit you think": ("railway", "deploy_current", None),
}


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table, column):
    if column.name not in _columns(table):
        with op.batch_alter_table(table) as batch:
            batch.add_column(column)


def _drop(table, name):
    if table in _tables() and name in _columns(table):
        with op.batch_alter_table(table) as batch:
            batch.drop_column(name)


def upgrade():
    existing = _tables()
    if "railway_services" not in existing:
        op.create_table(
            "railway_services",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider_id", sa.Integer(), sa.ForeignKey(
                "service_providers.id", ondelete="CASCADE",
                name="fk_railway_services_provider_id"), nullable=True),
            sa.Column("project_ref", sa.String(64), nullable=False),
            sa.Column("project_name", sa.String(200), nullable=True),
            sa.Column("service_ref", sa.String(64), nullable=False),
            sa.Column("service_name", sa.String(200), nullable=True),
            sa.Column("environment", sa.String(60), nullable=False, server_default="production"),
            sa.Column("repo", sa.String(200), nullable=True),
            sa.Column("image", sa.String(300), nullable=True),
            sa.Column("domains_json", sa.Text(), nullable=True),
            sa.Column("custom_domains_json", sa.Text(), nullable=True),
            sa.Column("deploy_status", sa.String(20), nullable=True),
            sa.Column("deploy_commit", sa.String(64), nullable=True),
            sa.Column("deploy_branch", sa.String(120), nullable=True),
            sa.Column("deployed_at", sa.DateTime(), nullable=True),
            sa.Column("healthcheck_path", sa.String(200), nullable=True),
            sa.Column("pre_deploy", sa.String(300), nullable=True),
            sa.Column("branch_head", sa.String(64), nullable=True),
            sa.Column("branch_head_at", sa.DateTime(), nullable=True),
            sa.Column("seen_at", sa.DateTime(), nullable=True),
            sa.Column("ignored", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.UniqueConstraint("service_ref", "environment", name="uq_railway_services_service_env"),
        )
        op.create_index("ix_railway_services_provider_id", "railway_services", ["provider_id"])
        op.create_index("ix_railway_services_project_ref", "railway_services", ["project_ref"])
        op.create_index("ix_railway_services_repo", "railway_services", ["repo"])
    if "site_checks" not in existing:
        op.create_table(
            "site_checks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("url", sa.String(500), nullable=False),
            sa.Column("host", sa.String(255), nullable=False, server_default=""),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("ok", sa.Boolean(), nullable=True),
            sa.Column("final_url", sa.String(500), nullable=True),
            sa.Column("error", sa.String(300), nullable=True),
            sa.Column("cert_expires_on", sa.Date(), nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.Column("down_since", sa.DateTime(), nullable=True),
            sa.Column("fail_nights", sa.Integer(), nullable=False, server_default="0"),
            sa.UniqueConstraint("url", name="uq_site_checks_url"),
        )
        op.create_index("ix_site_checks_host", "site_checks", ["host"])
    if "domain_watches" not in existing:
        op.create_table(
            "domain_watches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("domain", sa.String(255), nullable=False),
            sa.Column("expires_on", sa.Date(), nullable=True),
            sa.Column("auto_renew", sa.Boolean(), nullable=True),
            sa.Column("registrar", sa.String(40), nullable=True),
            sa.Column("checked_at", sa.DateTime(), nullable=True),
            sa.Column("error", sa.String(300), nullable=True),
            sa.UniqueConstraint("domain", name="uq_domain_watches_domain"),
        )

    _add("app_links", sa.Column("store_differ_since", sa.DateTime(), nullable=True))
    _add("app_links", sa.Column("repo_versions", sa.Text(), nullable=True))
    _add("playbooks", sa.Column("presence_pattern", sa.Text(), nullable=True))
    _add("playbooks", sa.Column("presence_globs", sa.String(300), nullable=True))
    _add("playbooks", sa.Column("presence_exclude", sa.String(300), nullable=True))
    _add("playbooks", sa.Column("presence_fixture", sa.Text(), nullable=True))
    _add("playbook_steps", sa.Column("check_kind", sa.String(12), nullable=True))
    _add("playbook_steps", sa.Column("check_target", sa.String(300), nullable=True))
    _add("playbook_steps", sa.Column("check_pattern", sa.Text(), nullable=True))

    bind = op.get_bind()
    for slug, (pattern, fixture) in SIGNATURES.items():
        bind.execute(sa.text(
            "UPDATE playbooks SET presence_pattern = :p, presence_globs = :g, "
            "presence_exclude = :x, presence_fixture = :f "
            "WHERE slug = :s AND presence_pattern IS NULL"),
            {"p": pattern, "g": CODE_GLOBS, "x": EXCLUDE, "f": fixture, "s": slug})
    for title, (kind, target, pattern) in RAILWAY_CHECKS.items():
        bind.execute(sa.text(
            "UPDATE playbook_steps SET check_kind = :k, check_target = :t, check_pattern = :p "
            "WHERE title = :title AND check_kind IS NULL AND playbook_id IN "
            "(SELECT id FROM playbooks WHERE slug = 'railway')"),
            {"k": kind, "t": target, "p": pattern, "title": title})


def downgrade():
    for name in ("check_pattern", "check_target", "check_kind"):
        _drop("playbook_steps", name)
    for name in ("presence_fixture", "presence_exclude", "presence_globs", "presence_pattern"):
        _drop("playbooks", name)
    for name in ("repo_versions", "store_differ_since"):
        _drop("app_links", name)
    existing = _tables()
    for table in ("domain_watches", "site_checks", "railway_services"):
        if table in existing:
            op.drop_table(table)
