# Finances, consolidated

Michael, 2026-11-04: "I feel like the finances section as a whole could use
some better processes top to bottom. maybe some page consolidation likely some
feature creep cleanup." An inventory of the six pages (Dashboard, Taxes,
Expenses, Books, Hosting, Invoices) found the same figures computed in up to
four places over different periods. Michael decided each piece below.

## What changes

1. **The Dashboard retires, and Books takes its spot.** Michael, the same
   evening, after the Overview shipped: "Dashboard (retire move books into
   this spot)". What the Overview held is the top of each company's Books
   (the Months tab), so nothing it showed is lost, and `/admin/finances`
   redirects to Books:
   - A company switcher and a year picker.
   - Income, Expenses, Net and the year's estimated tax, read from
     `books_service.summarize` and the Taxes calculation. That fixes the
     all-time profit run through this year's brackets, which disagreed with
     Books and Taxes.
   - One To do list: overdue and stalled invoices, bank lines to sort, missing
     receipts, missing vendor bills, and hosting fees under the floor. Months
     not yet closed are the list right under it, each with what is left.
   - Financials by client moves to the Clients page. Ticket and delivery
     deadlines move to Client support.
   - `sync_project_phases()` stops running on a GET.

2. **Books is the one place for each company's money.**
   - One tab per company, each with sub-tabs: Months and close, Bank (the
     review list moves in), Expenses (that company's ledger and breakdown),
     Receipts (that company's), Year report, and Connections.
   - Connections gathers what is spread over four places today: Mercury, the
     company Stripe key, card statements, receipt mailboxes and vendor
     providers.
   - Expenses leaves the sidebar, and its old URLs redirect.

3. **Invoices slims down.**
   - The list, New invoice, and a thin Stripe balance strip.
   - Setup Products and Sync All Clients go.
   - The two different "Outstanding" figures get different names.
   - The hidden Unbilled code comes back as "Time not yet billed", because
     time now logs itself from sessions.
   - Fix the stale "currently none" comments, and make invoice detail
     reachable from the list.

4. **Taxes.**
   - The same five tabs on every tax page: Income tax, Sales tax, Returns,
     Deadlines, Guide.
   - Income tax per company: Built by Bean on Schedule C, and EntertainHQ as
     a partnership showing each member's share, with no self-employment tax
     at the company.
   - Set aside on the same basis as the estimate, not Stripe payouts.
   - Stale wording goes.

5. **Only the bank line ever makes an expense.**
   - The vendor syncs (Railway, Cloudflare, Claude and the rest) stop writing
     Expenses. Their reports only split a bank-booked charge across projects
     and clients.
   - The `covered` disposition becomes "split by the vendor's report".
   - Write a migration that carries existing vendor-written expenses over
     without double counting or losing a project split. Prove it on a copy of
     production figures: `tools/test_one_set_of_figures.py` and the Books
     totals must not move by a cent unless a real double count is removed,
     and if one is, list it.

6. **Recurring expenses retire.** The toggle goes and existing recurring
   parents end. Past expenses stay. Anything one of them caught is caught by
   a bank rule.

7. **Adding an expense by hand stays,** inside each company's Books with a
   company picker, for cash or a card the board cannot see. Michael's words:
   "put it back in then whatever you need to automate things".

8. **A session's `log_expense` becomes a tag.** It no longer makes an
   expense. It leaves a note (amount, vendor, client, project, date) that the
   bank line takes when it arrives, so the charge lands on the right project
   with nothing typed. A tag no line has taken in 10 days is one Needs
   attention row.

9. **Hosting takes in the vendor mappings and Railway's monthly correction
   pages.** Stale wording ("Railway's API reports no money", "vendor has no
   billing API") goes.

10. **CEO only.** Every Finances page is CEO only, like Books and Businesses.
    Hannah keeps her work pages.

11. **The sidebar:** Finances is Books, Taxes, Invoicing, Hosting, in that
    order (Michael's second pass, 2026-11-04: "Dashboard (retire move books
    into this spot) / Expenses (... retired too since we track all expense in
    the books) / then the taxes / Invoicing / Hosting"). Invoices is called
    Invoicing. A divider and no heading, like his other groups.

## Small fixes found on the way

- The Expenses "Total out" caption ignores the business filter.
- The legacy redirects `stripe_dashboard` and `service_costs_dashboard` go
  once nothing links to them.
- The missing-vendor-bill check exists twice (`months_missing_manual_costs`
  and `provider_bills.bill_months`). Keep one.

## Timing

This waits until the Bank and books, Tax and deadlines, and Railway sessions
have pushed their audit fixes, because they are on these same pages.
