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


def from_bank(today=None):
    """The books' reading (from_books). It read one bank rule per vendor until
    2026-11-06, which put every charge under the rule's company and missed a
    company's own plan with the same vendor."""
    return from_books(today)

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
        # A DBA has no developer account of its own: its listing is under its
        # company's (Michael, 2026-11-06: "I do not have a data dungeon apple
        # developer program account. I have only a built by beans account").
        payer = _family(_payer(biz.id, _home_id())) if biz is not None else None
        if (tile.app_store_bundle_id or "").strip():
            if _note("Apple Developer Program", payer, f"{tile.name} on the App Store", kind="store"):
                lines.append("Apple Developer Program: found from the App Store")
        if (tile.play_package or "").strip():
            if _note("Google Play", payer, f"{tile.name} on Google Play", kind="store"):
                lines.append("Google Play: found from Google Play")
    db.session.commit()
    return lines


def run_free(today=None):
    """Everything the board can find from its own records: the books, the
    bank and the stores. The night runs it, and so does the web at boot."""
    return from_books(today) + from_stores()


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
    """What this account cost in the last year: what its company's books say
    it paid this vendor (`books_by_vendor`), else, for an account on a
    client's card that no book of ours holds, what the vendor reported. None
    when there is nothing to read. Until 2026-11-06 a found account was costed
    by one bank rule, which left EntertainHQ's own Claude plan and the Apple
    Developer Program at nothing (issue #18)."""
    from models import db, ServiceCostEntry
    today = today or date.today()
    books = _books(today).get((key(provider.vendor_name), _paid_by(provider)))
    if books:
        return round(books["year"], 2)
    if provider.syncs and _paid_by(provider)[0] == "client":
        since = today - timedelta(days=YEAR_DAYS)
        total = (db.session.query(db.func.coalesce(db.func.sum(ServiceCostEntry.allocated_amount), 0.0))
                 .filter(ServiceCostEntry.provider_id == provider.id,
                         ServiceCostEntry.period_end >= since).scalar())
        return round(total or 0.0, 2) if total else None
    return None


# What a description that names no vendor plainly is made by.
ALIASES = {"anthropic": "Claude", "claude ai": "Claude", "anthropic claude sub": "Claude"}


def known_vendors():
    """Every vendor name the board knows: its accounts, the bank's business
    rules, the code's signs and the stores'."""
    from models import ServiceProvider, VendorRule
    names = {key(p.vendor_name): p.vendor_name for p in ServiceProvider.query.all()}
    for r in VendorRule.query.filter(VendorRule.disposition.in_(("expense", "split"))).all():
        if (r.category or "") in VENDOR_CATEGORIES and (r.vendor or "").strip():
            names.setdefault(key(bare(r.vendor)), bare(r.vendor))
    for n in list(CODE_SIGNS) + ["Apple Developer Program", "Google Play"]:
        names.setdefault(key(n), n)
    return names


def vendor_of(expense, line, names):
    """The vendor an expense is, or None: its bank line's rule, else the
    longest known vendor name its description begins with."""
    if line is not None and line.rule_id:
        from models import db, VendorRule
        rule = db.session.get(VendorRule, line.rule_id)
        if rule is not None and key(bare(rule.vendor)) in names:
            return names[key(bare(rule.vendor))]
    desc = key(expense.description)
    for alias, name in ALIASES.items():
        if desc.startswith(alias):
            return names.get(key(name), name)
    best = None
    for k, name in names.items():
        if k and (desc == k or desc.startswith(k + " ")) and (best is None or len(k) > len(key(best))):
            best = name
    return best


_BOOKS = {"at": None, "data": None}


def _books(today=None):
    """{(vendor key, paid by): {"vendor", "year", "last", "first"}} from every
    company's expenses of the last two years: what each company was charged
    by each vendor. Read once per request or pass."""
    from models import db, Expense, BankTransaction
    today = today or date.today()
    try:
        from flask import g, has_request_context
        if has_request_context() and getattr(g, "_vendor_books", None) is not None:
            return g._vendor_books
    except Exception:  # noqa: BLE001
        g = None
    names = known_vendors()
    home = _home_id()
    out = {}
    since = today - timedelta(days=YEAR_DAYS * 2)
    # A charge the bank booked whole points at its expense (line.expense_id);
    # one split across projects is pointed at by each share (bank_line_id).
    by_expense = {t.expense_id: t for t in BankTransaction.query.filter(
        BankTransaction.expense_id.isnot(None), BankTransaction.occurred_on >= since).all()}
    by_id = {}
    for e in (Expense.query.filter(Expense.time_entry_id.is_(None), Expense.date >= since,
                                   Expense.amount > 0).all()):
        line = by_expense.get(e.id)
        if line is None and getattr(e, "bank_line_id", None):
            line = by_id.get(e.bank_line_id) or db.session.get(BankTransaction, e.bank_line_id)
            by_id[e.bank_line_id] = line
        vendor = vendor_of(e, line, names)
        if not vendor:
            continue
        payer = _payer(e.business_id, home)
        who = ("business", payer) if payer else ("home", None)
        row = out.setdefault((key(vendor), who), {"vendor": vendor, "year": 0.0, "last": e.date, "first": e.date,
                                                  "business_id": payer, "what": e.description, "dates": []})
        row["dates"].append(e.date)
        if e.date >= today - timedelta(days=YEAR_DAYS):
            row["year"] += e.amount
        row["last"] = max(row["last"], e.date)
        row["first"] = min(row["first"], e.date)
    try:
        from flask import g as _g, has_request_context as _h
        if _h():
            _g._vendor_books = out
    except Exception:  # noqa: BLE001
        pass
    return out


def in_use_by_rhythm(dates, today):
    """Whether a vendor still charges: within one and a half of its usual gap
    since the last charge (never under IN_USE_DAYS), or, with one charge only,
    within thirteen months, because a yearly membership (Apple's developer
    program) charges once a year and read as stopped after ninety days."""
    days = sorted(set(dates))
    if not days:
        return False
    last = days[-1]
    if len(days) < 2:
        return (today - last).days <= 400
    gaps = sorted((b - a).days for a, b in zip(days, days[1:]))
    usual = gaps[len(gaps) // 2]
    return (today - last).days <= max(IN_USE_DAYS, int(usual * 1.5))


def _family(business_id):
    """A company and its DBAs as one payer: Data Dungeon's App Store listing
    is Built by Bean's developer account."""
    from models import db, Business
    if business_id is None:
        return None
    b = db.session.get(Business, business_id)
    if b is not None and b.parent_id:
        return _payer(b.parent_id, _home_id())
    return business_id


def from_books(today=None):
    """An account for every vendor each company's books show it paying, where
    that company has none: one per vendor per company charged (Michael,
    2026-11-06: LegalZoom formed both LLCs, EntertainHQ has its own Claude
    plan). In use by the vendor's own rhythm (`in_use_by_rhythm`). Then the
    stand-ins give way: a vendor found only in the code or a store listing,
    and an account the old rule-based reading made for a company the books
    never show paying, are taken off once the vendor has a real account in
    that company's family. An account kept by other evidence (`mail:`) stays.
    Returns lines saying what changed."""
    from models import db, ServiceProvider
    today = today or date.today()
    books = _books(today)
    by_vendor = _accounts_by_vendor()
    lines = []
    for (vkey, who), row in sorted(books.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        in_use = in_use_by_rhythm(row["dates"], today)
        mine = [a for a in by_vendor.get(vkey, []) if _paid_by(a) == who]
        if mine:
            for a in mine:
                if not a.syncs and a.is_active != in_use:
                    a.is_active = in_use
                    lines.append(f"{a.vendor_name}: {'in use' if in_use else 'not in use'}")
            continue
        acct = ServiceProvider(name="bank", display_name=row["vendor"], vendor=row["vendor"], is_active=in_use,
                               account_business_id=row["business_id"], credentials_json="{}",
                               discovered_from=f"books: {row['what']}"[:200])
        db.session.add(acct)
        by_vendor.setdefault(vkey, []).append(acct)
        lines.append(f"{row['vendor']}: found in the books")

    paid = {(vkey, _family(who[1]) if who[0] == "business" else None) for (vkey, who) in books}
    for vkey, accounts in by_vendor.items():
        real = [a for a in accounts if a.syncs or (vkey, _family(a.account_business_id)
                                                   if _paid_by(a)[0] == "business" else None) in paid]
        for a in accounts:
            if a.id is None or a.syncs or (a.discovered_from or "").startswith("mail:"):
                continue
            fam = _family(a.account_business_id) if _paid_by(a)[0] == "business" else None
            if a.name == "code":
                # In the code or a store listing: a stand-in until money shows.
                if any(r is not a and (r.syncs or r.name == "bank") and
                       (_family(r.account_business_id) if _paid_by(r)[0] == "business" else None) == fam
                       for r in real + accounts):
                    db.session.delete(a)
                    lines.append(f"{a.vendor_name}: the books' account stands for the stand-in")
            elif a.name == "bank" and (vkey, fam) not in paid:
                # Made by the old rule-based reading for a company never charged.
                db.session.delete(a)
                lines.append(f"{a.vendor_name}: no charge to {a.account_business.name if a.account_business else 'Built by Bean'} in the books")
    db.session.commit()
    return lines


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
