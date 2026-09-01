"""Work out federal tax on business profit from facts rather than from a rate.

The user supplies what they know: filing status, wages, withholding. Everything
else is computed here, and the result carries its own working so the page can
show how it got there. A tax number nobody can check is a number nobody should
act on.

Scope, stated plainly, because what is missing matters as much as what is here:

  * Federal only. State comes in as a flat rate, which is right for Texas at
    zero and wrong for a state with brackets.
  * The standard deduction. No itemising, no credits, no dependents.
  * QBI at the simple 20%, with the taxable-income cap but without the
    specified-service phaseout that starts around $400k for a joint return.
  * No AMT, no NIIT, no capital gains, no retirement contributions.

The rate tables are published annually by the IRS. The 2026 figures below are
inflation adjustments and should be checked against the relevant Revenue
Procedure before anybody files on them. They are shown on the page for exactly
that reason.
"""

FILING_STATUSES = [
    ("single", "Single"),
    ("mfj", "Married filing jointly"),
    ("mfs", "Married filing separately"),
    ("hoh", "Head of household"),
]
FILING_LABELS = dict(FILING_STATUSES)

SE_SOCIAL_SECURITY = 0.124
SE_MEDICARE = 0.029
# SE tax is charged on 92.35% of profit. The adjustment stands in for the
# employer half that a wage earner never sees deducted.
SE_BASE_FRACTION = 0.9235
ADDITIONAL_MEDICARE = 0.009

# Brackets are (upper bound of the band, rate). The last band has no bound.
_2026 = {
    "standard_deduction": {"single": 15_750.0, "mfj": 31_500.0, "mfs": 15_750.0, "hoh": 23_600.0},
    "ss_wage_base": 184_500.0,
    "additional_medicare_threshold": {
        "single": 200_000.0, "mfj": 250_000.0, "mfs": 125_000.0, "hoh": 200_000.0,
    },
    "brackets": {
        "single": [(12_250, 0.10), (49_800, 0.12), (106_150, 0.22), (202_700, 0.24),
                   (257_300, 0.32), (643_300, 0.35), (None, 0.37)],
        "mfj": [(24_500, 0.10), (99_600, 0.12), (212_300, 0.22), (405_400, 0.24),
                (514_600, 0.32), (771_900, 0.35), (None, 0.37)],
        "mfs": [(12_250, 0.10), (49_800, 0.12), (106_150, 0.22), (202_700, 0.24),
                (257_300, 0.32), (385_950, 0.35), (None, 0.37)],
        "hoh": [(17_500, 0.10), (66_650, 0.12), (106_150, 0.22), (202_700, 0.24),
                (257_300, 0.32), (643_300, 0.35), (None, 0.37)],
    },
}

TAX_TABLES = {2026: _2026, 2025: _2026}


def table_for(year):
    """The rate table for `year`, falling back to the newest one we hold.

    A year we have no figures for gets the closest we do rather than a crash,
    because a slightly stale bracket is a better answer than a broken page, and
    the page prints which year's figures it used.
    """
    if year in TAX_TABLES:
        return year, TAX_TABLES[year]
    newest = max(TAX_TABLES)
    return newest, TAX_TABLES[newest]


def bracket_tax(taxable, brackets):
    """Tax on `taxable`, and the per band working that produced it."""
    tax, lower, bands = 0.0, 0.0, []
    for upper, rate in brackets:
        if upper is None:
            amount = max(0.0, taxable - lower)
        else:
            amount = max(0.0, min(taxable, upper) - lower)
        if amount > 0:
            bands.append({"from": lower, "to": upper, "rate": rate, "amount": amount,
                          "tax": amount * rate})
            tax += amount * rate
        if upper is not None:
            lower = upper
        if upper is not None and taxable <= upper:
            break
    return tax, bands


def compute(profit, *, filing_status, your_wages, spouse_wages, other_income,
            federal_withheld, state_rate, year):
    """Everything owed on `profit`, with the working attached.

    The cost of the business is measured as the difference the business makes:
    tax with it, less tax on the wages alone. That is the only honest way to
    answer "what does this cost me" when profit stacks on top of a salary and
    can straddle a bracket, which is exactly what happens here.
    """
    year_used, table = table_for(year)
    status = filing_status if filing_status in table["brackets"] else "single"
    # Two different totals, and mixing them up is the classic joint-return
    # error. Brackets, the deduction and the additional medicare threshold are
    # all household figures. The social security wage base is not: it is a
    # per-person cap, and a spouse's salary does not use up yours.
    own_wages = max(0.0, your_wages)
    wages = own_wages + max(0.0, spouse_wages)
    other = max(0.0, other_income)
    profit = profit or 0.0

    # ── Self employment tax ──────────────────────────────────
    se_base = max(0.0, profit) * SE_BASE_FRACTION
    # Social security stops at the wage base, and this earner's own salary has
    # already used part of it. Counting a spouse's salary here too would close
    # the gap early and understate the bill — their wages are capped against
    # their own base, on their own return line.
    ss_room = max(0.0, table["ss_wage_base"] - own_wages)
    ss_taxable = min(se_base, ss_room)
    ss_tax = ss_taxable * SE_SOCIAL_SECURITY
    medicare_tax = se_base * SE_MEDICARE

    threshold = table["additional_medicare_threshold"][status]
    over = max(0.0, wages + se_base - threshold)
    extra_medicare = min(se_base, over) * ADDITIONAL_MEDICARE

    se_tax = ss_tax + medicare_tax + extra_medicare
    half_se = se_tax / 2.0

    # ── Income tax, with and without the business ────────────
    standard = table["standard_deduction"][status]
    brackets = table["brackets"][status]

    agi = wages + other + profit - half_se
    taxable_before_qbi = max(0.0, agi - standard)
    # 20% of business income, capped at 20% of taxable income. The
    # service-business phaseout is not modelled; it starts far above here.
    qbi = min(0.20 * max(0.0, profit - half_se), 0.20 * taxable_before_qbi)
    taxable = max(0.0, taxable_before_qbi - qbi)
    federal, bands = bracket_tax(taxable, brackets)

    agi_wages_only = wages + other
    taxable_wages_only = max(0.0, agi_wages_only - standard)
    federal_wages_only, _ = bracket_tax(taxable_wages_only, brackets)

    federal_on_business = max(0.0, federal - federal_wages_only)
    state_tax = max(0.0, profit) * (max(0.0, state_rate) / 100.0)
    business_tax = se_tax + federal_on_business + state_tax

    return {
        "year_used": year_used,
        "status": status,
        "status_label": FILING_LABELS.get(status, status),
        "wages": wages,
        "own_wages": own_wages,
        "other_income": other,
        "profit": profit,

        "se_base": se_base,
        "ss_room": ss_room,
        "ss_taxable": ss_taxable,
        "ss_tax": ss_tax,
        "medicare_tax": medicare_tax,
        "extra_medicare": extra_medicare,
        "se_tax": se_tax,
        "half_se": half_se,
        "ss_capped": ss_taxable < se_base,

        "standard_deduction": standard,
        "ss_wage_base": table["ss_wage_base"],
        "agi": agi,
        "qbi": qbi,
        "taxable": taxable,
        "bands": bands,
        "federal_total": federal,
        "federal_wages_only": federal_wages_only,
        "federal_on_business": federal_on_business,
        "state_tax": state_tax,

        "business_tax": business_tax,
        "effective_on_profit": (business_tax / profit * 100.0) if profit > 0 else 0.0,
        "marginal_rate": (bands[-1]["rate"] * 100.0) if bands else 0.0,

        "total_liability": federal + se_tax + state_tax,
        "federal_withheld": max(0.0, federal_withheld),
        # Negative means overpaid. Withholding covers federal income tax and,
        # for a wage earner, their half of SS and medicare already; what it
        # does not cover is SE tax, which is why this can be owed even when a
        # salary looks over-withheld.
        "balance_due": federal + se_tax - max(0.0, federal_withheld),
    }
