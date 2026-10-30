"""Built by Bean and EntertainHQ on file, with the first two returns

What was learned and done on 2026-10-30, written where it can be found:

  * Built by Bean LLC: taxpayer 32093304155, SOS 0805381976, registered for
    sales tax online 2026-10-28, first taxable sale 2026-04-09, quarterly.
    Sold from Fort Worth (WebFile location 00002) until 2026-09-17 and from
    Paris (00001) from the 18th, both 2% local.
  * EntertainHQ LLC: taxpayer 32108463343, SOS 6000011479, registered for
    sales tax 2026-10-28, first return Q4 2026, home-based in Paris. Its
    sales come from its own app.
  * The two returns filed and paid that morning, off their confirmation
    pages: April to June ($426.93) and July to September ($739.54), both
    late and both by card.
  * The three things left to do, on the to-do list with dates.

WebFile numbers are not here: Michael types those in. Every insert is
skipped when its row is already there, so running this against a board
where somebody got there first changes nothing. Bound parameters throughout,
because Postgres and SQLite disagree about multi-line literals.

Revision ID: d9a25e6c1b47
Revises: c4e81a7f2d93
Create Date: 2026-10-30
"""
import json
from datetime import date, datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "d9a25e6c1b47"
down_revision = "c4e81a7f2d93"
branch_labels = None
depends_on = None

NOW = datetime(2026, 10, 30, 17, 0, tzinfo=timezone.utc).replace(tzinfo=None)

BUSINESSES = [
    dict(slug="built-by-bean", name="Built by Bean LLC", short_name="Built by Bean",
         texas_taxpayer_number="32093304155", sos_file_number="0805381976",
         formed_on=date(2024, 1, 17), sales_tax_registered_on=date(2026, 10, 28),
         sales_tax_first_sale=date(2026, 4, 9), sales_tax_frequency="quarterly",
         taxable_share=80.0, naics_code="541511", sales_source="board", hub_slug=None,
         admin_url="https://builtbybeans.com/admin",
         notes=("Registered for sales tax online on Oct 28, 2026, six months after the first "
                "sale. Apr-Jun and Jul-Sep 2026 were filed late on Oct 30, 2026 and paid by card.")),
    # From EntertainHQ's own playbook (docs/legal/texas_sales_tax_playbook.md,
    # section 0) and its filing calendar's facts block.
    dict(slug="entertainhq", name="EntertainHQ LLC", short_name="EntertainHQ",
         texas_taxpayer_number="32108463343", sos_file_number="6000011479",
         formed_on=date(2026, 10, 5), sales_tax_registered_on=date(2026, 10, 28),
         sales_tax_first_sale=date(2026, 11, 6), sales_tax_frequency="quarterly",
         taxable_share=80.0, naics_code="511210", sales_source="hub", hub_slug="entertainhq",
         admin_url="https://entertainhq.com/admin",
         notes=("Registered for sales tax online on Oct 28, 2026; first return Q4 2026, due "
                "Jan 20, 2027. Stripe Tax works out and collects the tax. Partners work in its "
                "own admin site, whose filing calendar reads and records returns here.")),
]

LOCATIONS = [
    dict(business="built-by-bean", webfile_number="00002", label="Fort Worth",
         address="7112 Culver Ave, Fort Worth, TX 76116", county="Tarrant", local_rate=2.0,
         opened_on=date(2026, 4, 9), closed_on=date(2026, 9, 17), closure_filed=False),
    dict(business="built-by-bean", webfile_number="00001", label="Paris",
         address="3244 Spaulding Dr, Paris, TX 75460", county="Lamar", local_rate=2.0,
         opened_on=date(2026, 9, 18), closed_on=None, closure_filed=False),
    # Its WebFile location number is not known until its first return.
    dict(business="entertainhq", webfile_number="", label="Paris",
         address="3244 Spaulding Dr, Paris, TX 75460", county="Lamar", local_rate=2.0,
         opened_on=date(2026, 10, 5), closed_on=None, closure_filed=False),
]

FILINGS = [
    dict(business="built-by-bean", year=2026, quarter=2,
         filed_at=datetime(2026, 10, 30, 11, 18, 31), reference_number="30326097098",
         payment_reference="3981644614", trace_number="902AA0027035190",
         payment_method="credit card", total_sales=5150.0, taxable_sales=4120.0,
         tax_due=339.90, penalty=34.00, late_filing_penalty=50.00, interest=3.03,
         discount=0.0, amount_paid=426.93, processing_fee=9.86,
         locations=[{"number": "00002", "label": "Fort Worth", "total_sales": 5150,
                     "taxable_sales": 4120, "state_tax": 257.50, "local_tax": 82.40}],
         notes="Filed 102 days late. The state had posted an estimated return of $1,158.93."),
    dict(business="built-by-bean", year=2026, quarter=3,
         filed_at=datetime(2026, 10, 30, 11, 25, 23), reference_number="30326098451",
         payment_reference="3029644780", trace_number="902AA0027035223",
         payment_method="credit card", total_sales=9950.0, taxable_sales=7960.0,
         tax_due=656.70, penalty=32.84, late_filing_penalty=50.00, interest=0.0,
         discount=0.0, amount_paid=739.54, processing_fee=16.89,
         locations=[{"number": "00001", "label": "Paris", "total_sales": 2500,
                     "taxable_sales": 2000, "state_tax": 125.00, "local_tax": 40.00},
                    {"number": "00002", "label": "Fort Worth", "total_sales": 7450,
                     "taxable_sales": 5960, "state_tax": 372.50, "local_tax": 119.20}],
         notes="Filed 10 days late. The state had posted an estimated return of $2,202.53."),
]

TODOS = [
    dict(title="Ask the Comptroller to waive Built by Bean's late penalties",
         body=("Apr-Jun and Jul-Sep 2026 were filed late on Oct 30, 2026 and paid in full: "
               "$84.00 and $82.84 in penalties and late filing fees, $3.03 interest. "
               "Form 89-224, or 800-531-5441 ext. 3-4560. First time, two reports."),
         due_on=date(2026, 11, 13)),
    dict(title="Tell the Comptroller Built by Bean's Fort Worth location closed Sep 17, 2026",
         body=("Location 00002, 7112 Culver Ave. Until it is closed every WebFile return asks "
               "for a line for it. Then tick \"State told it closed\" on the Businesses page."),
         due_on=date(2026, 11, 13)),
    dict(title="Move Built by Bean's Secretary of State address to Paris",
         body="The registered office and franchise tax mailing address still say 7112 Culver Ave, Fort Worth.",
         due_on=None),
    dict(title="File Built by Bean's Oct-Dec 2026 sales tax",
         body="Due Jan 20, 2027. Taxes, Returns has the numbers to type. On time keeps 0.5%.",
         due_on=date(2027, 1, 20)),
]


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    bind = op.get_bind()
    have = _tables()
    if not {"businesses", "business_locations", "sales_tax_filings"} <= have:
        return

    ids = {}
    for b in BUSINESSES:
        row = bind.execute(sa.text("SELECT id FROM businesses WHERE slug = :slug"),
                           {"slug": b["slug"]}).first()
        if row is None:
            bind.execute(sa.text(
                "INSERT INTO businesses (name, short_name, slug, texas_taxpayer_number, "
                "sos_file_number, formed_on, franchise_tax_webfile, sales_tax_webfile, "
                "sales_tax_registered_on, sales_tax_first_sale, sales_tax_frequency, "
                "taxable_share, naics_code, sales_source, admin_url, hub_slug, hub_base_url, hub_secret, "
                "hub_pull_note, notes, is_active, created_at, updated_at) VALUES (:name, "
                ":short_name, :slug, :texas_taxpayer_number, :sos_file_number, :formed_on, '', "
                "'', :sales_tax_registered_on, :sales_tax_first_sale, :sales_tax_frequency, "
                ":taxable_share, :naics_code, :sales_source, :admin_url, :hub_slug, '', '', '', :notes, "
                ":active, :now, :now)"), dict(b, active=True, now=NOW))
            row = bind.execute(sa.text("SELECT id FROM businesses WHERE slug = :slug"),
                               {"slug": b["slug"]}).first()
        ids[b["slug"]] = row[0]

    for loc in LOCATIONS:
        bid = ids[loc["business"]]
        exists = bind.execute(sa.text(
            "SELECT id FROM business_locations WHERE business_id = :bid AND label = :label"),
            {"bid": bid, "label": loc["label"]}).first()
        if exists is None:
            bind.execute(sa.text(
                "INSERT INTO business_locations (business_id, webfile_number, label, address, "
                "county, local_rate, opened_on, closed_on, closure_filed) VALUES (:bid, "
                ":webfile_number, :label, :address, :county, :local_rate, :opened_on, "
                ":closed_on, :closure_filed)"), dict(loc, bid=bid))

    for f in FILINGS:
        bid = ids[f["business"]]
        exists = bind.execute(sa.text(
            "SELECT id FROM sales_tax_filings WHERE business_id = :bid AND year = :year "
            "AND quarter = :quarter"), {"bid": bid, "year": f["year"], "quarter": f["quarter"]}).first()
        if exists is None:
            values = {k: v for k, v in f.items() if k not in ("business", "locations")}
            bind.execute(sa.text(
                "INSERT INTO sales_tax_filings (business_id, year, quarter, filed_at, "
                "reference_number, payment_reference, trace_number, payment_method, total_sales, "
                "taxable_sales, tax_due, penalty, late_filing_penalty, interest, discount, "
                "amount_paid, processing_fee, locations_json, notes, recorded_by, created_at, "
                "updated_at) VALUES (:bid, :year, :quarter, :filed_at, :reference_number, "
                ":payment_reference, :trace_number, :payment_method, :total_sales, "
                ":taxable_sales, :tax_due, :penalty, :late_filing_penalty, :interest, :discount, "
                ":amount_paid, :processing_fee, :locations_json, :notes, :who, :now, :now)"),
                dict(values, bid=bid, locations_json=json.dumps(f["locations"]),
                     who="Claude, from the confirmation page", now=NOW))

    if "notes" in have:
        for t in TODOS:
            exists = bind.execute(sa.text("SELECT id FROM notes WHERE title = :title"),
                                  {"title": t["title"]}).first()
            if exists is None:
                bind.execute(sa.text(
                    "INSERT INTO notes (title, body, due_on, created_at, updated_at) "
                    "VALUES (:title, :body, :due_on, :now, :now)"), dict(t, now=NOW))


def downgrade():
    bind = op.get_bind()
    have = _tables()
    if "notes" in have:
        for t in TODOS:
            bind.execute(sa.text("DELETE FROM notes WHERE title = :title AND done_at IS NULL"),
                         {"title": t["title"]})
    if not {"businesses", "business_locations", "sales_tax_filings"} <= have:
        return
    for b in BUSINESSES:
        row = bind.execute(sa.text("SELECT id FROM businesses WHERE slug = :slug"),
                           {"slug": b["slug"]}).first()
        if row is None:
            continue
        # Children first, by hand: SQLite does not enforce ON DELETE CASCADE
        # unless the connection asked it to.
        filing_ids = [r[0] for r in bind.execute(sa.text(
            "SELECT id FROM sales_tax_filings WHERE business_id = :bid"), {"bid": row[0]})]
        if "sales_tax_filing_files" in have:
            for fid in filing_ids:
                bind.execute(sa.text("DELETE FROM sales_tax_filing_files WHERE filing_id = :fid"),
                             {"fid": fid})
        bind.execute(sa.text("DELETE FROM sales_tax_filings WHERE business_id = :bid"),
                     {"bid": row[0]})
        bind.execute(sa.text("DELETE FROM business_locations WHERE business_id = :bid"),
                     {"bid": row[0]})
        bind.execute(sa.text("DELETE FROM businesses WHERE id = :bid"), {"bid": row[0]})
