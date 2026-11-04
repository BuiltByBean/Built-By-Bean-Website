"""What the State of Texas says about each business, read nightly, no key.

Audit items 8 and 12 (docs/automation_gaps.md): the board knew a company only
by what was typed onto it, while the Comptroller publishes most of it.

  read_franchise   the franchise tax search answers JSON by taxpayer number
                   (comptroller.texas.gov/data-search/franchise-tax/<n>): the
                   right to transact (ACTIVE or FORFEITED), the SOS file number
                   and date, the registered agent and office, the EIN, and
                   `reportYear`, the last franchise report on file. Empty
                   fields on the board are filled; the state's own fields are
                   kept and a change is flagged (ComptrollerFlag).
  read_permits     the open dataset of active sales tax permits (jrea-zgmq,
                   the one import_leads.py reads) has a row per outlet: its
                   five digit number, address, NAICS, permit date, first sale
                   and whether it is inside city limits. Empty fields fill,
                   locations are matched by number, and an outlet that drops
                   off is flagged. A number that finds NO permit is said in
                   words (Business.permit_status = "none"): Built by Bean's
                   found none on 2026-11-04 while it was filing returns.
  read_rates       the quarterly city rate workbook (city-rates.xlsx), whose
                   only statement of its quarter is its sheet name: a file
                   still naming last quarter is left for tomorrow.
  draft_filings    a Comptroller charge on the bank with no return recorded
                   near it drafts the return for the period it paid, leaving
                   only the reference number; search_mail fills that too when
                   a confirmation email turns up.

Everything here only ever fills a blank, flags a difference, or writes a row
of its own; a typed value is never overwritten except the state's own fields
(standing, agent, office, report year), which are the state's to say. Nothing
here files anything with the state.
"""
import io
import json
import re
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from xml.etree import ElementTree

import requests

FRANCHISE_URL = "https://comptroller.texas.gov/data-search/franchise-tax/{}"
PERMITS_URL = "https://data.texas.gov/resource/jrea-zgmq.json"
RATES_URL = "https://comptroller.texas.gov/taxes/sales/docs/city-rates.xlsx"
HEADERS = {"User-Agent": "BuiltByBean-board/1.0 (+https://builtbybeans.com)"}
TIMEOUT = 30
# The permit file's way of saying "unknown": the day the sales tax began.
UNKNOWN_START = date(1961, 9, 1)
STATE_RATE = 6.25
CHARGE_DAYS = 120
# A drafted return taken off the board writes DeadlineDone("nodraft:<line id>"),
# so the same charge is not drafted again the next night.
NO_DRAFT = "nodraft:"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _now():
    return datetime.now(timezone.utc)


def _get(url, params=None):
    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _us_date(value):
    try:
        return datetime.strptime(_clean(value), "%m/%d/%Y").date()
    except ValueError:
        return None


def _iso_date(value):
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _address(street, city, state, zipcode):
    tail = " ".join(p for p in (_clean(state), _clean(zipcode)) if p)
    return ", ".join(p for p in (_clean(street), _clean(city), tail) if p)


def _title(text):
    """KANSAS CITY to Kansas City, for a town read off a shouted record."""
    return " ".join(w.capitalize() for w in _clean(text).split(" "))


def _flag(business, kind, title, old="", new="", location=None):
    """A change for Michael to see once. The same open flag is never written
    twice, because the nightly read sees the same difference every night."""
    from models import db, ComptrollerFlag
    old, new = str(old or "")[:300], str(new or "")[:300]
    same = ComptrollerFlag.query.filter_by(business_id=business.id, kind=kind, new_value=new,
                                           location_id=location.id if location else None,
                                           seen_at=None).first()
    if same is not None:
        return same
    row = ComptrollerFlag(business_id=business.id, location_id=location.id if location else None,
                          kind=kind, title=title[:200], old_value=old, new_value=new)
    db.session.add(row)
    return row


# ── The franchise tax search ─────────────────────────────────

# The state's own fields: (record key or function, column, flag kind, words).
_STATE_FIELDS = (
    ("rightToTransactTX", "franchise_status", "standing", "Right to transact in Texas"),
    ("sosRegistrationStatus", "sos_status", "sos", "Secretary of State status"),
    ("registeredAgentName", "registered_agent", "agent", "Registered agent"),
    (lambda d: _address(d.get("registeredOfficeAddressStreet"), d.get("registeredOfficeAddressCity"),
                        d.get("registeredOfficeAddressState"), d.get("registeredOfficeAddressZip")),
     "registered_office", "office", "Registered office"),
    (lambda d: _address(d.get("mailingAddressStreet"), d.get("mailingAddressCity"),
                        d.get("mailingAddressState"), d.get("mailingAddressZip")),
     "mailing_address", "mailing", "Franchise tax mailing address"),
    ("feiNumber", "ein", "ein", "EIN"),
)


def fetch_franchise(number, get=None):
    """The record for a taxpayer number, or None when the state has none."""
    get = get or (lambda url: _get(url).json())
    payload = get(FRANCHISE_URL.format(number))
    if not isinstance(payload, dict) or not payload.get("success") or not payload.get("data"):
        return None
    return payload["data"]


def read_franchise(business, get=None):
    """Bring one business in line with its franchise tax record. Returns a
    list of what changed, in words, for the night's summary."""
    number = re.sub(r"\D", "", business.texas_taxpayer_number or "")
    business.comptroller_checked_at = _now()
    if len(number) != 11:
        business.comptroller_note = "No taxpayer number on file."
        return []
    data = fetch_franchise(number, get)
    if data is None:
        business.comptroller_note = f"The franchise tax search has no record for {number}."
        return [f"{business.label}: no franchise record"]
    said = []
    for source, column, kind, words in _STATE_FIELDS:
        value = _clean(source(data) if callable(source) else data.get(source))
        if column == "ein":
            value = re.sub(r"\D", "", value)
        if not value:
            continue
        before = _clean(getattr(business, column))
        if before == value:
            continue
        if before:
            _flag(business, kind, f"{business.label}: {words} changed", before, value)
            said.append(f"{business.label}: {words.lower()} changed")
        setattr(business, column, value[:300])

    # The typed fields: filled when empty, and a difference is flagged but
    # never overwritten, because a typed number may be the right one.
    sos = re.sub(r"\D", "", data.get("sosFileNumber") or "")
    if sos:
        mine = re.sub(r"\D", "", business.sos_file_number or "")
        if not mine:
            business.sos_file_number = sos[:20]
            said.append(f"{business.label}: SOS file number filled")
        elif mine.lstrip("0") != sos.lstrip("0"):
            _flag(business, "sos_number", f"{business.label}: the state has another SOS file number",
                  mine, sos)
    formed = _us_date(data.get("effectiveSosRegistrationDate"))
    if formed and not business.is_division:
        if business.formed_on is None:
            business.formed_on = formed
            said.append(f"{business.label}: formed on filled")
        elif business.formed_on != formed:
            _flag(business, "formed", f"{business.label}: the state has another formation date",
                  business.formed_on.isoformat(), formed.isoformat())

    year = data.get("reportYear")
    try:
        year = int(str(year).strip()) if str(year or "").strip() else None
    except ValueError:
        year = None
    if year and (business.franchise_report_year or 0) < year:
        business.franchise_report_year = year
        said.append(f"{business.label}: {year} franchise report on file")
    business.comptroller_note = ""
    return said


# ── The permit list (jrea-zgmq) ──────────────────────────────

def fetch_permits(number, get=None):
    get = get or (lambda url, params: _get(url, params).json())
    rows = get(PERMITS_URL, {"$where": f"taxpayer_number='{number}'", "$limit": 500})
    return rows if isinstance(rows, list) else []


def _has_sales_tax(business):
    """Whether a missing permit would mean anything: the business has said it
    collects sales tax somewhere on the board."""
    return bool(business.sales_tax_webfile or business.sales_tax_registered_on
                or business.sales_tax_first_sale or business.locations or business.filings
                or business.sales_source in ("board", "hub"))


def _city_of(loc):
    if loc.city:
        return loc.city
    return _clean((loc.label or "").split(",")[0])


def read_permits(business, get=None):
    from models import db, BusinessLocation
    number = re.sub(r"\D", "", business.texas_taxpayer_number or "")
    if len(number) != 11 or business.is_division:
        return []
    rows = fetch_permits(number, get)
    business.permit_checked_at = _now()
    said = []
    if not rows:
        if _has_sales_tax(business):
            if business.permit_status != "none":
                _flag(business, "permit", f"{business.label}: no active sales tax permit found",
                      business.permit_status or "", f"none under {number}")
                said.append(f"{business.label}: no permit under {number}")
            business.permit_status = "none"
        else:
            business.permit_status = ""
        return said
    if business.permit_status == "none":
        _flag(business, "permit", f"{business.label}: the permit is on the state's list again",
              "none", f"found under {number}")
    business.permit_status = "found"

    # Fill the business's own blanks from its outlets.
    naics = [r.get("outlet_naics_code") for r in rows if r.get("outlet_naics_code")]
    if naics and not business.naics_code:
        business.naics_code = max(set(naics), key=naics.count)[:10]
        said.append(f"{business.label}: NAICS filled")
    issued = [d for d in (_iso_date(r.get("outlet_permit_issue_date")) for r in rows) if d]
    if issued and not business.sales_tax_registered_on:
        business.sales_tax_registered_on = min(issued)
        said.append(f"{business.label}: permit date filled")
    firsts = [d for d in (_iso_date(r.get("outlet_first_sales_date")) for r in rows)
              if d and d != UNKNOWN_START]
    if firsts and not business.sales_tax_first_sale:
        business.sales_tax_first_sale = min(firsts)
        said.append(f"{business.label}: first sale filled")

    listed = set()
    for row in rows:
        num = re.sub(r"\D", "", str(row.get("outlet_number") or "")).zfill(5)[-5:]
        city = _title(row.get("outlet_city"))
        loc = next((l for l in business.locations if l.webfile_number == num), None)
        if loc is None:
            # A location typed before its number was known, in the same town.
            loc = next((l for l in business.locations if not l.webfile_number
                        and city and city.lower() in (f"{l.label} {l.address} {l.city}").lower()), None)
            if loc is not None:
                loc.webfile_number = num
                said.append(f"{business.label}: {loc.label} is outlet {num}")
        first = _iso_date(row.get("outlet_first_sales_date"))
        first = first if first and first != UNKNOWN_START else _iso_date(row.get("outlet_permit_issue_date"))
        if loc is None:
            loc = BusinessLocation(business_id=business.id, webfile_number=num, label=city or num,
                                   opened_on=first, local_rate=2.0)
            db.session.add(loc)
            business.locations.append(loc)
            db.session.flush()
            _flag(business, "outlet", f"{business.label}: outlet {num} ({city}) added from the permit list",
                  "", num, location=loc)
            said.append(f"{business.label}: outlet {num} added")
        address = _address(row.get("outlet_address"), city, row.get("outlet_state"), row.get("outlet_zip_code"))
        if not loc.address and address:
            loc.address = address[:300]
        if not loc.city and city:
            loc.city = city[:80]
        if loc.opened_on is None and first:
            loc.opened_on = first
        flag = str(row.get("outlet_inside_outside_city_limits_indicator") or "").upper()
        loc.inside_city_limits = True if flag == "Y" else False if flag == "N" else None
        loc.permit_listed = True
        loc.permit_seen_at = _now()
        listed.add(loc.id)

    for loc in business.locations:
        if loc.id in listed or (loc.closed_on and loc.closure_filed):
            continue
        if loc.permit_listed is not False:
            words = ("dropped off the permit list" if loc.permit_listed
                     else "is not on the permit list")
            _flag(business, "outlet", f"{business.label}: {loc.label} {words}",
                  loc.webfile_number or "", "not listed", location=loc)
            said.append(f"{business.label}: {loc.label} {words}")
        loc.permit_listed = False
    return said


# ── The quarterly local rate file ────────────────────────────

def quarter_tag(day):
    """The sheet name the rate file uses for the quarter `day` is in: Oct26."""
    first = 3 * ((day.month - 1) // 3)
    return f"{_MONTHS[first]}{day.year % 100:02d}"


def _col(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(data):
    """(sheet name, rows) of a workbook's first sheet, with no library: an
    xlsx is a zip of XML, and this file is one plain sheet."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        book = ElementTree.fromstring(z.read("xl/workbook.xml"))
        sheet = book.find("m:sheets/m:sheet", ns)
        name = sheet.get("name") if sheet is not None else ""
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                strings.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        sheet_files = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet"))
        root = ElementTree.fromstring(z.read(sheet_files[0]))
    rows = []
    for r in root.iter(f"{{{ns['m']}}}row"):
        cells = {}
        for c in r.findall("m:c", ns):
            kind, v = c.get("t"), c.find("m:v", ns)
            if kind == "s" and v is not None:
                value = strings[int(v.text)]
            elif kind == "inlineStr":
                value = "".join(t.text or "" for t in c.iter(f"{{{ns['m']}}}t"))
            elif v is not None:
                try:
                    value = float(v.text)
                except (TypeError, ValueError):
                    value = v.text
            else:
                value = None
            cells[_col(c.get("r"))] = value
        if cells:
            rows.append([cells.get(i) for i in range(max(cells) + 1)])
    return name, rows


def parse_rates(rows):
    """Rows of the city file as dicts: city, county, county code, local rate."""
    if not rows:
        return []
    head = [_clean(h) for h in rows[0]]
    idx = {h: i for i, h in enumerate(head)}
    need = ("CityName", "CityNumber", "CountyName", "TotalTax")
    if any(h not in idx for h in need):
        raise ValueError("the rate file's columns are not the ones expected: " + ", ".join(head[:6]))
    out = []
    for row in rows[1:]:
        def at(h):
            i = idx[h]
            return row[i] if i < len(row) else None
        city, total = _clean(at("CityName")), at("TotalTax")
        if not city or not isinstance(total, (int, float)):
            continue
        number = re.sub(r"\D", "", str(at("CityNumber") or "").split(".")[0])
        out.append({"city": city, "county": _clean(at("CountyName")),
                    # 2139013: a city's number carries its county's code (139).
                    "county_code": number[1:4] if len(number) == 7 else "",
                    "local": round(float(total) * 100 - STATE_RATE, 4)})
    return out


def rate_for(rates, city, county=""):
    """(local rate, county name, why not) for one town. A town with several
    rates (special districts inside it) is not guessed."""
    if not city:
        return None, None, "no town on the location"
    hits = [r for r in rates if r["city"].lower() == city.lower()]
    if county:
        hits = [r for r in hits if r["county"].lower() == county.lower()] or hits
    if not hits:
        return None, None, f"{city} is not in the city rate file"
    values = {r["local"] for r in hits}
    if len(values) > 1:
        return None, None, f"{city} has {len(values)} rates in the file; check the rate locator"
    counties = {r["county"] for r in hits}
    return values.pop(), (counties.pop() if len(counties) == 1 else None), None


def read_rates(locations, today=None, get=None):
    """Set each open location's local rate from this quarter's file. Returns
    what it did, in words. Does nothing when every location already has this
    quarter's rate, and writes nothing when the file still names last quarter.
    """
    today = today or date.today()
    tag = quarter_tag(today)
    source = f"Comptroller {tag}"
    # A rate changed by hand on the location form says "typed" and is left
    # alone; the 2.0 every location was created with says nothing.
    todo = [l for l in locations if not l.closed_on and l.rate_source not in (source, "typed")]
    if not todo:
        return [f"rates already {tag}"]
    get = get or (lambda url: _get(url).content)
    name, rows = read_xlsx(get(RATES_URL))
    if _clean(name) != tag:
        return [f"rate file still says {name or 'nothing'}, wanted {tag}; tomorrow"]
    rates = parse_rates(rows)
    said = []
    for loc in todo:
        if loc.inside_city_limits is False:
            loc.rate_note = "Outside city limits: the city file does not cover it"
            continue
        rate, county, why = rate_for(rates, _city_of(loc), loc.county or "")
        if rate is None:
            loc.rate_note = (why or "")[:200]
            continue
        if county and not loc.county:
            loc.county = county[:60]
        if abs((loc.local_rate or 0) - rate) > 0.00001:
            if loc.rate_source:
                _flag(loc.business, "rate", f"{loc.business.label}: {loc.label} local rate changed",
                      f"{loc.local_rate:g}%", f"{rate:g}%", location=loc)
            said.append(f"{loc.business.label}: {loc.label} {loc.local_rate:g}% to {rate:g}%")
            loc.local_rate = rate
        loc.rate_source = source
        loc.rate_note = ""
    return said or [f"rates checked against {tag}"]


# ── A Comptroller charge drafts its return ───────────────────

def comptroller_charges(since=None):
    """Money out to the state, newest last, from every bank and statement."""
    import books_service
    from models import BankTransaction
    q = BankTransaction.query.filter(BankTransaction.amount < 0,
                                     BankTransaction.disposition != "void")
    if since:
        q = q.filter(BankTransaction.occurred_on >= since)
    return [t for t in q.order_by(BankTransaction.occurred_on, BankTransaction.id).all()
            if books_service.STATE_TAX_PAYMENT.search(f"{t.counterparty} {t.description}")]


def _expected(figures, due, paid_on):
    import sales_tax
    charges = sales_tax.charges_if_paid_on(figures["tax"], due, paid_on)
    owed = round(figures["tax"] + charges["penalty"] + charges["late_fee"] - charges["discount"], 2)
    return owed, charges


def _fits(charge, owed, charges):
    """Whether a charge can be this return: at least what was owed less a
    dollar of rounding, and no more than a card fee over, plus room for
    interest when the period is late enough to draw it."""
    import books_service
    room = owed * books_service.CARD_FEE_ROOM + 1.0
    if charges.get("interest_from") and charges["interest_from"] <= charges.get("paid_on", date.max):
        room += owed * 0.05
    return owed - 1.0 <= charge <= room


def draft_filings(today=None, sales_for=None):
    """Draft a return for each Comptroller charge with none recorded near it.

    `sales_for(business, start, end)` gives (sales, share) or (None, share),
    and defaults to the returns page's own reader. Returns words for the
    night's summary.
    """
    import books_service
    import sales_tax
    from models import db, SalesTaxFiling
    from pm import business_routes as br
    today = today or date.today()
    sales_for = sales_for or (lambda b, s, e: br.sales_between(b, s, e)[:2])
    said = []
    # A charge older than four months either has its return recorded or is
    # not a return; reading every one every night only repeats the summary.
    from models import DeadlineDone
    refused = {d.key for d in DeadlineDone.query.filter(DeadlineDone.key.like(f"{NO_DRAFT}%")).all()}
    for line in comptroller_charges(since=today - timedelta(days=CHARGE_DAYS)):
        business = line.business.parent if line.business.parent_id else line.business
        if business is None or f"{NO_DRAFT}{line.id}" in refused:
            continue
        if SalesTaxFiling.query.filter_by(drafted_from_line_id=line.id).first():
            continue
        if line.expense is not None and line.expense.sales_tax_filing_id:
            continue
        day = line.occurred_on
        near = [f for f in business.filings if f.filed_at and
                day - timedelta(days=books_service.FILED_AFTER) <= f.filed_at.date()
                <= day + timedelta(days=books_service.FILED_BEFORE)]
        if near:
            continue
        unfiled = [p for p in br.owed_periods(business, today)
                   if business.filing_for(*p) is None and sales_tax.quarter_bounds(*p)[1] < day]
        if not unfiled:
            continue
        charge = round(abs(line.amount), 2)
        start = sales_tax.quarter_bounds(*unfiled[0])[0]
        sales, share = sales_for(business, start, sales_tax.quarter_bounds(*unfiled[-1])[1])
        period, figures, charges = None, None, None
        if sales is not None:
            # The period just closed first, then older ones: Built by Bean
            # paid two back returns on one day.
            for p in reversed(unfiled):
                f = br.return_for(business, p[0], p[1], sales, share)
                owed, ch = _expected(f, sales_tax.due_date(*p), day)
                ch["paid_on"] = day
                if _fits(charge, owed, ch):
                    period, figures, charges = p, f, ch
                    break
            if period is None:
                said.append(f"{business.label}: ${charge:,.2f} to the state on {day} fits no open return")
                continue
        else:
            period = unfiled[-1]
        # business=, not business_id=: the draft has to be in business.filings
        # at once, or a second charge the same night drafts the same period.
        filing = SalesTaxFiling(business=business, year=period[0], quarter=period[1],
                                filed_at=datetime.combine(day, time(12, 0)), reference_number="",
                                drafted_from_line_id=line.id, recorded_by="board, from the bank",
                                payment_method="")
        notes = [f"Drafted from the ${charge:,.2f} charge to the Comptroller on {day:%b %d, %Y}."]
        if figures is not None:
            filing.total_sales = figures["total_sales"]
            filing.taxable_sales = figures["taxable_sales"]
            filing.tax_due = figures["tax"]
            filing.penalty = charges["penalty"]
            filing.late_filing_penalty = charges["late_fee"]
            filing.discount = charges["discount"]
            filing.amount_paid = round(figures["tax"] + charges["penalty"] + charges["late_fee"]
                                       - charges["discount"], 2)
            over = round(charge - filing.amount_paid, 2)
            if over > 0.005:
                filing.processing_fee = over
                filing.payment_method = "credit card"
                if charges.get("interest_from") and charges["interest_from"] <= day:
                    notes.append(f"The ${over:,.2f} over the tax and penalty is the card fee and "
                                 "interest together; split it from the confirmation.")
            else:
                filing.payment_method = "electronic check"
            filing.locations_json = json.dumps([
                {"number": l["number"], "label": l["label"], "total_sales": l["total_sales"],
                 "taxable_sales": l["taxable_sales"], "state_tax": l["state_tax"],
                 "local_tax": l["local_tax"]} for l in figures["lines"]])
            notes.append("The penalty and discount are the board's estimate; WebFile's confirmation is the figure.")
        else:
            filing.amount_paid = charge
            notes.append("No sales to work the return from; type the figures off the confirmation.")
        filing.notes = " ".join(notes)
        db.session.add(filing)
        db.session.flush()
        books_service.settle_sales_tax(filing)
        said.append(f"{business.label}: drafted {sales_tax.period_label(*period)} from ${charge:,.2f}")
    return said


# ── Confirmation mail ────────────────────────────────────────
#
# WebFile shows its confirmation on a page, and whether eSystems also mails
# one was not known when this was written (2026-11-04; the mailbox could not
# be read from the session that built it). So the nightly read searches each
# receipt mailbox for mail from the Comptroller, says in the night's summary
# how many it found, and fills a drafted return's reference numbers only when
# a message near its date states one and the amount matches.

SENDERS = ("cpa.texas.gov", "comptroller.texas.gov")
_REF_PATTERNS = {
    "reference_number": r"(?:confirmation|reference)\s*(?:number|no\.?|#)\s*[:#]?\s*([A-Z0-9-]{6,40})",
    "payment_reference": r"payment\s*(?:reference|confirmation)\s*(?:number|no\.?|#)?\s*[:#]?\s*([A-Z0-9-]{6,40})",
    "trace_number": r"trace\s*(?:number|no\.?|#)\s*[:#]?\s*([A-Z0-9-]{6,40})",
}


def parse_confirmation(text):
    """{reference_number, payment_reference, trace_number, amount} found in a
    message's text; absent keys were not found."""
    out = {}
    for key, pattern in _REF_PATTERNS.items():
        m = re.search(pattern, text or "", re.I)
        if m and re.search(r"\d", m.group(1)):
            out[key] = m.group(1).strip("-")[:40]
    amounts = [float(a.replace(",", "")) for a in re.findall(r"\$\s?([\d,]+\.\d{2})", text or "")]
    if amounts:
        out["amount"] = max(amounts)
    return out


def comptroller_mail(mailbox, since):
    """[(date, text)] of mail from the Comptroller since `since`."""
    import email as email_lib
    from email.utils import parsedate_to_datetime
    import receipts_service as rs
    conn = rs._connect(mailbox)
    found = []
    try:
        if "gmail" in mailbox.imap_host:
            query = f"after:{since:%Y/%m/%d} (" + " OR ".join(f"from:{s}" for s in SENDERS) + ")"
            status, data = conn.search(None, "X-GM-RAW", f'"{query}"')
        else:
            status, data = conn.search(None, "SINCE", since.strftime("%d-%b-%Y"), "FROM", '"texas.gov"')
        for mid in ((data[0] or b"").split() if status == "OK" else [])[-60:]:
            status, parts = conn.fetch(mid, "(BODY.PEEK[])")
            if status != "OK" or not parts or not isinstance(parts[0], tuple):
                continue
            msg = email_lib.message_from_bytes(parts[0][1])
            try:
                day = parsedate_to_datetime(msg.get("Date")).date()
            except (TypeError, ValueError):
                continue
            plain, html = rs._text_of(msg)
            found.append((day, f"{rs._decode(msg.get('Subject'))}\n{plain}\n{rs._strip(html)}"))
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    return found


def fill_from_mail(drafts, messages):
    """Fill drafted returns' references from parsed messages. Pure apart from
    setting attributes: `messages` is [(date, text)]."""
    filled = 0
    for filing in drafts:
        day = filing.filed_at.date()
        want = round((filing.amount_paid or 0) + (filing.processing_fee or 0), 2)
        for when, text in messages:
            if not (day - timedelta(days=1) <= when <= day + timedelta(days=2)):
                continue
            got = parse_confirmation(text)
            if "reference_number" not in got:
                continue
            if "amount" in got and want and not (filing.amount_paid - 0.01 <= got["amount"] <= want + 0.01):
                continue
            for key in ("reference_number", "payment_reference", "trace_number"):
                if got.get(key) and not getattr(filing, key):
                    setattr(filing, key, got[key])
            filing.notes = ((filing.notes or "") + " Reference numbers read from the Comptroller's email.").strip()
            filled += 1
            break
    return filled


def search_mail(today=None):
    from models import ReceiptMailbox, SalesTaxFiling
    today = today or date.today()
    drafts = [f for f in SalesTaxFiling.query.filter(SalesTaxFiling.drafted_from_line_id.isnot(None)).all()
              if f.is_draft and f.filed_at]
    seen, filled = 0, 0
    since = min([f.filed_at.date() for f in drafts] or [today]) - timedelta(days=2)
    since = min(since, today - timedelta(days=45))
    for mailbox in ReceiptMailbox.query.all():
        if not mailbox.password:
            continue
        messages = comptroller_mail(mailbox, since)
        seen += len(messages)
        filled += fill_from_mail(drafts, messages)
    return f"{seen} Comptroller emails since {since:%b %d}, {filled} returns filled from them"


# ── The night ────────────────────────────────────────────────

def run_all(today=None, franchise_get=None, permits_get=None, rates_get=None, sales_for=None,
            mail=True):
    """Every read, each business on its own so one bad answer never stops the
    rest. Returns (summary, errors)."""
    from models import db, Business, BusinessLocation
    today = today or date.today()
    said, errors = [], []
    for b in (Business.query.filter_by(is_active=True, parent_id=None)
              .order_by(Business.id).all()):
        for reader, get in ((read_franchise, franchise_get), (read_permits, permits_get)):
            try:
                said += reader(b, get)
                db.session.commit()
            except Exception as err:  # noqa: BLE001
                db.session.rollback()
                errors.append(f"{b.label} {reader.__name__}: {str(err)[:120]}")
    steps = [("rates", lambda: read_rates(
                 BusinessLocation.query.join(Business).filter(Business.is_active.is_(True)).all(),
                 today, rates_get)),
             ("drafts", lambda: draft_filings(today, sales_for))]
    if mail:
        steps.append(("mail", lambda: [search_mail(today)]))
    for name, fn in steps:
        try:
            said += fn()
            db.session.commit()
        except Exception as err:  # noqa: BLE001
            db.session.rollback()
            errors.append(f"{name}: {str(err)[:160]}")
    return said, errors


def main():
    """Nightly, from sync_costs._sweep. The summary is the night's note; any
    error fails the step so Needs attention shows it."""
    from app import create_app
    app = create_app()
    with app.app_context():
        said, errors = run_all()
    for line in said + errors:
        print(f"comptroller: {line}", flush=True)
    if errors:
        raise RuntimeError("; ".join(errors)[:500])
    return "; ".join(said)[:500] or "nothing changed"


if __name__ == "__main__":
    print(main())
