"""Each business's bank, read nightly, and the expenses its lines make.

    python bank_feed.py            # every connection
    python bank_feed.py --suggest  # and ask Claude about the lines nobody knows

Michael, 2026-11-03: "I use an unbelievable amount of services ... I need my
expense tracking automated to like the highest degree ... broken out
specifically by business as well, so that way I'm not accidentally double
counting."

Most vendors have no billing API (Sentry, Resend, Postmark, Claude's own
subscription, Apple's $99, LegalZoom...), but every dollar a business spends
leaves its bank. So the bank is what the books stand on: ONE line per money
movement, and that line is the only thing allowed to make an expense. A
vendor's own report (Railway's invoices, Twilio's usage) is evidence and a
way to split the money across projects, never a second expense.

What a line is:
  - void      the bank cancelled, failed or reversed it; any expense it made
              is removed
  - transfer  money between the company's own accounts (Mercury's internal
              and treasury transfers, a card payoff once a rule says so)
  - contribution / draw
              an owner's own money going in or coming out (Michael moving
              money in from his personal Chase is the first): neither income
              nor an expense, and the year-end report says whose it was
  - expense   a business cost, booked once the line has SETTLED, in the
              books of the business the rule names, else the business whose
              bank it is. Mercury's own fees are expenses without a rule.
              Money back from a vendor with an expense rule is a refund: a
              negative expense.
  - covered   a vendor sync already books this money (Railway, Cloudflare,
              Claude, for Built by Bean); for any other business it is an
              expense, because the sync books only Built by Bean's
  - income    money in (Stripe payouts, client payments); revenue is read
              from Stripe, so this is never an expense and never revenue
  - personal  not the business's money
  - review    nobody knows yet: it waits on the review list, with Claude's
              suggestion beside it, and one press settles it and every line
              like it for good (VendorRule)

A pending charge changes amount when it settles (tips, currency), so lines
are upserted on Mercury's id and the last ten days are read again every
night. Nothing here ever writes to the bank: the token is read only.
"""
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import requests

MERCURY = "https://api.mercury.com/api/v1"
BOOKS_START = date(2026, 4, 1)
OVERLAP_DAYS = 10
PAGE = 500
TIMEOUT = 30

TRANSFER_KINDS = {"internalTransfer", "treasuryTransfer"}
BANK_FEE_KINDS = {"wireFee", "cardInternationalTransactionFee", "billingEngineSubscriptionFee"}
VOID_STATUSES = {"cancelled", "failed", "reversed", "blocked"}
REFUND_KINDS = {"debitCardCredit", "creditCardCredit"}
SUGGEST_MODEL = os.environ.get("BANK_SUGGEST_MODEL", "claude-opus-5-5")


class BankError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


# ── Mercury ──────────────────────────────────────────────


def _auth(token):
    token = (token or "").strip()
    if token and not token.startswith("secret-token:"):
        token = "secret-token:" + token
    return {"Authorization": f"Bearer {token}", "Accept": "application/json",
            "User-Agent": "builtbybean-books/1.0"}


def mercury_get(token, path, params=None):
    try:
        resp = requests.get(MERCURY + path, headers=_auth(token), params=params or {},
                            timeout=TIMEOUT)
    except requests.RequestException as err:
        raise BankError(f"Mercury did not answer: {str(err)[:120]}") from err
    if resp.status_code == 401:
        raise BankError("Mercury refused the token (401). Make a new read only token.", 401)
    if resp.status_code >= 400:
        raise BankError(f"Mercury answered {resp.status_code}: {resp.text[:160]}", resp.status_code)
    try:
        return resp.json()
    except ValueError as err:
        raise BankError("Mercury answered with something that is not JSON") from err


def mercury_accounts(token, balances=None):
    """{account id: name}. Also the check that a token works. Pass a dict as
    `balances` to have it filled with {account id: current balance}."""
    data = mercury_get(token, "/accounts")
    rows = data.get("accounts", data) if isinstance(data, dict) else data
    out = {}
    for a in rows or []:
        if isinstance(a, dict) and a.get("id"):
            out[a["id"]] = a.get("nickname") or a.get("name") or a.get("kind") or "Account"
            if balances is not None:
                value = a.get("currentBalance", a.get("availableBalance"))
                try:
                    balances[a["id"]] = round(float(value), 2)
                except (TypeError, ValueError):
                    pass
    return out


def mercury_transactions(token, start):
    """Every transaction created on or after `start`, oldest first, across
    every account the token opens (the IO card included). Paged by the last
    id seen, which the docs name as the forward cursor."""
    params = {"start": start.isoformat(), "limit": PAGE, "order": "asc"}
    while True:
        data = mercury_get(token, "/transactions", params)
        rows = data.get("transactions") or []
        for row in rows:
            yield row
        if len(rows) < PAGE:
            return
        params = {"start": start.isoformat(), "limit": PAGE, "order": "asc",
                  "start_after": rows[-1]["id"]}


# ── What a line is ───────────────────────────────────────


_NONWORD = re.compile(r"[^A-Z0-9]+")


def norm(text):
    return " ".join(_NONWORD.sub(" ", (text or "").upper()).split())


def _when(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
            timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def _card_payment(line):
    import statements
    return statements.is_card_payment(line.counterparty)


def is_stripe_payout(line):
    hay = f"{norm(line.counterparty)} {norm(line.description)}"
    return " STRIPE" in f" {hay}"


def _connection(line):
    """The line's card or account, also for a line not yet flushed, whose
    relationship is still empty though its connection_id is set."""
    if line.connection is not None:
        return line.connection
    if line.connection_id:
        from models import db, BankConnection
        return db.session.get(BankConnection, line.connection_id)
    return None


def is_personal(line):
    conn = _connection(line)
    return bool(conn is not None and conn.kind == "personal")


def rule_for(line, rules=None):
    """The longest rule whose pattern appears in the line's counterparty or
    bank description, so GOOGLE WORKSPACE beats GOOGLE. A rule learned as
    personal on an owner's own card applies only to owners' own cards."""
    from models import VendorRule
    rules = rules if rules is not None else VendorRule.query.all()
    hay = f" {norm(line.counterparty)} | {norm(line.description)} "
    personal = is_personal(line)
    best = None
    for r in rules:
        if (r.applies_to or "all") == "personal" and not personal:
            continue
        pat = norm(r.pattern)
        if not pat:
            continue
        # Whole words, or a long enough run to be unambiguous inside a word
        # (Mercury writes "CLOUDFLARECOM" as often as "CLOUDFLARE COM").
        if f" {pat} " in hay or (len(pat) >= 6 and pat in hay):
            if best is None or len(norm(best.pattern)) < len(pat):
                best = r
    return best


def _home_family():
    from models import Business, home_business_id
    home = home_business_id()
    if home is None:
        return set()
    return {home} | {b.id for b in Business.query.filter_by(parent_id=home).all()}


def provider_books(provider, business_id):
    """Whether this vendor's own sync already writes the expense for money
    this business spent: only for a provider that is Built by Bean's, and
    only for Built by Bean or one of its DBAs."""
    return bool(provider and provider.is_active and provider.account_client_id is None
                and provider.account_business_id is None
                and business_id in _home_family())


def classify(line, rules=None):
    """Set the line's disposition and rule, and book or unbook its expense."""
    rule = None
    if line.status in VOID_STATUSES:
        line.disposition = "void"
    elif line.decided_at and line.rule_id is None and line.disposition != "review":
        pass  # settled by hand for this line alone; only the amount follows the bank
    elif line.kind in TRANSFER_KINDS:
        line.disposition = "transfer"
    elif line.kind == "statement" and _card_payment(line):
        line.disposition = "transfer"  # paying a card off is money moving, not spending
    elif line.amount > 0 and is_stripe_payout(line):
        # A payout is the company's own money leaving its Stripe balance for
        # its bank. The sale it came from was income on the day the customer
        # paid (stripe_books.py, or the board's invoices); counting the
        # deposit too would book the same money twice.
        line.disposition = "transfer"
    elif line.kind in BANK_FEE_KINDS:
        line.disposition = "expense"
    else:
        rule = rule_for(line, rules)
        # An owner's money only goes in as money in, and out as money out: a
        # Chase fee on a statement must not read as Michael putting in a
        # negative amount because the CHASE rule matched it.
        if rule is not None and ((rule.disposition == "contribution" and line.amount < 0)
                                 or (rule.disposition == "draw" and line.amount > 0)):
            rule = None
        if rule is not None:
            line.disposition = rule.disposition
            if rule.disposition in ("contribution", "draw"):
                line.owner_name = rule.owner_name or ""
            if rule.disposition == "covered":
                owner = rule.business_id or line.business_id
                if not provider_books(rule.provider, owner):
                    line.disposition = "expense"
        elif line.amount > 0 and line.kind not in REFUND_KINDS and not is_personal(line):
            line.disposition = "income"
        else:
            line.disposition = "review"
    if rule is not None:
        line.rule_id = rule.id
    elif not line.decided_at:
        line.rule_id = None
    book(line, rule)
    return line.disposition


def book(line, rule=None, manual=None):
    """Make, rewrite or remove the one expense this line stands for."""
    from models import db, Expense
    wants = line.disposition == "expense" and line.status == "sent"
    if not wants:
        if line.expense_id:
            gone = db.session.get(Expense, line.expense_id)
            line.expense_id = None
            if gone is not None:
                db.session.delete(gone)
        return None
    if rule is not None:
        spec = {"business_id": rule.business_id, "category": rule.category,
                "client_id": rule.client_id, "project_id": rule.project_id,
                "vendor": rule.vendor}
    elif manual is not None:
        spec = manual
    elif line.kind in BANK_FEE_KINDS:
        spec = {"category": "bank_fees", "vendor": "Mercury"}
    else:
        spec = None  # settled by hand earlier: keep what was settled, follow the amount
    expense = db.session.get(Expense, line.expense_id) if line.expense_id else None
    paid_by = (_connection(line).owner_name or None) if is_personal(line) else None
    if expense is None:
        expense = adopt(line, (spec or {}).get("business_id") or line.business_id)
        if expense is not None:
            line.expense_id = expense.id
            if paid_by and not expense.paid_by:
                expense.paid_by = paid_by
            return expense
    fresh = expense is None
    if fresh:
        expense = Expense(amount=0, date=line.occurred_on, category="misc")
        db.session.add(expense)
    expense.amount = round(-line.amount, 2)
    expense.date = line.occurred_on
    if spec is not None or fresh:
        spec = spec or {}
        expense.business_id = spec.get("business_id") or line.business_id
        expense.category = spec.get("category") or "misc"
        expense.client_id = spec.get("client_id") or None
        expense.project_id = spec.get("project_id") or None
        vendor = spec.get("vendor") or line.counterparty or "Bank charge"
        expense.description = vendor + (f" - {line.note}" if line.note else "")
    if paid_by:
        expense.paid_by = paid_by
    db.session.flush()
    line.expense_id = expense.id
    return expense


ADOPT_BEFORE, ADOPT_AFTER = 3, 7


def adopt(line, business_id):
    """An expense somebody already booked for this very charge, if there is
    one: typed on the expense form, or logged by a session through the
    guidance door (a domain bought from the Piped repo was, on 2026-11-02).
    Same business, the same amount to the cent, dated up to seven days before
    the bank's date or three after (a receipt is dated when the order is
    placed and the card posts later; an annual renewal can charge a day
    before its email), and not already standing for another bank line nor written
    by a vendor sync. The closest date wins. Adopting it is what keeps the
    bank from booking the same money a second time."""
    from models import db, Expense, BankTransaction, ServiceCostEntry, Business
    if line.amount >= 0:
        return None
    # The whole company: a DBA's charge may have been typed under the LLC it
    # trades as, and the other way round. One company, one set of books.
    biz = db.session.get(Business, business_id) if business_id else None
    root = (biz.parent_id or biz.id) if biz else business_id
    family = {root} | {b.id for b in Business.query.filter_by(parent_id=root).all()}
    target = round(-line.amount, 2)
    lo = line.occurred_on - timedelta(days=ADOPT_AFTER)
    hi = line.occurred_on + timedelta(days=ADOPT_BEFORE)
    taken = db.session.query(BankTransaction.expense_id).filter(
        BankTransaction.expense_id.isnot(None), BankTransaction.id != line.id)
    synced = db.session.query(ServiceCostEntry.expense_id).filter(
        ServiceCostEntry.expense_id.isnot(None))
    rows = (Expense.query.filter(Expense.business_id.in_(family), Expense.date >= lo,
                                 Expense.date <= hi, Expense.time_entry_id.is_(None),
                                 ~Expense.id.in_(taken), ~Expense.id.in_(synced))
            .all())
    rows = [e for e in rows if abs(round(e.amount, 2) - target) < 0.005]
    if not rows:
        return None
    return min(rows, key=lambda e: (abs((e.date - line.occurred_on).days), e.id))


def upsert(conn, row, accounts):
    """One Mercury transaction onto its line. Returns (line, created)."""
    from models import db, BankTransaction
    line = BankTransaction.query.filter_by(connection_id=conn.id, external_id=row["id"]).first()
    created = line is None
    if created:
        line = BankTransaction(connection_id=conn.id, business_id=conn.business_id,
                               external_id=row["id"], amount=0, occurred_on=date.today())
        db.session.add(line)
    posted = _when(row.get("postedAt"))
    made = _when(row.get("createdAt"))
    merchant = row.get("merchant") or {}
    line.account_id = row.get("accountId") or ""
    line.account_name = accounts.get(line.account_id, "")[:120]
    line.status = (row.get("status") or "")[:12]
    line.kind = (row.get("kind") or "")[:40]
    line.amount = float(row.get("amount") or 0)
    line.occurred_on = (posted or made or datetime.now()).date()
    line.posted_at = posted
    line.counterparty = (row.get("counterpartyNickname") or row.get("counterpartyName") or "")[:200]
    line.description = (row.get("bankDescription") or "")[:300]
    line.note = row.get("note") or row.get("externalMemo") or ""
    line.merchant_category = (merchant.get("category") or "")[:80]
    line.bank_category = (row.get("mercuryCategory") or "")[:60]
    line.card_id = (row.get("cardId") or "")[:60]
    line.link = (row.get("dashboardLink") or "")[:300]
    line.raw_json = json.dumps(row)[:20000]
    return line, created


def sync_connection(conn, fetch=None, accounts=None):
    """Read one business's bank into lines and expenses. Returns counts."""
    from models import db, VendorRule
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = conn.synced_from or BOOKS_START
    if conn.last_synced_at and conn.last_ok:
        start = max(start, (conn.last_synced_at - timedelta(days=OVERLAP_DAYS)).date())
    counts = {"read": 0, "new": 0, "review": 0, "expense": 0}
    try:
        if accounts is None:
            balances = {}
            accounts = mercury_accounts(conn.token, balances)
            if balances:
                conn.balances_json = json.dumps(balances)
        if accounts:
            conn.accounts_json = json.dumps(accounts)
        else:
            accounts = conn.accounts
        rows = (fetch or mercury_transactions)(conn.token, start)
        rules = VendorRule.query.all()
        for row in rows:
            line, created = upsert(conn, row, accounts)
            classify(line, rules)
            counts["read"] += 1
            counts["new"] += int(created)
        db.session.flush()
    except BankError as err:
        db.session.rollback()
        conn.last_ok = False
        conn.last_note = str(err)[:300]
        conn.last_synced_at = now
        db.session.commit()
        return {"error": str(err)}
    from models import BankTransaction
    counts["review"] = BankTransaction.query.filter_by(
        connection_id=conn.id, disposition="review").count()
    counts["expense"] = BankTransaction.query.filter_by(
        connection_id=conn.id, disposition="expense").count()
    conn.last_ok = True
    conn.last_synced_at = now
    conn.last_note = (f"{counts['read']:,} lines read, {counts['new']:,} new, "
                      f"{counts['review']:,} to review")
    db.session.commit()
    return counts


def reclassify_review(rules=None):
    """Run every line still waiting through the rules again, after a rule is
    written. Returns how many it settled."""
    from models import db, BankTransaction, VendorRule
    rules = rules if rules is not None else VendorRule.query.all()
    settled = 0
    for line in BankTransaction.query.filter_by(disposition="review").all():
        if classify(line, rules) != "review":
            settled += 1
    db.session.commit()
    return settled


def remember(pattern, disposition, vendor="", business_id=None, category="misc",
             client_id=None, project_id=None, provider_id=None, note="", owner_name="",
             applies_to="all"):
    """Write (or rewrite) the rule for a pattern. Returns the rule."""
    from models import db, VendorRule
    pattern = norm(pattern)[:120]
    if not pattern:
        raise ValueError("a rule needs a pattern")
    rule = VendorRule.query.filter_by(pattern=pattern).first()
    if rule is None:
        rule = VendorRule(pattern=pattern)
        db.session.add(rule)
    rule.vendor = (vendor or "")[:120]
    rule.disposition = disposition
    rule.business_id = business_id or None
    rule.category = category or "misc"
    rule.client_id = client_id or None
    rule.project_id = project_id or None
    rule.provider_id = provider_id or None
    rule.note = (note or "")[:300]
    rule.owner_name = (owner_name or "")[:120]
    rule.applies_to = applies_to if applies_to in ("all", "personal") else "all"
    db.session.flush()
    return rule


def decide(line, disposition, *, business_id=None, category="misc", client_id=None,
           project_id=None, vendor="", pattern="", keep=True, owner_name=""):
    """Settle one line from the review list. With `keep`, the answer becomes
    a rule and every waiting line like it is settled too."""
    from models import db, VendorRule
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    line.decided_at = now
    if keep and pattern:
        rule = remember(pattern, disposition, vendor=vendor, business_id=business_id,
                        category=category, client_id=client_id, project_id=project_id,
                        owner_name=owner_name,
                        applies_to="personal" if disposition == "personal" and is_personal(line)
                        else "all")
        classify(line, VendorRule.query.all())
        line.decided_at = now
        db.session.commit()
        return reclassify_review()
    line.rule_id = None
    line.disposition = disposition
    line.owner_name = (owner_name or "")[:120] if disposition in ("contribution", "draw") else ""
    book(line, manual={"business_id": business_id, "category": category,
                       "client_id": client_id, "project_id": project_id,
                       "vendor": vendor or line.counterparty})
    db.session.commit()
    return 0


def sync_all(app):
    from models import BankConnection
    with app.app_context():
        for conn in (BankConnection.query.filter_by(provider="mercury")
                     .order_by(BankConnection.id).all()):
            result = sync_connection(conn)
            name = conn.business.name if conn.business else conn.business_id
            print(f"  bank {name:30} {result.get('error') or conn.last_note}", flush=True)


# ── Claude's suggestion for the lines nobody knows ───────

SUGGEST_SYSTEM = """You sort bank lines for Michael Bean's companies. Built \
by Bean LLC is his software studio (it builds and hosts web apps for small \
businesses and for his own products); EntertainHQ LLC is a separate company \
he runs, an entertainment booking platform. A line is money out of one \
company's bank unless its amount is positive. For each line, say what it \
most likely is: a business expense (and whose: usually the company whose \
bank paid it, but a charge for EntertainHQ's own services paid by Built by \
Bean is EntertainHQ's), a transfer between the company's own accounts, \
money an owner put in (contribution) or took out (draw), money in from \
customers, or a personal purchase that does not belong in either company's \
books. Michael's personal accounts are at Chase. A line whose account \
says PERSONAL CARD was paid on an owner's own card, which carries his whole \
life: there it is personal unless it is plainly something a software studio \
or a booking platform buys (software, hosting, domains, developer tools, \
business subscriptions, a vendor already known below). Restaurants, fuel, \
groceries, shops, travel and entertainment on a personal card are personal \
unless the known vendors say otherwise, and money in on a personal card is \
a refund or a card payment, never income. Name the \
vendor in plain words, and give the PATTERN: the shortest stable piece of \
the counterparty or bank text that will appear on every future charge from \
this vendor and on no other (e.g. "GITHUB", "GOOGLE WORKSPACE", not a \
transaction number). Use only the ids you are given. Say how sure you are."""


def _suggest_schema(categories):
    s = {"type": "string"}
    item = {"type": "object", "additionalProperties": False,
            "required": ["id", "disposition", "vendor", "pattern", "business_id", "category",
                         "project_id", "confidence", "why"],
            "properties": {
                "id": {"type": "integer"},
                "disposition": {"type": "string",
                                "enum": ["expense", "contribution", "draw", "transfer",
                                         "income", "personal"]},
                "vendor": s, "pattern": s,
                "business_id": {"type": "integer"},
                "category": {"type": "string", "enum": categories},
                "project_id": {"type": "integer"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "why": s}}
    return {"type": "object", "additionalProperties": False, "required": ["lines"],
            "properties": {"lines": {"type": "array", "items": item}}}


def _account_words(line):
    conn = _connection(line)
    company = line.business.name if line.business else ""
    if conn is not None and conn.kind == "personal":
        return f"PERSONAL CARD of {conn.owner_name or 'an owner'} ({conn.label}), usually for {company}"
    return f"{company} account" + (f" ({conn.label})" if conn is not None and conn.label else "")


def suggest_all(client=None, batch=60, rounds=20):
    """Every waiting line, a batch at a time, until a batch answers none."""
    total = 0
    for _ in range(rounds):
        n = suggest(client=client, limit=batch)
        total += n
        if not n:
            break
    return total


_suggesting = set()
_suggest_lock = __import__("threading").Lock()


def suggesting():
    return bool(_suggesting)


def suggest_in_background(app):
    """Ask on a thread of its own: 500 lines from a first statement is many
    minutes of Claude, far past gunicorn's sixty seconds. A second press
    while it runs starts nothing."""
    import threading
    with _suggest_lock:
        if _suggesting:
            return False
        _suggesting.add(1)

    def run():
        try:
            with app.app_context():
                suggest_all()
        except Exception as err:  # noqa: BLE001 - a suggestion is a nicety
            app.logger.warning("bank: background suggestions failed: %s", err)
        finally:
            with _suggest_lock:
                _suggesting.clear()

    threading.Thread(target=run, name="bank-suggest", daemon=True).start()
    return True


def suggest(client=None, limit=60):
    """Ask Claude about waiting lines that have no suggestion yet. Returns how
    many it answered. Without ANTHROPIC_API_KEY it answers none and the list
    simply carries no suggestions."""
    from forms import EXPENSE_CATEGORY_CHOICES
    from models import db, BankTransaction, Business, Project, VendorRule
    lines = (BankTransaction.query.filter_by(disposition="review")
             .filter(BankTransaction.suggestion_json.is_(None))
             .order_by(BankTransaction.occurred_on.desc()).limit(limit).all())
    if not lines:
        return 0
    if client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return 0
        import anthropic
        client = anthropic.Anthropic(max_retries=4, timeout=600)
    categories = [k for k, _ in EXPENSE_CATEGORY_CHOICES if k != "billable_time"]
    businesses = Business.query.order_by(Business.id).all()
    projects = Project.query.order_by(Project.name).all()
    prompt = (
        "THE COMPANIES (id | name):\n"
        + "\n".join(f"{b.id} | {b.name}" + (f" (a DBA of {b.parent.name})" if b.parent else "")
                    for b in businesses)
        + "\n\nCATEGORIES: " + ", ".join(categories)
        + "\n\nPROJECTS, if one line plainly belongs to one (id | name | client), else 0:\n"
        + "\n".join(f"{p.id} | {p.name} | {p.client.name if p.client else ''}" for p in projects)
        + "\n\nWHAT IS ALREADY KNOWN (pattern -> vendor, what it is):\n"
        + "\n".join(f"{r.pattern} -> {r.vendor}, {r.disposition}" for r in VendorRule.query.all())
        + "\n\nTHE LINES (id | date | amount | account | counterparty | bank text | merchant type):\n"
        + "\n".join(f"{l.id} | {l.occurred_on} | {l.amount:.2f} | {_account_words(l)} | "
                    f"{l.counterparty} | "
                    f"{l.description} | {l.merchant_category or l.bank_category}" for l in lines))
    with client.beta.messages.stream(
        model=SUGGEST_MODEL, max_tokens=32000,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        system=SUGGEST_SYSTEM,
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": _suggest_schema(categories)}},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        message = stream.get_final_message()
    if message.stop_reason in ("refusal", "max_tokens"):
        return 0
    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        answer = json.loads(text)
    except ValueError:
        return 0
    by_id = {l.id: l for l in lines}
    known = {b.id for b in businesses}
    project_ids = {p.id for p in projects}
    done = 0
    for s in answer.get("lines", []):
        line = by_id.get(s.get("id"))
        if line is None:
            continue
        if s.get("business_id") not in known:
            s["business_id"] = line.business_id
        if s.get("project_id") not in project_ids:
            s["project_id"] = 0
        line.suggestion_json = json.dumps(s)
        done += 1
    db.session.commit()
    return done


def main():
    from app import create_app
    app = create_app()
    sync_all(app)
    if "--suggest" in sys.argv or os.environ.get("ANTHROPIC_API_KEY"):
        with app.app_context():
            try:
                print(f"  bank: {suggest()} lines given a suggestion", flush=True)
            except Exception as err:  # noqa: BLE001 - a suggestion is a nicety
                print(f"  bank suggestions failed: {str(err)[:200]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
