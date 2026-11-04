# What the board could know for itself

Audit of 2026-11-04. The goal it serves, in Michael's words: spend his time on
ideas and on orchestrating Claude sessions, with everything else automated,
"literally everything". Each item below is something he still has to notice,
type or keep track of by hand, where the truth already lives, and how the board
could read it with no model and no new cost. Anything that needs judgement is
marked for a Claude Code session on the Max plan (the Tend pattern), never for
an API key on the server.

Ranked by how much of his attention each one saves: how often it comes up,
times what it costs when it is missed. Sizes: **S** an afternoon, **M** a day
or two, **L** more.

Line numbers are as of commit `ff217ac`.

---

## The ranked list

### 1. One record of every nightly run, and one row when it breaks

- **By hand today:** nothing records that cost-sync ran at all. Each step of
  `sync_costs._sweep` (repo sweep, audit, store ids, Stripe books, bank feed,
  receipts, curator) only `print`s its failure to Railway's log
  (`sync_costs.py:87-139`), and the job exits non-zero only when EVERY vendor
  sync fails (`sync_costs.py:60`). The status that does exist is scattered over
  five pages: the Expenses page's `sync_error`, the bank review page, Books ->
  Connections, the business page and the provider rows. He finds a broken night
  by chance, usually days later, from a number that looks wrong.
- **Where the truth lives:** the job itself.
- **Free read:** a `NightRun` row per run with one result per step (ok, count,
  error text), written as each step finishes. Needs attention gets ONE row when
  any step failed, or when there has been no run for 26 hours. Every item
  below that runs nightly then reports through the same row.
- **Size:** S. **Attention:** every time something breaks, and today it is
  silent. Everything else on this list leans on it, which is why it is first.

### 2. Bank review: suggest without the paid API, and finish the list on the Max plan

- **By hand today:** every bank line no `VendorRule` covers waits on
  `/admin/bank/` for him to settle. This is the main recurring chore. Worse,
  `bank_feed.main` calls the PAID Anthropic API every night whenever
  `ANTHROPIC_API_KEY` is set on cost-sync (`bank_feed.py:797`, `suggest` at
  `bank_feed.py:742`). That key was put there for the curator, which now has
  its own `CURATOR_ENABLED` gate. The bank suggestion has no gate, so it is
  paid spend he did not ask for.
- **Where the truth lives:** data the board already holds: lines he settled
  before without "remember" (`decided_at` set, `rule_id` null), a receipt in
  the mailbox for the same amount within days (it names the vendor), Mercury's
  `merchant_category` (`bank_feed.py:493`), and ServiceProvider and playbook
  vendor names.
- **Free read:** a deterministic suggester in that order (past decision on the
  same counterparty, matching receipt, merchant category to expense category).
  What is left goes through a new door route (`/api/guidance/bank/review` plus
  a decide POST) to a Tend-style skill run in a Claude Code session, which
  settles lines and writes the rules. Gate the nightly `suggest()` behind an
  explicit switch like the curator's, off by default.
- **Size:** M. **Attention:** weekly at least; the paid call costs money every
  night it finds something.

### 3. Time logs itself from the sessions and the commits

- **By hand today:** every `TimeEntry` is typed on `/admin/time/new`, run on
  the timer (`app.py:3461`, `app.py:3553`), or estimated from memory by a
  session calling `log_time`. The Stop hook only nags when commits landed and
  no time was logged (`tools/hooks/stop.py:97`); the session still guesses the
  hours.
- **Where the truth lives:** every Claude Code transcript under
  `~/.claude/projects/<folder>/*.jsonl` has a timestamp on every line, and the
  folder name is the repo's path. Commit times on every repo over the
  `GITHUB_TOKEN` the sweep already uses.
- **Free read:** a SessionEnd hook (installed by `tools/hooks/install.py` like
  the others) that adds up the gaps of 15 minutes or less in the session it
  just ended, maps the folder to `Project.repo` or a tile's `github_url`, and
  posts to `/api/guidance/time` keyed on the session id, so a re-run corrects
  rather than adds. The rate type follows the project's phase (build before
  go-live, maintenance after). Projects of his own are skipped, per the rule
  "Never log time against your own products".
- **Size:** M. **Attention:** daily, and the hours drive every margin and
  every maintenance invoice.

### 4. Nothing waits for a page to be opened

- **By hand today:** three things only refresh when he looks at them.
  - Mail syncs only when Needs attention or Messages is opened
    (`mail_service.kick`, `pm/attention_routes.py:156`,
    `pm/messages_routes.py:44`), so the sidebar badge is stale until then.
  - Signature status only refreshes when the Contracts list or a contract page
    is opened (`refresh_open_requests`, `pm/contract_routes.py:363`, `:389`).
    He learns somebody signed by going to look.
  - Store versions only refresh on the way into My Apps
    (`pm/apps_routes.py:92`), and "Versions differ" never reaches Needs
    attention.
- **Where the truth lives:** Gmail over IMAP, the SignaDoc portal, the public
  store pages, all already read.
- **Free read:** a background thread for mail every five minutes and for
  signatures every fifteen, the same pattern as the hub reply sender
  (`app.py:2397`). Store versions join the nightly run, and a "differ" lasting
  more than a day becomes a Needs attention row.
- **Size:** S. **Attention:** daily.

### 5. A payment moves the client, and a Stripe invoice finds its client

- **By hand today:**
  - **Bug:** paying is meant to move a client to Active client
    (`_mark_client_active`, `stripe_service.py:250`), but its only caller is
    `sync_invoice_from_stripe` (`stripe_service.py:243`), which runs only when
    somebody presses Sync on one invoice. The webhook
    (`process_invoice_event`, `stripe_service.py:1178`) and the six-hourly
    importer (`import_invoices_from_stripe`, `stripe_service.py:669`) never
    call it. So the stage is still moved by hand.
  - Invoices whose Stripe customer matches no client are only printed
    (`stripe_service.py:731`, `sync_costs.py:73`); `Client.stripe_customer_id`
    is typed on the client form to fix it.
  - `create_stripe_customer` (`stripe_service.py:35`) and "Sync all clients"
    (`pm/stripe_routes.py:680`) always make a NEW Stripe customer without
    looking for one by email first, which makes more orphans.
  - Imported invoices never get a `project_id` (`stripe_service.py:699`).
- **Where the truth lives:** Stripe: the customer's email and
  `metadata.pm_client_id`, the invoice's own metadata.
- **Free read:** call `_mark_client_active` from the webhook and the importer.
  Match an orphan by `metadata.pm_client_id`, then by email, filling only an
  empty id. Look up by email before creating a customer. Give an imported
  invoice its project when the client has exactly one (the rule sales tax
  already uses).
- **Size:** S. **Attention:** every payment and every new client.

### 6. A signed contract does what it says, and an unsigned one takes nothing

- **By hand today:** the SOW writes stage, budget, MVP date and hosting fee
  when it is SENT (`app.py:3331`, `app.py:3382`), and a hosting agreement
  writes its fee when sent (`pm/contract_routes.py:973`). On signing,
  `_apply` only files the PDF (`pm/contract_routes.py:237-262`). On a decline
  or a void nothing takes those values back, so the board can hold a fee and a
  stage nobody agreed to. The package (`MvpPackage.status`,
  `pm/mvp_routes.py:464`), the product sales (`ProductSale`, typed in the sell
  modal, `pm/products_routes.py:290`) and the lead's stage are all moved by
  hand afterwards.
- **Where the truth lives:** SignaDoc's envelope status, already read, and the
  form the contract was built from (`SignatureRequest.form_json`).
- **Free read:** keep the proposed values on the request and apply them on
  `completed`: client to contracted, package to contracted, the package's
  product items written as `ProductSale` rows, the linked lead moved. On
  `declined` or `voided`, put back what was there.
- **Size:** M. **Attention:** every deal, and it is a quiet source of wrong
  margins.

### 7. Railway projects map themselves to board projects

- **By hand today:** every `ServiceMapping` (Railway project to board project)
  is typed on `/admin/service-costs/mappings/new`
  (`pm/service_costs_routes.py:476-531`), or "Automap" is pressed and matches
  exact names only (`pm/service_costs_routes.py:735-775`). Anything unmapped
  books as a no-mapping row. `AppLink.railway_url` is typed on the tile form
  (`pm/apps_routes.py:191`). A build that is live on Railway with no tile is
  noticed only if a session remembered `register_app`.
  - Worse, a priced project with no mapping reads **"Fine - No cost
    recorded"** on Hosting (`pm/hosting_routes.py:283`), so it sits out of the
    raise badge and shows a full margin.
- **Where the truth lives:** one Railway GraphQL query with the account token
  the board already holds (`PM_RAILWAY_ACCOUNT_TOKEN`): each service's
  `source.repo`, its custom and service domains, and its latest deployment.
  The board already has `AppLink.url`, `AppLink.github_url` and `Project.repo`.
- **Free read:** nightly, Railway project -> repo or domain -> tile or project.
  Write the mapping and `railway_url` only on a single unambiguous match, only
  into empty fields. List "live on Railway, not on My Apps" as one Needs
  attention row. Make "Not mapped" its own band on Hosting and count it in the
  badge.
- **Size:** M (the Hosting band alone is S). **Attention:** every new build,
  and silent until then.

### 8. One deadline list, read from the state

- **By hand today:** nothing on the board knows the Texas franchise tax report
  and Public Information Report are due May 15 (no code mentions it). Sales
  tax returns that are due or late show only on the business page and the
  returns page; `attention_counts` (`pm/attention_routes.py:136-148`) has no
  tax row. Federal dates are missing too: EntertainHQ's Form 1065 and K-1s
  (March 15, it has three `BusinessOwner` rows), Michael's 1040 and Schedule C
  (April 15). The estimated-payment dates at `pm/tax_routes.py:26-36` do not
  roll off weekends the way `sales_tax.due_date` does. A DBA's assumed name
  certificate (Data Dungeon, Personal Training) runs up to ten years and has no
  date anywhere. And `texas_taxpayer_number`, `sos_file_number` and
  `formed_on` are typed (`pm/business_routes.py:570-580`).
- **Where the truth lives:** the Comptroller's franchise tax search answers
  JSON with no key, by taxpayer number:
  `https://comptroller.texas.gov/data-search/franchise-tax/<number>`. Checked
  live on 2026-11-04: `rightToTransactTX` (ACTIVE or FORFEITED), the SOS file
  number, the SOS registration date, the registered agent and office, the EIN,
  and `reportYear`, the last report on file (Built by Bean's reads 2026;
  EntertainHQ's is empty, its first is due 2027-05-15).
- **Free read:** a nightly fetch per business that fills the empty fields,
  stores the agent and office and flags any change, and marks this year's
  report filed once `reportYear` catches up. One deadline list (sales tax by
  period, franchise and PIR, 1065, 1040, estimates, DBA renewals), each
  becoming a Needs attention row ten days out or when late, and a loud row if
  standing ever leaves ACTIVE. Estimates are marked paid when an IRS line shows
  up in the bank or a statement.
- **Size:** S to M. **Attention:** quarterly and yearly, but a missed franchise
  report forfeits the company's right to do business, and a missed sales tax
  return draws an estimated bill at about three times the real tax.

### 9. Watch what is live: sites, certificates, domains, deploys

- **By hand today:** nothing checks that a tile's URL still answers, that its
  certificate is current, or that a deploy succeeded. CLAUDE.md tells sessions
  to run `railway deployment list` by hand. Domain expiry is FETCHED and
  thrown away: `_cloudflare_registrar_domains` reads `expires_at` and
  `auto_renew` for every Cloudflare domain (`service_costs_service.py:853-880`)
  and uses them only to date-match a charge. Today a client finds an outage
  first.
- **Where the truth lives:** HTTP and TLS themselves; Cloudflare's registrar
  response; public RDAP (`rdap.org/domain/<name>`) for domains held elsewhere;
  Railway's `latestDeployment { status meta }` (commit SHA) against the
  branch head on GitHub.
- **Free read:** nightly, GET each tile's URL and store status, final URL and
  certificate `notAfter`, with a "down since" date. Store each domain's expiry
  and auto-renew. Needs attention rows for: down two nights running, a
  certificate under 14 days, a domain under 30 days with auto-renew off or held
  outside Cloudflare, a latest deploy FAILED or CRASHED, a deployed commit more
  than a day behind the branch.
- **Size:** S to M. **Attention:** rare, but each miss is an outage a client
  sees.

### 10. The hosting fee agreed is the hosting fee billed

- **By hand today:** `Project.hosting_fee` comes from the contract. Nothing
  compares it with what Stripe actually charges. A signed fee update never
  changes the subscription, and a project with an agreed fee and no
  subscription at all is agreed money never billed.
- **Where the truth lives:** Stripe subscriptions, already read by
  `get_subscriptions_for_tax` and `_recurring_plan` (`stripe_service.py:347`,
  `:987`): each item's `price.unit_amount` and `recurring.interval`.
- **Free read:** on each hosting row, "billed $X, agreed $Y" when they differ,
  and a row in the Hosting badge for a priced project whose client has no
  hosting subscription. Offer the subscription change as one press, the same
  way "Tax the subscription" asks first.
- **Size:** S to M. **Attention:** monthly, and it is lost revenue.

### 11. A project's phase and dates come from its repo and its domain

- **By hand today:** Contracted -> MVP is manual by design
  (`MANUAL_ONLY`, `project_phases.py:37`: "nothing in the data says started").
  `go_live_date` is typed (`forms.py:167`), and it starts the free-maintenance
  clock, so a missed one turns billable hours into free ones. `Project.repo`
  (`forms.py:175`) and `AppLink.github_url` (`pm/apps_routes.py:192`) are two
  fields for one fact; the only screen that linked them was Cerebro, now
  retired. The nightly store-id read skips any tile without `github_url`
  (`store_ids_service.py:111`).
- **Where the truth lives:** GitHub: the first commit on the repo after the
  contract date. Item 9's first nightly 200 on the custom domain, the earliest
  `register_app` for the project, or the first successful production deploy.
  The other half of each repo pair, joined through `AppLink.project_id`, and a
  repo's `homepage` field against a tile's host.
- **Free read:** nightly, fill whichever repo field is empty from the other,
  then from `homepage`. Move Contracted -> MVP on the first commit after the
  contract date. Propose `go_live_date` from the first answer on the domain.
  All only into empty fields and never past `phase_locked`.
- **Size:** S. **Attention:** once per project, but every later margin hangs
  on it.

### 12. The sales tax return records itself from the payment

- **By hand today:** recording a filed return is typed off WebFile's
  confirmation page (`pm/business_routes.py:826-887`): filed date, amount
  paid, card fee, penalty, interest and three reference numbers. The
  confirmation PDF is uploaded by hand (`pm/business_routes.py:787`).
  `BusinessLocation` rows (WebFile location number, address, county, opened
  on) and `naics_code`, `sales_tax_registered_on` and `sales_tax_first_sale`
  are typed from the permit (`pm/business_routes.py:579-585`, `:648-662`).
  **Silent hole:** with `sales_tax_first_sale` blank, `periods_owed` returns
  nothing (`sales_tax.py:382-383`), so no return ever reads as owed.
- **Where the truth lives:** the Comptroller charge, which already arrives as a
  bank line and is already recognised (`STATE_TAX_PAYMENT`,
  `books_service.py:270`). The open dataset `jrea-zgmq`, which
  `import_leads.py` already reads, has a row per outlet with `outlet_number`
  (the WebFile location number, padded to five), address, county, NAICS,
  permit issue date, first sale date and the city-limits flag. Possibly
  WebFile or eSystems confirmation mail in Gmail (worth one search first).
- **Free read:** a Comptroller charge with no `SalesTaxFiling` in its window
  drafts the filing for the period just closed (date from the bank, amount
  from the computed tax, card fee and penalty split from
  `charges_if_paid_on`), leaving only the reference number, or nothing if the
  confirmation mail can be parsed. Fill locations and first-sale date from
  `jrea-zgmq` into empty fields, and flag an outlet that drops off the list.
- **Check first:** Built by Bean's taxpayer number 32093304155 returned NO
  rows from `jrea-zgmq` on 2026-11-04, while EntertainHQ's outlet is there.
  Either the number on file is not the one the permit is under, or the permit
  is not active. Worth Michael confirming before any of this is built on it.
- **Size:** S to M. **Attention:** quarterly.

### 13. Card statements ask for themselves and reconcile

- **By hand today:** three Chase CSVs (Built by Bean's debit, his personal
  debit and his personal credit card) are downloaded and uploaded each month
  (`pm/books_routes.py:450`, `statements.py`). Nothing says one is due; the
  connections tab only shows how far each reaches. Statement accounts are
  never balanced, so a partial upload is invisible at the monthly close
  (`bank_check`, `books_service.py:405`, covers Mercury only).
- **Where the truth lives:** Chase has no free API, but it emails "your
  statement is ready" and, if turned on, a per-transaction alert at a $0
  threshold, into the Gmail the receipt reader already opens. Chase checking's
  CSV carries a Balance column.
- **Free read:** a Needs attention row when a statement source has nothing
  past last month's end, or nothing past the latest "statement ready" mail.
  Store the last balance on upload and feed it to `bank_check`. Later, parse
  the alert emails into provisional lines that the CSV folds over by date and
  amount, which leaves the upload as a check rather than the source.
- **Size:** S for the reminder and balance, M for the alert mail.
  **Attention:** monthly.

### 14. The month closes itself when it is clean

- **By hand today:** `close_month` (`pm/books_routes.py:171`) is pressed per
  company per month, and nothing says a finished month is still open.
- **Where the truth lives:** `month_status` already counts unsorted lines and
  missing receipts, and `bank_check` says whether each account agrees.
- **Free read:** nightly, close a finished month once nothing is unsorted, no
  receipt over $75 is missing and every account agrees. Otherwise one row:
  "October will not close: 3 unsorted, 1 receipt".
- **Size:** S. **Attention:** monthly.

### 15. Vendor amounts and covered charges follow the bank

- **By hand today:**
  - Claude's subscription is a "flat" provider with `monthly_cost` and
    `billing_day` typed (`pm/service_costs_routes.py:226`, `_sync_flat` at
    `service_costs_service.py:337`). A plan change books the wrong amount and
    the real charge then falls to review.
  - Only Railway, Cloudflare, Anthropic and Claude carry a "covered" rule. Any
    Twilio or AWS line lands in review, and settling it as an expense counts it
    twice against the usage sync. A covered rule would not save Twilio either:
    a $20 prepaid top-up never equals a month of usage, so `booked_by_sync`
    (`bank_feed.py:220`) misses. Latent while no Twilio or AWS provider is
    Built by Bean's own, live the moment one is.
  - Recurring expenses spawn children at a fixed amount (`app.py:504`) that the
    bank feed already books; `adopt` only catches an exact cent within -7/+3
    days, so a price change leaves a duplicate.
- **Where the truth lives:** the settled bank line, and the vendor's receipt
  mail already in the mailbox.
- **Free read:** set a flat provider's amount and day from its last settled
  line, or retire flat providers and make it an expense rule. Treat a prepaid
  vendor's bank line as the expense and its usage rows as the split only. End
  a recurring parent whose vendor has a rule, and flag any child no bank line
  adopted within ten days.
- **Size:** S each. **Attention:** monthly, and each one risks a silent double
  count.

### 16. Email counts as contact, and leads hear their replies

- **By hand today:** `ClientContact` rows are typed (`app.py:1160-1182`), and
  "days since contact" reads only those. A client's email reply moves nothing.
  `match_client` (`pm/mail_service.py:104`) matches one address per client, so
  a colleague's never links. A contact form enquiry writes a `Message` and
  nothing else (`record_contact`, `pm/mail_service.py:364`). Lead emails are
  not in `watched_senders` (`pm/mail_service.py:87-101`), so a lead replying to
  Hannah is never seen. A converted lead is pinned at In conversation for good
  (`pm/leads_routes.py:375`) while its client moves on.
- **Where the truth lives:** `Message` rows already linked to clients; Gmail's
  Sent folder (not read today); lead and lead-person emails.
- **Free read:** count `Message` in last contact; move contacted -> in
  conversation on a reply; match on the client's domain as well as the
  address; watch lead emails and log a reply as a touch; have a form enquiry
  create or link a lead; show the client's stage on a converted lead.
- **Size:** S to M. **Attention:** weekly, mostly Hannah's.

### 17. The lead list refreshes itself

- **By hand today:** `import_leads.py`, then `check_websites.py`, then
  `enrich_sites.py` are run by hand (`check_websites.py:16`). Nothing
  schedules them, so the "Started in the last 12 months" call list, which is
  the page's reason to exist, ages silently.
- **Where the truth lives:** the Comptroller permit file (`jrea-zgmq`), TDLR,
  FMCSA and the rest, all public and already read by the script.
- **Free read:** a weekly step on cost-sync that runs the import and then the
  website check and enrichment on new rows only. Check runtime and memory on
  that service first; DuckDB for Overture is already optional.
- **Size:** S to M. **Attention:** monthly, as a list that quietly stops
  growing.

### 18. The business map notices what the repos and the books say

- **By hand today:** map surfaces are typed one by one with their URLs
  (`_fill_node`, `pm/business_routes.py:1351`); node status is typed
  (`:1375-1378`); a vendor added in a repo reaches the map only when Tend is
  run (`.claude/skills/tend/SKILL.md:81-88`).
- **Where the truth lives:** each blueprint's repos, whose tarballs
  `audit_repos.py` already downloads nightly (dependencies like `twilio`,
  `stripe`, `resend`, `@sentry/*`; env names like `TWILIO_`, `SENTRY_DSN`).
  Railway's custom domains per service and its env var NAMES (keys only).
  The company's own expenses by vendor (`Expense.business_id`, `VendorRule`).
  HTTP for each surface's URL.
- **Free read:** give `Playbook` a presence signature (the
  `Product.presence_pattern` mechanism, `models.py:3058`, reused) and file a
  gap when a repo uses a vendor its map lacks. Add a missing surface from a
  Railway domain. Flag a vendor on the books but not the map, and a service
  node with no charge in 90 days. Set surface status live or unreachable from
  item 9's probe. Outcome status stays Tend's.
- **Size:** M. **Attention:** each vendor or surface added, roughly weekly
  across the repos.

### 19. A tile says what is in the repo against what is in the stores

- **By hand today:** whether a phone build is waiting on submission or review
  is remembered, not shown.
- **Where the truth lives:** the files `store_ids_service` already pulls:
  `versionName` in `app/build.gradle`, `MARKETING_VERSION` in
  `project.pbxproj`, `expo.version` in `app.json`.
- **Free read:** extend `ids_from_files` to read the version, and the tile
  says "1.4.0 in the repo, stores on 1.3.2".
- **Size:** S. **Attention:** weekly during a release.

### 20. Playbook steps tick themselves when the evidence is checkable

- **By hand today:** every `ProjectPlaybookStep.done` is a press
  (`app.py:1407-1449`), including steps a machine can see: `preDeployCommand`
  and `healthcheckPath` in `railway.json`, a custom domain with its DNS and
  certificate, a deploy from the expected commit.
- **Where the truth lives:** the repo (GitHub contents API) and Railway.
- **Free read:** an optional `check` on a playbook step, like a rule's
  `check_pattern`, run nightly; a pass ticks the step, nothing ever unticks
  one.
- **Size:** M. **Attention:** weekly while a build is running.

---

## Smaller ones

- **Tile description and icon go stale.** `AppLink.description` is typed and
  icons are fetched once on save (`pm/apps_routes.py:190`, `:213`). Fill an
  empty description from the repo's `description` or the site's meta, and
  re-fetch found icons monthly (never uploaded ones). S, rare.
- **Prepaid API usage has no split.** The Anthropic and OpenAI APIs report cost
  by workspace or project through their admin cost endpoints for free; GitHub
  has a billing usage endpoint. A usage-only sync that writes cost entries and
  no expense (the bank line stays the expense) would split them by client.
  M each, monthly, only if the split matters.
- **A receipt with no bank line means a card the board cannot see.** A known
  vendor's receipt over a threshold with no bank line within five days on any
  connection could be one Needs attention row. S, monthly.
- **Local sales tax rate is a typed guess** (`BusinessLocation.local_rate`
  defaults to 2.0, `models.py:1972`). The Comptroller publishes local rate
  files each quarter. S to M, rarely changes.
- **Partner Railway bills from the mailbox.** Where an account has no token, a
  Railway invoice email in the receipt mailbox could write its
  `ProviderInvoice` with a "From mail" note. S, monthly.

## Correctness faults found along the way

These are not automation, but they came up and each one is a wrong number or a
missed step today.

1. **Paying never moves a client to Active client** except through a manual
   Sync press (item 5).
2. **The nightly bank suggestion calls the paid API** whenever the key is on
   cost-sync, with no switch (item 2).
3. **"No cost recorded" reads Fine on Hosting** (item 7).
4. **A blank `sales_tax_first_sale` hides every owed return** (item 12).
5. **`sales_tax_frequency` is offered and ignored.** The form takes monthly,
   quarterly or yearly (`models.py:1780`, `pm/business_routes.py:581`), but
   `periods_owed`, `due_date` and `quarter_bounds` are quarterly only
   (`sales_tax.py:318-390`). A company moved to monthly gets the wrong periods.
6. **`create_stripe_customer` makes duplicates** rather than finding one by
   email (item 5).
7. **`sync_costs.main` returns early when no vendor is active**
   (`sync_costs.py:45`), which skips the nightly Stripe invoice import.
8. **The door's `get_costs` reports Railway (EntertainHQ) October as not
   recorded** while Needs attention correctly graces it (its October runs to
   November 16). The two should share one test.
9. **Built by Bean's permit is not in the state's active permit list** under
   the taxpayer number on file (item 12). Worth a look by Michael.

## Already automated (do not propose again)

- Store ids read from repos nightly; store versions read from the public pages.
- Railway bills and the per-project split, from the account token.
- Cloudflare billing and registrar charges; Twilio monthly usage and account
  label; Stripe fees; each company's own Stripe books.
- Mercury nightly with a ten-day re-read, fold duplicates, adopt, rule cascade.
- Receipts: the mailbox sweep, the expense-first hunt, statement-line proof
  under $75, the 45-day set-aside, nightly rematch, sales tax settled on the
  charge, filings attached as receipts.
- Statement uploads classify and store nothing twice.
- Sales tax due dates with weekend and holiday roll, the per-location return,
  the penalty estimate, sales and tax prefilled on the record form.
- Project phases Delivered -> Free maintenance -> In production from dates.
- The SOW writes the project, its playbooks, budget, MVP date and fee.
- Hosting fee raise drafts and the badge.
- Hub tickets pulled daily and replies pushed every minute; Stripe invoices
  imported every six hours.
- Repo sweep and rule audit nightly; Tend on the Max plan for rules,
  blueprints, maps and gaps.

## Where to start

Items 1, 4 and 5 are each an afternoon and remove a daily or per-payment
chore; 1 is also what makes every later nightly step visible. Then 2 (the
biggest recurring chore, and it stops a paid call), then the single Railway
query that serves 7, 9 and 11 together, then the Comptroller fetch that serves
8 and 12.

---

## Michael's decisions, 2026-11-04

Every item above was walked through with him one by one. **Build all of them as
written**, with these changes:

- **1. Night run record:** built (`night_log.py`, commit fd2131e). Every new
  nightly step goes through `night.step(...)` in `sync_costs._sweep`, and any
  Needs attention row follows the pattern in `pm/attention_routes.py`.
- **2. Bank:** the paid nightly call is already off (`BANK_SUGGEST_NIGHTLY`).
  Build both parts: the free suggester and a `/bank` Claude Code skill on the
  Max plan for what is left. No paid API.
- **14. Month close:** a month closes only when EVERY receipt is in, not only
  those over $75.
- **17. Leads:** keep the page active and build the weekly refresh.
- **Smaller ones:** all four are approved.
- **Faults:** fix all of them. Fault 2 is already fixed. Fault 9 (Built by
  Bean's permit missing from the state list) is Michael's to check with the
  Comptroller; build item 12 regardless.

Added the same day:

- **Pages fill the screen** (done, commit 9eddebb; house rule in CLAUDE.md).
- **Sidebar order** (done): Businesses, Notes, Clients, Leads, Projects, Client
  support, Contracts, MVP Builder, Products, My Apps, Handbook, Time. Best
  Practices is called the **Handbook** on screen; Tickets is **Client support**.
- **Products folds into the MVP Builder** as a Price list tab; its sidebar link
  goes. Best Practices holds no prices.
- **Client support** (the Tickets board) is overhauled into one support board
  across all his businesses. It talks properly to each app's own support system
  (EntertainHQ's admin support board, Data Dungeon's, and the client apps on
  the hub), shows client satisfaction at a glance, and has quick links to each
  app's own portal.
- **Clients page cleanup:** remove what he does not use and what does not talk
  to the rest of the board, and make it friendlier. Ask him about each feature
  before removing it.
- **Workspace** replaces Notes and Projects: EntertainHQ's workspace (messages,
  tasks, projects), built into this board. It sits second in the sidebar, right
  under Needs attention, and the standalone Projects page folds into it.

## Who builds what

Each session owns its files. The paths are the hand-off: two sessions never
edit the same module on purpose.

| Session | Items |
|---|---|
| Money in: Stripe, mail, leads | 4 (mail every 5 min), 5, 17, fault 8 |
| Bank and books | 2, 13, 14, 15, receipt with no bank line |
| Deals: contracts, MVP Builder, time | 3, 6, 4 (signatures every 15 min), Products into the MVP Builder |
| Railway, hosting and live apps | 7 (with the Not mapped band), 9, 10, 18, 19, 20, 4 (store versions nightly), tile text and icons, Railway bills from email |
| Tax and deadlines | 8, 12, local tax rates, faults 4 and 5 |
| Client support | the Tickets overhaul |
| Clients | the Clients page cleanup, and item 16 |
| Workspace | the Workspace (replaces Notes and Projects), and item 11 |
