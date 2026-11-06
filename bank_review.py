"""The bank review list, settled without the paid API.

Michael, 2026-11-04: everything automated, and nothing on the server calls a
paid model. Two halves (docs/automation_gaps.md, item 2):

1. A suggestion for every waiting line, worked out from what the board already
   holds, in this order, the first that answers winning:
     history   how the same counterparty was settled by hand before (a line
               settled without "remember" leaves no rule, but it is still an
               answer, and two that agree are a confident one)
     receipt   a receipt in the mailbox for the same amount to the cent within
               days, which names the vendor; and when that receipt already
               proves an expense, that expense's company and category
     vendor    a vendor the board already works with (its providers and its
               playbooks), by name
     category  the bank's own merchant category (Mercury's, or the Category
               column of a Chase card export) mapped to an expense category;
               on an owner's personal card a restaurant or a shop is personal
   Only `history`, `receipt` and `vendor` carry a pattern, so only they write a
   rule when accepted. A category guess settles its one line and teaches
   nothing, because "Food & Drink" is not a vendor.

2. What is left goes to a Claude Code session on Michael's Max plan (the /bank
   skill, .claude/skills/bank/SKILL.md) through the door:
   GET /api/guidance/bank/review is everything a session needs to judge the
   lines, and POST /api/guidance/bank/decide settles them and writes the rules,
   through the same bank_feed.decide the review page uses.
"""
import json
import re
from datetime import timedelta

# The bank's words for a kind of merchant -> the expense category. Mercury's
# categories and Chase's export column both; matched as lower-case substrings,
# first hit wins, so the specific ones come first.
CATEGORY_WORDS = [
    (("software", "saas", "computer", "digital good", "subscription"), "software"),
    (("web hosting", "cloud", "data processing", "information services"), "hosting"),
    (("advertis", "marketing"), "advertising"),
    (("restaurant", "food & drink", "food and drink", "dining", "coffee", "fast food", "bar"), "meals"),
    (("airline", "air travel", "hotel", "lodging", "travel", "car rental", "taxi", "rideshare",
      "parking", "toll"), "travel"),
    (("telecom", "phone", "internet", "cable", "utilities", "bills & utilities"), "phone_internet"),
    (("office", "stationery", "supplies", "shipping", "postage", "courier"), "office"),
    (("government", "tax", "licen"), "taxes_licenses"),
    (("legal", "accounting", "professional service", "consult"), "legal_professional"),
    (("education", "book", "course", "school"), "education"),
    (("electronics", "hardware"), "hardware"),
    (("bank", "fees & adjustments", "financial"), "bank_fees"),
]
# On an owner's own card these are their life, not the business's, unless a
# history, receipt or vendor answer says otherwise (bank_feed.SUGGEST_SYSTEM
# said the same to the paid model).
PERSONAL_WORDS = ("food & drink", "restaurant", "dining", "groceries", "grocery", "gas", "fuel",
                  "shopping", "entertainment", "health", "personal", "home", "gifts", "automotive",
                  "travel", "fast food", "coffee", "bar")

# Vendors the board's own work buys, by the word on the charge. Playbooks add
# their display names at run time as software.
KNOWN_VENDORS = {
    "railway": "hosting", "cloudflare": "hosting", "aws": "hosting", "amazon web services": "hosting",
    "heroku": "hosting", "vercel": "hosting", "netlify": "hosting", "digitalocean": "hosting",
    "github": "software", "google workspace": "software", "gsuite": "software", "sentry": "software",
    "resend": "software", "postmark": "software", "twilio": "software", "stripe": "bank_fees",
    "anthropic": "ai_services", "claude": "ai_services", "openai": "ai_services", "chatgpt": "ai_services",
    "namecheap": "domain", "godaddy": "domain", "squarespace": "software", "apple developer": "software",
    "google play": "software", "figma": "software", "notion": "software", "legalzoom": "legal_professional",
    "texas comptroller": "taxes_licenses", "comptroller": "taxes_licenses",
}

_DIGITS = re.compile(r"\d")
# Card networks, processors and other noise a counterparty carries in front of
# or around the vendor's name.
_NOISE = {"SQ", "TST", "POS", "PURCHASE", "DEBIT", "CARD", "RECURRING", "ONLINE", "WWW", "COM",
          "HTTPS", "HTTP", "INC", "LLC", "CO", "CORP", "THE", "PAYPAL", "PP", "SP", "DBA", "IN", "US",
          "USA", "TX", "CA", "NY", "WA", "BILL", "PAYMENT", "AUTOPAY", "ACH", "DES", "ID", "INDN"}


def counterparty_key(text):
    """The stable part of a counterparty, the words a vendor's every charge
    carries: 'SQ *BLUE BOTTLE 0123 OAKLAND CA' and 'SQ *BLUE BOTTLE 0456' are
    both 'BLUE BOTTLE OAKLAND' and 'BLUE BOTTLE', so only the first two words are
    kept, which is also the pattern a rule is written with."""
    import bank_feed
    words = [w for w in bank_feed.norm(text).split()
             if not _DIGITS.search(w) and w not in _NOISE and len(w) > 1]
    return " ".join(words[:2])


def _category_for(words):
    low = (words or "").lower()
    if not low:
        return None
    for keys, category in CATEGORY_WORDS:
        if any(k in low for k in keys):
            return category
    return None


def _known_vendors():
    from models import Playbook
    known = dict(KNOWN_VENDORS)
    try:
        for p in Playbook.query.filter_by(is_active=True).all():
            name = (p.display_name or "").strip().lower()
            if len(name) >= 4 and name not in known:
                known[name] = "software"
    except Exception:  # noqa: BLE001 - a suggestion never fails a night
        pass
    return known


def _from_history(line, key):
    """The same counterparty, settled by hand before."""
    from models import BankTransaction
    if not key:
        return None
    past = (BankTransaction.query.filter(BankTransaction.id != line.id,
                                         BankTransaction.decided_at.isnot(None),
                                         BankTransaction.disposition.notin_(("review", "void")))
            .order_by(BankTransaction.decided_at.desc()).limit(400).all())
    same = [p for p in past if counterparty_key(p.counterparty) == key]
    if not same:
        return None
    last = same[0]
    agree = [p for p in same if p.disposition == last.disposition]
    expense = last.expense
    return {"disposition": last.disposition,
            "vendor": (expense.description.split(" - ")[0] if expense and expense.description
                       else key.title()),
            "pattern": key,
            "business_id": (expense.business_id if expense else None) or last.business_id,
            "category": (expense.category if expense else None) or "misc",
            "project_id": (expense.project_id if expense else None) or 0,
            "owner_name": last.owner_name or "",
            "confidence": "high" if len(agree) >= 2 and len(agree) == len(same) else "medium",
            "why": f"{key.title()} was settled as {last.disposition} by hand "
                   f"{len(same)} time{'' if len(same) == 1 else 's'} before",
            "source": "history"}


def _from_receipt(line, key):
    """A receipt in a mailbox for this charge, to the cent, within days."""
    from models import Receipt
    import receipts_service
    if line.amount >= 0:
        return None
    target = round(-line.amount, 2)
    rows = Receipt.query.filter(Receipt.received_on >= line.occurred_on - timedelta(days=10),
                                Receipt.received_on <= line.occurred_on + timedelta(days=5)).all()
    hits = []
    for r in rows:
        amounts = {round(r.amount, 2)} if r.amount else set()
        try:
            amounts |= receipts_service.candidate_amounts(r)
        except Exception:  # noqa: BLE001 - a file that will not read keeps its first amount
            pass
        if any(abs(a - target) < 0.005 for a in amounts):
            hits.append(r)
    if not hits:
        return None
    # A receipt that names a word of the charge beats one that only costs the same.
    said = set(key.lower().split())
    hits.sort(key=lambda r: (not (said & set(re.findall(r"[a-z]{3,}",
                                                        f"{r.vendor} {r.sender}".lower()))),
                             abs((r.received_on - line.occurred_on).days), r.id))
    r = hits[0]
    expense = r.expense
    known = _known_vendors()
    vendor = r.vendor or key.title()
    category = (expense.category if expense else None) or next(
        (c for name, c in known.items() if name in vendor.lower()), None) or "misc"
    business = (expense.business_id if expense else None) or \
        (r.mailbox.business_id if r.mailbox else None) or line.business_id
    named = bool(said & set(re.findall(r"[a-z]{3,}", f"{r.vendor} {r.sender}".lower())))
    return {"disposition": "expense", "vendor": vendor, "pattern": key if named else "",
            "business_id": business, "category": category,
            "project_id": (expense.project_id if expense else None) or 0, "owner_name": "",
            "confidence": "high" if named and len(hits) == 1 else "medium",
            "why": f"A receipt from {vendor} for ${target:,.2f} arrived "
                   f"{r.received_on:%b %d}".replace(" 0", " "),
            "source": "receipt"}


def _from_vendor(line, key):
    import bank_feed
    hay = f" {bank_feed.norm(line.counterparty)} {bank_feed.norm(line.description)} ".lower()
    for name, category in sorted(_known_vendors().items(), key=lambda kv: -len(kv[0])):
        if f" {name} " in hay or (len(name) >= 6 and name.replace(" ", "") in hay.replace(" ", "")):
            pattern = bank_feed.norm(name)
            return {"disposition": "expense", "vendor": name.title(), "pattern": pattern,
                    "business_id": line.business_id, "category": category, "project_id": 0,
                    "owner_name": "", "confidence": "medium",
                    "why": f"{name.title()} is a vendor the board already works with",
                    "source": "vendor"}
    return None


def _from_category(line, key):
    import bank_feed
    words = line.merchant_category or line.bank_category or ""
    if bank_feed.is_personal(line):
        if line.amount > 0:
            return {"disposition": "transfer", "vendor": key.title() or "Money in", "pattern": "",
                    "business_id": line.business_id, "category": "misc", "project_id": 0,
                    "owner_name": "", "confidence": "medium",
                    "why": "Money in on a personal account is a refund or a payment, never income",
                    "source": "category"}
        if any(w in words.lower() for w in PERSONAL_WORDS):
            return {"disposition": "personal", "vendor": key.title(), "pattern": "",
                    "business_id": line.business_id, "category": "misc", "project_id": 0,
                    "owner_name": "", "confidence": "low",
                    "why": f"{words} on a personal card", "source": "category"}
    category = _category_for(words)
    if category is None:
        return None
    return {"disposition": "expense", "vendor": key.title(), "pattern": "",
            "business_id": line.business_id, "category": category, "project_id": 0,
            "owner_name": "", "confidence": "low",
            "why": f"The bank calls it {words}", "source": "category"}


def suggest_line(line):
    """The board's own suggestion for one waiting line, or None."""
    key = counterparty_key(line.counterparty) or counterparty_key(line.description)
    for source in (_from_history, _from_receipt, _from_vendor, _from_category):
        got = source(line, key)
        if got is not None:
            return got
    return None


def suggest_free(lines=None):
    """Give every waiting line the board's own suggestion. A suggestion a
    person or a session wrote (anything without a free `source`) is left
    alone; the board's own is worked out again, because history grows. Returns
    how many lines carry one afterwards. The caller commits."""
    from models import BankTransaction
    if lines is None:
        lines = BankTransaction.query.filter_by(disposition="review").all()
    FREE = {"history", "receipt", "vendor", "category"}
    done = 0
    for line in lines:
        current = line.suggestion
        if current and current.get("source") not in FREE:
            done += 1
            continue
        got = suggest_line(line)
        line.suggestion_json = json.dumps(got) if got else None
        done += int(got is not None)
    return done


# ── The door: what a /bank session reads and how it answers ────────


def _account_words(line):
    import bank_feed
    return bank_feed._account_words(line)


def review_payload(limit=150):
    """Everything a session needs to settle the waiting lines, as JSON."""
    from forms import EXPENSE_CATEGORY_CHOICES
    from models import BankTransaction, Business, BusinessOwner, Project, VendorRule
    waiting = BankTransaction.query.filter_by(disposition="review")
    lines = (waiting.order_by(BankTransaction.occurred_on.desc(), BankTransaction.id.desc())
             .limit(max(1, min(int(limit or 150), 500))).all())
    decided = (BankTransaction.query.filter(BankTransaction.decided_at.isnot(None),
                                            BankTransaction.rule_id.is_(None))
               .order_by(BankTransaction.decided_at.desc()).limit(60).all())
    return {
        "waiting": waiting.count(),
        "companies": [{"id": b.id, "name": b.name,
                       "dba_of": b.parent.name if b.parent else None,
                       "owners": [o.name for o in BusinessOwner.query.filter_by(business_id=b.id)]}
                      for b in Business.query.order_by(Business.id).all()],
        "categories": [k for k, _ in EXPENSE_CATEGORY_CHOICES if k != "billable_time"],
        "dispositions": ["expense", "personal", "contribution", "draw", "transfer", "income"],
        "projects": [{"id": p.id, "name": p.name, "client": p.client.name if p.client else ""}
                     for p in Project.query.order_by(Project.name).all()],
        "rules": [{"pattern": r.pattern, "vendor": r.vendor, "disposition": r.disposition,
                   "business_id": r.business_id, "category": r.category,
                   "applies_to": r.applies_to}
                  for r in VendorRule.query.order_by(VendorRule.pattern).all()],
        "settled_by_hand": [{"counterparty": l.counterparty, "amount": l.amount,
                             "disposition": l.disposition, "account": _account_words(l)}
                            for l in decided],
        "lines": [{"id": l.id, "date": l.occurred_on.isoformat(), "amount": l.amount,
                   "account": _account_words(l), "business_id": l.business_id,
                   "personal_card": bool(l.connection and l.connection.kind == "personal"),
                   "counterparty": l.counterparty, "bank_text": l.description,
                   "merchant_category": l.merchant_category or l.bank_category or "",
                   "pattern_hint": counterparty_key(l.counterparty),
                   "suggestion": l.suggestion}
                  for l in lines],
    }


def decide_many(decisions, who="bank skill"):
    """Settle lines the way the review page does. Each decision is
    {id, disposition, business_id, category, project_id, vendor, pattern,
    keep, owner_name}; a line already settled by an earlier one's rule is
    reported, not settled twice. Returns (results, settled_alike)."""
    import bank_feed
    from models import db, BankTransaction, Business, Project
    allowed = {"expense", "personal", "contribution", "draw", "transfer", "income"}
    businesses = {b.id for b in Business.query.all()}
    results, alike = [], 0
    for d in decisions or []:
        if not isinstance(d, dict):
            continue
        try:
            line_id = int(d.get("id"))
        except (TypeError, ValueError):
            results.append({"id": d.get("id"), "error": "no such line"})
            continue
        line = db.session.get(BankTransaction, line_id)
        if line is None:
            results.append({"id": line_id, "error": "no such line"})
            continue
        # A line already settled is only settled again when the decision says
        # so (`resettle`), with what it was before in the answer, so the
        # change can be put back: a charge filed as personal that was a
        # business expense (Apple's developer program, 2026-11-06) or booked
        # to the wrong company (LegalZoom forming EntertainHQ).
        before = None
        if line.disposition != "review":
            if not d.get("resettle"):
                results.append({"id": line_id, "skipped": f"already {line.disposition}"})
                continue
            from models import Expense
            exp = db.session.get(Expense, line.expense_id) if line.expense_id else None
            before = {"disposition": line.disposition, "business_id": exp.business_id if exp else line.business_id,
                      "category": exp.category if exp else None, "rule_id": line.rule_id}
        disposition = str(d.get("disposition") or "").strip().lower()
        if disposition not in allowed:
            results.append({"id": line_id, "error": f"disposition must be one of {sorted(allowed)}"})
            continue
        business_id = d.get("business_id") or line.business_id
        if business_id not in businesses:
            results.append({"id": line_id, "error": "no such company"})
            continue
        project = db.session.get(Project, int(d.get("project_id") or 0)) if d.get("project_id") else None
        keep = bool(d.get("keep", True)) and bool(str(d.get("pattern") or "").strip())
        alike += bank_feed.decide(
            line, disposition, business_id=business_id,
            category=str(d.get("category") or "misc")[:50],
            project_id=project.id if project else None,
            client_id=project.client_id if project else None,
            vendor=str(d.get("vendor") or "")[:120], pattern=str(d.get("pattern") or "")[:120],
            keep=keep, owner_name=str(d.get("owner_name") or "")[:120])
        line = db.session.get(BankTransaction, line_id)
        results.append({"id": line_id, "settled": line.disposition, "rule": keep,
                        **({"before": before} if before else {})})
    bank_feed.fold_duplicates()
    return results, alike
