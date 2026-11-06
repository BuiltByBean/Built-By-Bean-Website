"""The vendors the board finds for itself, and how the Vendors page reads them.

Michael, 2026-11-05: "I feel like some vendors are for sure missing", and his
pick when asked what the board should do about one it spots: add it on its
own. The board already knows two places a vendor shows itself:

- **The bank.** A rule that settles a business charge (`VendorRule`, an
  expense or split in a business category) names a vendor somebody pays.
  OpenAI, Google Workspace, Squarespace Domains and LegalZoom were all
  charged and none had a tile. One account per vendor per company that pays.
- **The code.** The nightly map check reads each business's repos for every
  playbook's proven signature (`map_checks.vendors_in_repos`); a vendor the
  code uses with no account on file is noted from there (`note_code`).

What the night adds is an account of type "bank" or "code"
(`ServiceProvider.FOUND_TYPES`). It never syncs and never books money: the
bank line is the record (only the bank line makes an expense), and a twin
company is read by sync type, which these never share. A bank account is in
use while its vendor charged in the last `IN_USE_DAYS`; it moves to Not in use
on its own when the charges stop and back when they start.

- **The stores** (Michael, the same evening: "you should have known that a
  vendor's missing because we have an app on the fucking App Store"). A My
  Apps tile with an App Store bundle id is a paid Apple Developer Program
  membership, one with a Play package a Google Play Console account
  (`from_stores`), paid by the company whose logo is that tile, else Built by
  Bean.
- **Every repo the night reads** (`note_repo`, from `audit_repos`, which has
  already downloaded each one): a vendor's own key names and libraries in the
  code (`CODE_SIGNS`, defaults in code). His repos used Resend, Sentry,
  GitHub, Firebase, RevenueCat, Google Cloud and Hugging Face with none of them
  on the page.

What the board can find in its own records (bank, stores) it also finds at
boot (`start_background`), so a deploy does not wait for the night.

`plain_error` is a failed sync said for a person, and `groups` is the page.
Every vendor knows its playbook (`playbook_for`): the tile wears the
playbook's mark and opens it, names the business maps it is a service on,
and the playbook's page lists the vendor's accounts (`accounts_for`).
"""
import os
import re
from datetime import date, timedelta

# The categories a business pays a vendor under. Meals, travel, taxes and
# bank fees are charges, not vendors anybody runs anything on.
VENDOR_CATEGORIES = {"software", "hosting", "ai_services", "domain", "legal_professional",
                     "service_cost", "phone_internet", "advertising", "design", "subcontractor"}
IN_USE_DAYS = 90
YEAR_DAYS = 365


def key(name):
    """One vendor however it is written: "Google  Workspace" is google workspace."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def bare(name):
    """A name without the account in brackets: "Railway (EntertainHQ)"."""
    return re.sub(r"\s*\(.*\)\s*$", "", name or "").strip()


def _home_id():
    import books_service
    b = books_service.board_business()
    return b.id if b else None


def _payer(business_id, home):
    """The account_business_id an account paid by this company carries: None
    for the company the board bills from, which every older account means."""
    return None if business_id in (None, home) else business_id


def _paid_by(p):
    """("client", id) / ("business", id) / ("home", None) for an account."""
    if p.account_client_id:
        return ("client", p.account_client_id)
    if p.account_business_id:
        return ("business", p.account_business_id)
    return ("home", None)


def _accounts_by_vendor():
    from models import ServiceProvider
    out = {}
    for p in ServiceProvider.query.all():
        out.setdefault(key(p.vendor_name), []).append(p)
    return out


def _last_charge(rule_ids, since):
    from models import BankTransaction, db
    if not rule_ids:
        return None
    return (db.session.query(db.func.max(BankTransaction.occurred_on))
            .filter(BankTransaction.rule_id.in_(rule_ids), BankTransaction.amount < 0,
                    BankTransaction.occurred_on >= since).scalar())


def from_bank(today=None):
    """Add an account for every business vendor the bank pays that has none
    for that company, and keep each bank account's in use / not in use with
    its charges. Returns lines saying what changed."""
    from models import db, ServiceProvider, VendorRule
    today = today or date.today()
    home = _home_id()
    by_vendor = _accounts_by_vendor()
    rules = {}
    for r in VendorRule.query.filter(VendorRule.disposition.in_(("expense", "split"))).all():
        if (r.category or "") not in VENDOR_CATEGORIES or not (r.vendor or "").strip():
            continue
        rules.setdefault((key(r.vendor), _payer(r.business_id, home)), []).append(r)

    lines = []
    for (vkey, payer), rs in sorted(rules.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
        accounts = by_vendor.get(vkey, [])
        wanted = ("business", payer) if payer else ("home", None)
        last = _last_charge([r.id for r in rs], today - timedelta(days=YEAR_DAYS * 2))
        in_use = bool(last and last >= today - timedelta(days=IN_USE_DAYS))
        mine = [a for a in accounts if _paid_by(a) == wanted]
        if any(a.syncs for a in mine):
            # A real account now stands where the bank's placeholder did.
            for a in [a for a in mine if a.name == "bank"]:
                db.session.delete(a)
                lines.append(f"{a.vendor_name}: the bank's placeholder gave way to its account")
            continue
        if mine:
            for a in mine:
                if a.name == "bank" and a.is_active != in_use:
                    a.is_active = in_use
                    lines.append(f"{a.vendor_name}: {'in use' if in_use else 'not in use'}")
            continue
        if not last:
            continue  # a rule nothing has matched yet is not a vendor anybody pays
        name = bare(rs[0].vendor.strip())
        row = ServiceProvider(
            name="bank", display_name=name, vendor=name, is_active=in_use,
            account_business_id=payer, credentials_json="{}",
            discovered_from=f"bank: {rs[0].pattern}"[:200])
        db.session.add(row)
        lines.append(f"{name}: found on the bank")
        by_vendor.setdefault(vkey, []).append(row)
    db.session.commit()
    return lines


def replace_found(provider):
    """A real account added for a vendor takes the place of what the night
    found for the same vendor and payer: the bank's placeholder for that
    company, and any "in the code" stand-in. Does not commit."""
    from models import db, ServiceProvider
    if not provider.syncs:
        return 0
    gone = 0
    for a in ServiceProvider.query.filter(ServiceProvider.name.in_(ServiceProvider.FOUND_TYPES),
                                          ServiceProvider.id != provider.id).all():
        if key(a.vendor_name) != key(provider.vendor_name):
            continue
        if a.name == "code" or _paid_by(a) == _paid_by(provider):
            db.session.delete(a)
            gone += 1
    return gone


def note_code(playbook, business, repos):
    """A vendor the code of `business`'s apps uses: an account for it when the
    board has none for that vendor at all. Called from the nightly map check,
    which has just read the repos. Does not commit."""
    from models import db, ServiceProvider
    name = bare(playbook.display_name)
    if not name or _accounts_by_vendor().get(key(name)):
        return None
    where = ", ".join(sorted({r for r in repos}))[:180]
    db.session.add(ServiceProvider(
        name="code", display_name=name, vendor=name, is_active=True,
        account_business_id=_payer(business.id, _home_id()), credentials_json="{}",
        discovered_from=f"code: {where}"[:200]))
    return name


# A vendor's own words in code: the names of its keys and its libraries. Only
# the unmistakable ones, because a vendor found here is a tile on the page.
CODE_SIGNS = {
    "Resend": r"\bRESEND_API_KEY\b|\bimport resend\b|\bfrom resend\b|['\"]resend['\"]\s*:",
    "Sentry": r"\bSENTRY_DSN\b|\bsentry_sdk\b|['\"]@sentry/",
    "GitHub": r"\bGITHUB_TOKEN\b|api\.github\.com",
    "Twilio": r"\bTWILIO_(?:ACCOUNT_SID|AUTH_TOKEN|API_KEY)\b|\bfrom twilio\b|['\"]twilio['\"]\s*:",
    "Stripe": r"\bSTRIPE_SECRET_KEY\b|^\s*import stripe\b|['\"]stripe['\"]\s*:",
    "Anthropic API": r"\bANTHROPIC_API_KEY\b|^\s*import anthropic\b|['\"]@anthropic-ai/",
    "OpenAI API": r"\bOPENAI_API_KEY\b|^\s*import openai\b|^\s*from openai\b",
    "Firebase": r"\bFCM_[A-Z_]+\b|\bfirebase_admin\b|['\"]firebase(?:-admin)?['\"]\s*:|fcm\.googleapis\.com",
    "Apple Developer Program": r"\bAPNS_[A-Z_]+\b|api\.push\.apple\.com",
    "RevenueCat": r"\bREVENUECAT_[A-Z_]+\b|['\"]@revenuecat/|['\"]react-native-purchases['\"]",
    "Google Cloud": r"\bGOOGLE_(?:MAPS|PLACES)_[A-Z_]*KEY\b|maps\.googleapis\.com|places\.googleapis\.com",
    "Hugging Face": r"\bHF_TOKEN\b|\bHUGGINGFACE_[A-Z_]+\b|\bhuggingface_hub\b",
    "Postmark": r"\bPOSTMARK_[A-Z_]+\b|api\.postmarkapp\.com",
    "SendGrid": r"\bSENDGRID_API_KEY\b|api\.sendgrid\.com",
    "Mailgun": r"\bMAILGUN_[A-Z_]+\b|api\.mailgun\.net",
    "OneSignal": r"\bONESIGNAL_[A-Z_]+\b|onesignal\.com/api",
    "Mapbox": r"\bMAPBOX_[A-Z_]+\b|api\.mapbox\.com",
    "PostHog": r"\bPOSTHOG_[A-Z_]+\b|['\"]posthog-js['\"]",
    "Supabase": r"\bSUPABASE_[A-Z_]+\b|['\"]@supabase/",
    "ElevenLabs": r"\bELEVENLABS_[A-Z_]+\b|api\.elevenlabs\.io",
    "Deepgram": r"\bDEEPGRAM_[A-Z_]+\b|api\.deepgram\.com",
    "Expo": r"['\"]eas-cli['\"]|\bEXPO_TOKEN\b|expo\.dev/accounts",
    "Cloudflare": r"\bCLOUDFLARE_API_TOKEN\b|\bR2_ACCOUNT_ID\b|\bR2_ACCESS_KEY_ID\b",
}
CODE_FILES = (".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".jsonc", ".toml", ".yml", ".yaml", ".example", ".cfg", ".txt")
# A word each sign needs, checked on the lowercased text before its pattern
# runs: the patterns alone took 30 seconds on a repo of a thousand files.
CODE_HINTS = {
    "Resend": ("resend",), "Sentry": ("sentry",), "GitHub": ("github_token", "api.github.com"),
    "Twilio": ("twilio",), "Stripe": ("stripe",), "Anthropic API": ("anthropic",), "OpenAI API": ("openai",),
    "Firebase": ("fcm", "firebase"), "Apple Developer Program": ("apns", "push.apple.com"),
    "RevenueCat": ("revenuecat", "react-native-purchases"), "Google Cloud": ("googleapis", "google_maps", "google_places"),
    "Hugging Face": ("hf_token", "huggingface"), "Postmark": ("postmark",), "SendGrid": ("sendgrid",),
    "Mailgun": ("mailgun",), "OneSignal": ("onesignal",), "Mapbox": ("mapbox",), "PostHog": ("posthog",),
    "Supabase": ("supabase",), "ElevenLabs": ("elevenlabs",), "Deepgram": ("deepgram",),
    "Expo": ("eas-cli", "expo_token", "expo.dev"), "Cloudflare": ("cloudflare_api_token", "r2_"),
}
# Not the repo's running code: dependencies, build output, and the places a
# repo talks ABOUT vendors (docs, tests, migrations, seeds and fixtures). The
# board's own playbooks name Postmark and RevenueCat without using either.
NOT_CODE = ("node_modules/", "/vendor/", ".venv/", "venv/", "/dist/", "/build/", "package-lock",
            "tools/", "tests/", "test_", "/test/", "migrations/", "docs/", "fixture", "seed",
            "vendor_discovery.py", "map_checks.py", "/scripts/", "scripts/")
_COMPILED = None


def _signs():
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = {name: re.compile(rx, re.M) for name, rx in CODE_SIGNS.items()}
    return _COMPILED


def vendors_in_files(files):
    """{vendor: path of the first file that shows it} for one repo's files
    ({path: text}). Only the repo's own running code is read."""
    found = {}
    signs = _signs()
    for path, text in (files or {}).items():
        low = path.lower()
        if any(part in low for part in NOT_CODE):
            continue
        if not low.endswith(CODE_FILES) and "/.env" not in low and not low.startswith(".env"):
            continue
        if not isinstance(text, str):
            continue
        if low.endswith(("wrangler.toml", "wrangler.jsonc")):
            found.setdefault("Cloudflare", path)
        lower = text.lower()
        for name, rx in signs.items():
            if name in found or not any(h in lower for h in CODE_HINTS.get(name, ())):
                continue
            if rx.search(text):
                found[name] = path
        if len(found) == len(signs):
            break
    return found


def _payer_for_repo(repo):
    """The company whose app this repo is (its logo is the repo's My Apps
    tile), as the account_business_id a found account carries."""
    from models import AppLink, Business
    want = (repo or "").lower().strip("/")
    for tile in AppLink.query.filter(AppLink.github_url.isnot(None)).all():
        if (tile.github_url or "").lower().rstrip("/").endswith("/" + want):
            biz = Business.query.filter_by(logo_app_id=tile.id).first()
            if biz is not None:
                return _payer(biz.id, _home_id())
    return None


def _note(name, payer, where, kind="code"):
    """An account for a vendor nobody has set up, found in the code or the
    stores. One per vendor: a vendor that has any account is left alone. Does
    not commit."""
    from models import db, ServiceProvider
    if not name or _accounts_by_vendor().get(key(name)):
        return None
    db.session.add(ServiceProvider(
        name="code", display_name=name, vendor=name, is_active=True,
        account_business_id=payer, credentials_json="{}",
        discovered_from=f"{kind}: {where}"[:200]))
    db.session.flush()
    return name


def note_repo(repo, files):
    """What one repo's code says it pays for (the nightly audit calls this
    with the files it has already downloaded). Returns the vendors added."""
    payer = _payer_for_repo(repo)
    return [n for n in (_note(name, payer, repo) for name in vendors_in_files(files)) if n]


def from_stores():
    """A store listing is a paid developer account: the App Store's is the
    Apple Developer Program, Play's is the Google Play Console."""
    from models import AppLink, Business, db
    lines = []
    for tile in AppLink.query.order_by(AppLink.id).all():
        biz = Business.query.filter_by(logo_app_id=tile.id).first()
        payer = _payer(biz.id, _home_id()) if biz is not None else None
        if (tile.app_store_bundle_id or "").strip():
            if _note("Apple Developer Program", payer, f"{tile.name} on the App Store", kind="store"):
                lines.append("Apple Developer Program: found from the App Store")
        if (tile.play_package or "").strip():
            if _note("Google Play", payer, f"{tile.name} on Google Play", kind="store"):
                lines.append("Google Play: found from Google Play")
    db.session.commit()
    return lines


def run_free(today=None):
    """Everything the board can find from its own records: the bank and the
    stores. The night runs it, and so does the web at boot."""
    return from_bank(today) + from_stores()


def run(today=None):
    """The night's step (the code half rides the nightly audit)."""
    lines = run_free(today)
    return "; ".join(lines)[:500] or "nothing new"


_timer = {"started": False}


def start_background(app):
    """Once a minute after boot and then daily, on the web service, so a
    deploy shows what the board can already find. Two workers each start one;
    a Postgres advisory lock lets one of them do it."""
    import threading
    import time
    if _timer["started"] or os.environ.get("VENDOR_DISCOVERY_DISABLED") == "1":
        return
    _timer["started"] = True

    def loop():
        time.sleep(60)
        while True:
            try:
                with app.app_context():
                    from models import db
                    got = True
                    if db.engine.dialect.name == "postgresql":
                        got = db.session.execute(db.text("SELECT pg_try_advisory_xact_lock(84412017)")).scalar()
                    if got:
                        lines = run_free()
                        if lines:
                            print("vendors: " + "; ".join(lines), flush=True)
                    db.session.commit()
            except Exception as err:  # noqa: BLE001 - a missed pass is tomorrow's
                print(f"vendors: {str(err)[:200]}", flush=True)
            time.sleep(24 * 3600)

    threading.Thread(target=loop, daemon=True, name="vendor-discovery").start()


# ------------------------------------------------------------- the page

def plain_error(provider):
    """A failed sync in words a person can act on, or None."""
    err = (provider.sync_error or "").strip()
    if not err:
        return None
    who = provider.vendor_name
    low = err.lower()
    if "401" in low or "403" in low or "unauthorized" in low or "forbidden" in low \
            or "authenticat" in low or "invalid api key" in low:
        return (f"{who} turned the key down. Make a new key on this {who} account "
                f"and paste it in with Edit.")
    if "timed out" in low or "timeout" in low or "max retries" in low or "connection" in low:
        return f"{who} did not answer. The next sync tries again."
    if "not found" in low or "404" in low:
        return f"{who} says this account is not there. Check the account on Edit."
    return err[:200]


def spend(provider, today=None):
    """What this account cost in the last year: what its vendor reported, or
    for an account the night found, the bank's charges for that vendor paid
    by that company. None when there is nothing to read."""
    from models import db, BankTransaction, ServiceCostEntry, VendorRule
    today = today or date.today()
    since = today - timedelta(days=YEAR_DAYS)
    if provider.syncs:
        total = (db.session.query(db.func.coalesce(db.func.sum(ServiceCostEntry.allocated_amount), 0.0))
                 .filter(ServiceCostEntry.provider_id == provider.id,
                         ServiceCostEntry.period_end >= since).scalar())
        return round(total or 0.0, 2) if total else None
    if provider.name != "bank":
        return None
    home = _home_id()
    rule_ids = [r.id for r in VendorRule.query.all()
                if key(r.vendor) == key(provider.vendor_name)
                and _payer(r.business_id, home) == provider.account_business_id]
    if not rule_ids:
        return None
    total = (db.session.query(db.func.coalesce(db.func.sum(BankTransaction.amount), 0.0))
             .filter(BankTransaction.rule_id.in_(rule_ids), BankTransaction.amount < 0,
                     BankTransaction.disposition.in_(("expense", "split")),
                     BankTransaction.occurred_on >= since).scalar())
    return round(-(total or 0.0), 2) if total else None


def playbook_for(name, accounts, playbooks=None):
    """The playbook (one vendor's runbook) this vendor is: the one pointed at
    one of its accounts, else the one its name names (map_checks' words, the
    same reading the night uses on the code and the books). None when the
    board has no runbook for it. Michael, 2026-11-05: "ensure something knows
    that a vendor will connect to a service that we have a blueprint for"."""
    import map_checks
    from models import Playbook
    if playbooks is None:
        playbooks = Playbook.query.filter_by(is_active=True).order_by(Playbook.sort_order, Playbook.id).all()
    ids = {a.id for a in accounts}
    hit = next((p for p in playbooks if p.service_provider_id in ids), None)
    if hit is not None:
        return hit
    named = [p for p in playbooks if key(p.display_name) == key(name)]
    if named:
        return named[0]
    words = [p for p in playbooks if map_checks.names_vendor(name, p)]
    return words[0] if len(words) == 1 else None


def accounts_for(playbook):
    """Every account of the vendor a playbook is, for the playbook's page."""
    from models import ServiceProvider
    by_vendor = _accounts_by_vendor()
    playbooks = [playbook]
    out = []
    for vkey, accounts in by_vendor.items():
        if playbook_for(accounts[0].vendor_name, accounts, playbooks) is playbook:
            out.extend(accounts)
    return sorted(out, key=lambda a: (not a.is_active, a.display_name or ""))


def maps_for(playbook):
    """The businesses whose map has this vendor as a service."""
    from models import Business, BusinessNode
    if playbook is None:
        return []
    ids = {n.business_id for n in BusinessNode.query.filter_by(kind="service", playbook_id=playbook.id).all()}
    return Business.query.filter(Business.id.in_(ids)).order_by(Business.name).all() if ids else []


def groups(providers, today=None):
    """One entry per vendor, its accounts under it, in name order:
    {"name", "key", "accounts": [...], "in_use", "spend", "trouble"}."""
    out = {}
    for p in providers:
        g = out.setdefault(key(p.vendor_name), {"name": p.vendor_name, "key": key(p.vendor_name),
                                                "accounts": [], "in_use": False, "spend": 0.0,
                                                "trouble": 0})
        cost = spend(p, today)
        g["accounts"].append({"provider": p, "spend": cost, "error": plain_error(p),
                              "used_by": sorted({m.project.name for m in p.mappings
                                                 if m.is_active and m.project is not None})})
        g["in_use"] = g["in_use"] or bool(p.is_active)
        g["spend"] += cost or 0.0
        g["trouble"] += 1 if (p.is_active and p.syncs and p.sync_error) else 0
    from models import Playbook
    playbooks = Playbook.query.filter_by(is_active=True).order_by(Playbook.sort_order, Playbook.id).all()
    for g in out.values():
        g["accounts"].sort(key=lambda a: (not a["provider"].is_active, a["provider"].display_name or ""))
        g["spend"] = round(g["spend"], 2)
        g["playbook"] = playbook_for(g["name"], [a["provider"] for a in g["accounts"]], playbooks)
        g["maps"] = maps_for(g["playbook"])
    return sorted(out.values(), key=lambda g: g["name"].lower())
