# -*- coding: utf-8 -*-
"""What the state says about each business (comptroller.py), against the
answers the state actually gave on 2026-11-04.

  1. The franchise tax search fills empty fields, keeps the state's own
     fields and flags a change, never overwrites a typed number, and a
     standing that leaves ACTIVE is a loud row only the CEO sees.
  2. The permit list (jrea-zgmq) fills NAICS, permit date and first sale,
     makes or matches the outlet's location, ignores the 1961 "unknown" date,
     flags an outlet that drops off, and says in words when a number finds no
     permit at all (Built by Bean's did).
  3. The quarterly city rate file sets an untyped location's local rate,
     refuses a file still naming last quarter, will not guess a town with
     several rates, leaves a typed rate alone, and flags a change.
  4. A Comptroller charge drafts the return for the period it paid, to the
     cent of what WebFile would charge, Built by Bean's real late return
     included; a charge with a return near it, or one that fits nothing, is
     left; a second night drafts nothing twice; typing the reference number
     makes it filed; a confirmation email fills it when one says so.

Run: python tools/test_comptroller.py         (offline, the fixtures below)
     python tools/test_comptroller.py --live  (also asks the state)
"""
import io
import json
import os
import pathlib
import sys
import tempfile
import zipfile
from datetime import date, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-comptroller-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, Business, BusinessLocation,  # noqa: E402
                    ComptrollerFlag, SalesTaxFiling, User)
import comptroller  # noqa: E402
import deadlines  # noqa: E402
import sales_tax  # noqa: E402

application = create_app()
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


# The franchise search's answer for Built by Bean, 2026-11-04, verbatim.
BBB_FRANCHISE = {"success": True, "data": {
    "taxpayerId": "32093304155", "feiNumber": "990826653", "name": "BUILT BY BEAN LLC", "dbaName": None,
    "mailingAddressStreet": "7112 CULVER AVE", "mailingAddressCity": "FORT WORTH",
    "mailingAddressState": "TX", "mailingAddressZip": "76116", "mailingAddressZip4": "8700",
    "rightToTransactTX": "ACTIVE", "rightToTransactTXLink": None, "stateOfFormation": " TX",
    "sosRegistrationStatus": "ACTIVE", "effectiveSosRegistrationDate": "01/17/2024",
    "sosFileNumber": "0805381976", "registeredAgentName": "MICHAEL E BEAN",
    "registeredOfficeAddressStreet": "7112 CULVER AVE", "registeredOfficeAddressCity": "FORT WORTH",
    "registeredOfficeAddressState": "TX", "registeredOfficeAddressZip": "76116", "taxId": 13,
    "lastUpdated": "2026-11-04T18:39:57.160Z", "reportYear": "2026",
    "officerInfo": [{"AGNT_NM": "MICHAEL BEAN", "AGNT_TITL_TX": "MEMBER"}]}}
# jrea-zgmq's row for EntertainHQ, 2026-11-04, verbatim.
EHQ_OUTLET = {
    "taxpayer_number": "32108463343", "taxpayer_name": "ENTERTAINHQ LLC",
    "taxpayer_address": "3244 SPAULDING DR", "taxpayer_city": "PARIS", "taxpayer_state": "TX",
    "taxpayer_zip_code": "75460", "taxpayer_county_code": "139", "taxpayer_organization_type": "CL",
    "outlet_number": "1", "outlet_name": "ENTERTAINHQ LLC", "outlet_address": "3244 SPAULDING DR",
    "outlet_city": "PARIS", "outlet_state": "TX", "outlet_zip_code": "75460", "outlet_county_code": "139",
    "outlet_naics_code": "511210", "outlet_inside_outside_city_limits_indicator": "Y",
    "outlet_permit_issue_date": "2026-10-29T00:00:00.000",
    "outlet_first_sales_date": "2026-11-06T00:00:00.000"}


def franchise(data):
    return lambda url: data


def xlsx(sheet, rows):
    """A workbook shaped like city-rates.xlsx: shared strings and numbers."""
    strings, xml_rows = [], []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = chr(65 + c) + str(r)
            if isinstance(value, str):
                strings.append(value)
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns}><sheets><sheet name="{sheet}" sheetId="1"/></sheets></workbook>')
        z.writestr("xl/sharedStrings.xml", f'<sst {ns}>' + "".join(
            f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet {ns}><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
    return buf.getvalue()


HEAD = ["CityName", "CityNumber", "CityTax", "CountyName", "CountyNumber", "CountyTax", " TotalTax   "]
RATES = [HEAD,
         ["Paris                         ", 2139013, 0.015, "Lamar   ", 4139004, 0.005, 0.0825],
         ["Fort Worth                    ", 2220031, 0.01, "Tarrant ", "n/a    ", 0, 0.0825],
         ["Fort Worth                    ", 2220031, 0.01, "Denton  ", "n/a    ", 0, 0.0825],
         ["Houston", 2101000, 0.01, "Harris", "n/a", 0, 0.0825],
         ["Houston", 2101000, 0.01, "Harris", "n/a", 0, 0.08],
         ["Blossom", 2139022, 0.01, "Lamar", 4139004, 0.005, 0.0775]]

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    member = User(username="hb", email="hb@example.test", first_name="Hannah", role="member")
    member.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="built-by-bean",
                   texas_taxpayer_number="32093304155", sales_tax_first_sale=date(2026, 4, 9),
                   sales_tax_webfile="RT000000", sales_source="manual", taxable_share=80.0)
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="entertainhq",
                   texas_taxpayer_number="32108463343", sales_source="manual", taxable_share=80.0)
    db.session.add_all([boss, member, bbb, ehq])
    db.session.flush()
    db.session.add_all([
        BusinessLocation(business_id=bbb.id, webfile_number="00002", label="Fort Worth",
                         local_rate=2.0, opened_on=date(2026, 4, 9), closed_on=date(2026, 9, 17)),
        BusinessLocation(business_id=bbb.id, webfile_number="00001", label="Paris",
                         local_rate=2.0, opened_on=date(2026, 9, 18)),
    ])
    db.session.commit()
    boss_id, member_id, bbb_id, ehq_id = boss.id, member.id, bbb.id, ehq.id

print("1. THE FRANCHISE TAX SEARCH")
with application.app_context():
    b = db.session.get(Business, bbb_id)
    said = comptroller.read_franchise(b, franchise(BBB_FRANCHISE))
    db.session.commit()
    check("standing, agent, office and EIN are kept",
          (b.franchise_status, b.registered_agent, b.registered_office, b.ein)
          == ("ACTIVE", "MICHAEL E BEAN", "7112 CULVER AVE, FORT WORTH, TX 76116", "990826653"),
          (b.franchise_status, b.registered_agent, b.registered_office, b.ein))
    check("the empty SOS number and formation date are filled",
          b.sos_file_number == "0805381976" and b.formed_on == date(2024, 1, 17),
          (b.sos_file_number, b.formed_on))
    check("this year's report is on file", b.franchise_report_year == 2026, b.franchise_report_year)
    check("a first read flags nothing", ComptrollerFlag.query.count() == 0, ComptrollerFlag.query.count())

    moved = json.loads(json.dumps(BBB_FRANCHISE))
    moved["data"].update(registeredAgentName="NORTHWEST REGISTERED AGENT", sosFileNumber="0805999999")
    comptroller.read_franchise(b, franchise(moved))
    comptroller.read_franchise(b, franchise(moved))
    db.session.commit()
    agent = ComptrollerFlag.query.filter_by(kind="agent").all()
    check("a new registered agent is flagged once, however many nights see it",
          len(agent) == 1 and agent[0].old_value == "MICHAEL E BEAN"
          and agent[0].new_value == "NORTHWEST REGISTERED AGENT", [(f.old_value, f.new_value) for f in agent])
    check("a different SOS number is flagged and the typed one kept",
          b.sos_file_number == "0805381976" and ComptrollerFlag.query.filter_by(kind="sos_number").count() == 1)

    gone = json.loads(json.dumps(BBB_FRANCHISE))
    gone["data"]["rightToTransactTX"] = "FORFEITED"
    comptroller.read_franchise(b, franchise(gone))
    db.session.commit()
    check("a forfeited standing is kept and flagged",
          b.franchise_status == "FORFEITED" and ComptrollerFlag.query.filter_by(kind="standing").count() == 1)
    check("and is a standing problem", [x.id for x in deadlines.standing_problems()] == [bbb_id])
    check("an unknown number says so",
          comptroller.read_franchise(db.session.get(Business, ehq_id), franchise({"success": True, "data": None}))
          and "no record" in db.session.get(Business, ehq_id).comptroller_note)
    db.session.rollback()

c = application.test_client()
with c.session_transaction() as sess:
    sess["_user_id"] = str(boss_id)
page = c.get("/admin/attention/").get_data(as_text=True)
check("Needs attention carries the forfeited company in red for the CEO",
      "data-standing-row" in page and "FORFEITED" in page)
check("and the agent change, with a Seen press", "NORTHWEST REGISTERED AGENT" in page and "Seen" in page)
with c.session_transaction() as sess:
    sess["_user_id"] = str(member_id)
page = c.get("/admin/attention/").get_data(as_text=True)
check("the marketing seat sees none of it", "data-standing-row" not in page and "data-flag-row" not in page)
with c.session_transaction() as sess:
    sess["_user_id"] = str(boss_id)

with application.app_context():
    b = db.session.get(Business, bbb_id)
    comptroller.read_franchise(b, franchise(BBB_FRANCHISE))
    db.session.commit()
    check("ACTIVE again is no longer a standing problem", deadlines.standing_problems() == [])
    agent = ComptrollerFlag.query.filter_by(kind="agent", seen_at=None).first()
    agent_id = agent.id
r = c.post(f"/admin/taxes/flags/{agent_id}/seen", data={"next": "/admin/attention/"})
with application.app_context():
    check("Seen clears a flag", r.status_code == 302 and db.session.get(ComptrollerFlag, agent_id).seen_at is not None)

print("\n2. THE PERMIT LIST")
with application.app_context():
    e = db.session.get(Business, ehq_id)
    said = comptroller.read_permits(e, lambda url, params: [EHQ_OUTLET])
    db.session.commit()
    loc = e.locations[0] if e.locations else None
    check("NAICS, permit date and first sale are filled",
          (e.naics_code, e.sales_tax_registered_on, e.sales_tax_first_sale)
          == ("511210", date(2026, 10, 29), date(2026, 11, 6)),
          (e.naics_code, e.sales_tax_registered_on, e.sales_tax_first_sale))
    check("the outlet is a location numbered as WebFile numbers it",
          loc is not None and loc.webfile_number == "00001" and loc.city == "Paris"
          and loc.address == "3244 SPAULDING DR, Paris, TX 75460" and loc.inside_city_limits is True
          and loc.opened_on == date(2026, 11, 6), loc and (loc.webfile_number, loc.city, loc.address))
    check("and a new outlet is flagged", ComptrollerFlag.query.filter_by(kind="outlet", business_id=ehq_id).count() == 1)
    check("the permit is found", e.permit_status == "found")

    second = dict(EHQ_OUTLET, outlet_number="2", outlet_city="BLOSSOM", outlet_address="1 MAIN ST",
                  outlet_first_sales_date="1961-09-01T00:00:00.000")
    comptroller.read_permits(e, lambda url, params: [EHQ_OUTLET, second])
    db.session.commit()
    blossom = next(l for l in e.locations if l.webfile_number == "00002")
    check("the 1961 'unknown' start date is never a date", blossom.opened_on == date(2026, 10, 29),
          blossom.opened_on)
    comptroller.read_permits(e, lambda url, params: [EHQ_OUTLET])
    db.session.commit()
    dropped = ComptrollerFlag.query.filter(ComptrollerFlag.title.contains("dropped off")).all()
    check("an outlet that drops off the list is flagged",
          len(dropped) == 1 and dropped[0].location_id == blossom.id and blossom.permit_listed is False)

    b = db.session.get(Business, bbb_id)
    comptroller.read_permits(b, lambda url, params: [])
    comptroller.read_permits(b, lambda url, params: [])
    db.session.commit()
    check("a number that finds no permit says so, once",
          b.permit_status == "none"
          and ComptrollerFlag.query.filter_by(kind="permit", business_id=bbb_id).count() == 1)
    # A typed location with no number, in the outlet's town, takes the number.
    typed = Business(name="Typed LLC", slug="typed", texas_taxpayer_number="32000000001",
                     sales_source="manual")
    db.session.add(typed)
    db.session.flush()
    db.session.add(BusinessLocation(business_id=typed.id, label="Paris", local_rate=2.0))
    db.session.commit()
    comptroller.read_permits(typed, lambda url, params: [dict(EHQ_OUTLET, taxpayer_number="32000000001")])
    db.session.commit()
    check("a location typed before its number was known is matched, not doubled",
          len(typed.locations) == 1 and typed.locations[0].webfile_number == "00001")

for path in ("/admin/taxes/sales/returns", f"/admin/businesses/{bbb_id}"):
    page = c.get(path).get_data(as_text=True)
    check(f"{path} says in words that no permit was found",
          "has nothing under 32093304155" in page, page[:200])

print("\n3. THE LOCAL RATE FILE")
name, rows = comptroller.read_xlsx(xlsx("Oct26", RATES))
rates = comptroller.parse_rates(rows)
check("the workbook reads without a library", name == "Oct26" and len(rates) == 6, (name, len(rates)))
check("Paris is 2% local, in Lamar (139)",
      comptroller.rate_for(rates, "Paris") == (2.0, "Lamar", None)
      and rates[0]["county_code"] == "139", comptroller.rate_for(rates, "Paris"))
check("Fort Worth across two counties at one rate is still one rate",
      comptroller.rate_for(rates, "Fort Worth")[0] == 2.0)
check("a town with two rates is not guessed", comptroller.rate_for(rates, "Houston")[0] is None)
check("the quarter's sheet name", comptroller.quarter_tag(date(2026, 11, 4)) == "Oct26"
      and comptroller.quarter_tag(date(2027, 1, 1)) == "Jan27")
with application.app_context():
    locs = BusinessLocation.query.all()
    said = comptroller.read_rates(locs, date(2026, 11, 4), lambda url: xlsx("Jul26", RATES))
    check("a file still naming last quarter writes nothing",
          all(not l.rate_source for l in locs) and "tomorrow" in said[0], said)
    blossom = BusinessLocation.query.filter_by(webfile_number="00002", business_id=ehq_id).first()
    blossom.closed_on = None
    blossom.city = "Blossom"
    bbb_paris = BusinessLocation.query.filter_by(business_id=bbb_id, webfile_number="00001").first()
    bbb_paris.rate_source = "typed"
    bbb_paris.local_rate = 1.5
    said = comptroller.read_rates(locs, date(2026, 11, 4), lambda url: xlsx("Oct26", RATES))
    db.session.commit()
    ehq_paris = BusinessLocation.query.filter_by(business_id=ehq_id, webfile_number="00001").first()
    check("an untyped location takes the file's rate and its county",
          ehq_paris.rate_source == "Comptroller Oct26" and ehq_paris.local_rate == 2.0
          and ehq_paris.county == "Lamar", (ehq_paris.rate_source, ehq_paris.county))
    check("a 2.0 that was really 1.5 becomes 1.5", blossom.local_rate == 1.5, blossom.local_rate)
    check("a typed rate is left alone", bbb_paris.local_rate == 1.5 and bbb_paris.rate_source == "typed")
    check("a closed location is not touched",
          BusinessLocation.query.filter_by(label="Fort Worth").first().rate_source in ("", None))
    check("the first rate written is not a change", ComptrollerFlag.query.filter_by(kind="rate").count() == 0)
    rows2 = [r[:] for r in RATES]
    rows2[6][6] = 0.08
    comptroller.read_rates(locs, date(2027, 1, 5), lambda url: xlsx("Jan27", rows2))
    db.session.commit()
    flag = ComptrollerFlag.query.filter_by(kind="rate").first()
    check("next quarter's change is flagged with both rates",
          flag is not None and flag.old_value == "1.5%" and flag.new_value == "1.75%",
          flag and (flag.old_value, flag.new_value))
    bbb_paris.rate_source = ""
    bbb_paris.local_rate = 2.0
    db.session.commit()

print("\n4. A COMPTROLLER CHARGE DRAFTS ITS RETURN")
SALES = [{"date": date(2026, 9, 30), "total": 2500.0, "taxable": None}]


def sales_for(business, start, end):
    return [s for s in SALES if start <= s["date"] <= end], business.taxable_share


with application.app_context():
    b = db.session.get(Business, bbb_id)
    for loc in b.locations:
        loc.local_rate = 2.0
    conn = BankConnection(business_id=bbb_id, provider="statement", label="Chase")
    db.session.add(conn)
    db.session.flush()

    def line(day, amount, who="TX COMPTROLLER WEBFILE", ext=None):
        t = BankTransaction(connection_id=conn.id, business_id=bbb_id, external_id=ext or f"{day}-{amount}",
                            amount=-amount, occurred_on=day, counterparty=who, status="sent",
                            disposition="expense")
        db.session.add(t)
        db.session.flush()
        return t

    # Q3 2026 paid on time by electronic check: $165.00 less the 0.5% discount.
    q3 = line(date(2026, 10, 15), 164.17)
    said = comptroller.draft_filings(date(2026, 10, 16), sales_for)
    db.session.commit()
    f = SalesTaxFiling.query.filter_by(drafted_from_line_id=q3.id).first()
    check("an on-time charge drafts Jul-Sep 2026", f is not None and (f.year, f.quarter) == (2026, 3), said)
    check("with WebFile's figures and no reference",
          f and (f.total_sales, f.taxable_sales, f.tax_due, f.discount, f.amount_paid, f.processing_fee,
                 f.payment_method, f.reference_number)
          == (2500.0, 2000.0, 165.0, 0.83, 164.17, 0.0, "electronic check", ""),
          f and (f.total_sales, f.taxable_sales, f.tax_due, f.discount, f.amount_paid, f.processing_fee))
    check("its location line is Paris", f and f.location_rows[0]["number"] == "00001")
    check("a draft reads as drafted, not filed or late",
          sales_tax.status_of(2026, 3, f, date(2026, 11, 4)) == "drafted")
    again = comptroller.draft_filings(date(2026, 10, 17), sales_for)
    check("a second night drafts nothing twice",
          SalesTaxFiling.query.filter_by(business_id=bbb_id).count() == 1, again)
    draft_id = f.id
    db.session.commit()
    r = c.post(f"/admin/taxes/sales/filings/{draft_id}/delete")
    db.session.expire_all()
    comptroller.draft_filings(date(2026, 10, 18), sales_for)
    check("a draft taken off the board is not drafted again",
          r.status_code == 302 and SalesTaxFiling.query.filter_by(business_id=bbb_id).count() == 0)

    # Built by Bean's real Q2 2026 return: $339.90 of tax, filed 102 days late
    # on 2026-10-30 by card. WebFile charged $34.00 penalty, $50 late fee and
    # interest, $426.93 in all, plus a $9.86 card fee: $436.79 left the bank.
    SALES[:] = [{"date": date(2026, 4, 9), "total": 5150.0, "taxable": 4120.0}]
    q2 = line(date(2026, 10, 30), 436.79, who="Texas Comptroller of Public Accounts")
    comptroller.draft_filings(date(2026, 11, 4), sales_for)
    db.session.commit()
    f = SalesTaxFiling.query.filter_by(drafted_from_line_id=q2.id).first()
    check("the real late return drafts as Apr-Jun 2026", f is not None and (f.year, f.quarter) == (2026, 2),
          f and (f.year, f.quarter))
    check("tax $339.90, penalty and the $50 fee from the board's estimate",
          f and (f.tax_due, f.penalty, f.late_filing_penalty) == (339.9, 33.99, 50.0),
          f and (f.tax_due, f.penalty, f.late_filing_penalty))
    check("the rest of the charge is named as card fee and interest together",
          f and f.processing_fee == 12.9 and "interest together" in f.notes, f and (f.processing_fee, f.notes))

    # A charge with a return recorded beside it is that return's.
    f.reference_number = "00012345"
    db.session.commit()
    near = line(date(2026, 11, 1), 50.0)
    comptroller.draft_filings(date(2026, 11, 4), sales_for)
    check("a charge with a return near it drafts nothing",
          SalesTaxFiling.query.filter_by(drafted_from_line_id=near.id).count() == 0)
    # A charge that fits no open return (a franchise payment, say) is left.
    SALES[:] = [{"date": date(2026, 9, 30), "total": 2500.0, "taxable": None}]
    odd = line(date(2026, 12, 10), 900.0)
    said = comptroller.draft_filings(date(2026, 12, 11), sales_for)
    check("a charge that fits nothing is left and said",
          SalesTaxFiling.query.filter_by(drafted_from_line_id=odd.id).count() == 0
          and any("fits no open return" in s for s in said), said)
    card = line(date(2026, 10, 16), 168.00)
    comptroller.draft_filings(date(2026, 10, 17), sales_for)
    db.session.commit()
    f3 = SalesTaxFiling.query.filter_by(drafted_from_line_id=card.id).first()
    check("a card charge a few dollars over is the card fee",
          f3 and (f3.year, f3.quarter, f3.payment_method) == (2026, 3, "credit card")
          and f3.processing_fee == round(168.00 - f3.amount_paid, 2), f3 and (f3.year, f3.quarter, f3.processing_fee))
    f3_id = f3.id

    text = ("Thank you for your payment. Confirmation Number: 98765432 Payment Reference Number: "
            "PR123456789 Trace Number: 1234567890 Amount: $168.00")
    got = comptroller.parse_confirmation(text)
    check("a confirmation's numbers are read",
          got.get("reference_number") == "98765432" and got.get("payment_reference") == "PR123456789"
          and got.get("trace_number") == "1234567890" and got.get("amount") == 168.0, got)
    filled = comptroller.fill_from_mail([f3], [(date(2026, 10, 24), text)])
    check("mail a week away fills nothing", filled == 0 and f3.is_draft)
    filled = comptroller.fill_from_mail([f3], [(date(2026, 10, 16), text)])
    db.session.commit()
    check("mail the same day fills the reference numbers",
          filled == 1 and f3.reference_number == "98765432" and not f3.is_draft)
    f3.reference_number = ""
    db.session.commit()

page = c.get("/admin/attention/").get_data(as_text=True)
check("a drafted return asks for its reference on Needs attention",
      "type its reference number" in page)
r = c.post("/admin/taxes/sales/returns/built-by-bean/2026/q3/record", data={
    "reference_number": "55555555", "filed_on": "2026-10-16", "total_sales": "2500", "taxable_sales": "2000",
    "tax_due": "165", "penalty": "0", "late_filing_penalty": "0", "interest": "0", "discount": "0",
    "processing_fee": "3.83", "amount_paid": "164.17", "payment_method": "credit card"})
with application.app_context():
    f3 = db.session.get(SalesTaxFiling, f3_id)
    check("typing the reference number makes the draft filed",
          r.status_code == 302 and f3.reference_number == "55555555"
          and sales_tax.status_of(2026, 3, f3, date(2026, 12, 13)) == "filed")

if "--live" in sys.argv:
    print("\nLIVE")
    with application.app_context():
        data = comptroller.fetch_franchise("32093304155")
        check("the franchise search answers for Built by Bean", data and data.get("rightToTransactTX"), data)
        rows = comptroller.fetch_permits("32108463343")
        check("the permit list has EntertainHQ's outlet", any(r.get("outlet_number") for r in rows), rows)
        import requests
        name, rows = comptroller.read_xlsx(requests.get(comptroller.RATES_URL, headers=comptroller.HEADERS,
                                                        timeout=60).content)
        rates = comptroller.parse_rates(rows)
        check(f"the rate file ({name}) reads, Paris at 2%",
              comptroller.rate_for(rates, "Paris", "Lamar")[0] == 2.0, comptroller.rate_for(rates, "Paris"))

print("\n" + ("all passed" if not FAIL else "FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
