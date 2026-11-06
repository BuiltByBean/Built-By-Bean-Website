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

`plain_error` is a failed sync said for a person, and `groups` is the page.
Every vendor knows its playbook (`playbook_for`): the tile wears the
playbook's mark and opens it, names the business maps it is a service on,
and the playbook's page lists the vendor's accounts (`accounts_for`).
"""
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


def run(today=None):
    """The night's step: the bank half (the code half rides the map check)."""
    lines = from_bank(today)
    return "; ".join(lines)[:500] or "nothing new"


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
