---
name: bank
description: Settle the Built by Bean board's bank review list - every bank line no rule has sorted yet, across every company, card and account - and write the rules so the same vendor never asks again. Use when Michael says "bank", "run bank", "sort the bank", "clear the bank review", or asks for the bank lines to be settled. Runs on his Claude plan, never the paid API.
---

# Bank

Michael, 2026-11-04: everything automated, and nothing on the server calls a
paid model. Every night the board settles what its rules know and suggests
what it can work out for itself (`bank_review.py`: lines settled by hand
before, a receipt for the same amount, a vendor it already pays, the bank's
merchant category). What is left needs judgement, and this run is that
judgement, done by you in this session on his plan.

Everything goes through the board's door with the pm-guidance tools. Never
edit the board's database any other way, and never move money, contact a
vendor or a client, or touch a bank.

## Before you start

1. You need `bank_review` and `bank_decide` among the pm-guidance tools. If
   they are missing, say so and stop: the bridge in `tools/pm_guidance_mcp.py`
   gains them in a session started after the repo was pulled.
2. Call `bank_review`. Tell Michael in one line how many lines are waiting,
   then work without asking. He reads the result, not the plan.

## How to judge a line

The companies, their owners, the categories, the projects, every rule and the
lines settled by hand recently are all in the review. Use them.

- **expense**: a cost of one company. Its `business_id` is the company whose
  cost it is, which is usually the company whose account paid. A charge for
  EntertainHQ's own services (its Railway, its Claude plan, its domains)
  paid by Built by Bean is EntertainHQ's. Pick the category the tax return
  would want (software, hosting, ai_services, domain, meals, travel, ...).
  Name a project only when the line plainly belongs to one.
- **personal**: not the business's money at all. On an owner's personal card
  (the account says PERSONAL CARD) a restaurant, fuel, groceries, a shop,
  travel or entertainment is personal unless a rule, a receipt or the
  history says the business bought it.
- **transfer**: money between accounts the same people own: paying a card
  off, moving money between a company's own accounts, Zelle to himself, and
  on a personal account the other half of a contribution or a draw.
- **contribution / draw**: an owner putting money into a company or taking
  it out, on the company's side. `owner_name` is the owner from the review.
- **income**: money a customer paid. Never on a personal account, and never
  a Stripe payout (the board already counts the sale).

## Settling

1. Accept the board's suggestion where it is right; fix it where it is not.
2. Give a `pattern` with `keep: true` whenever the vendor will charge again:
   the shortest stable words of the counterparty, on every future charge and
   no other vendor's ("GITHUB", "GOOGLE WORKSPACE", never a store number or a
   date). The `pattern_hint` is a start. With a pattern, every waiting line
   like it is settled too. A one-off (a restaurant, a single purchase) gets
   no pattern and `keep: false`.
3. Never write a pattern so broad it would catch another vendor ("GOOGLE"
   alone catches Workspace, Play and Ads, which are different things).
4. Leave a line waiting when you cannot tell. A wrong answer moves money
   between companies or into the books; a waiting one costs nothing.
5. Send decisions in batches of up to 50 with `bank_decide`, then call
   `bank_review` again: rules written by one batch settle lines in the next.

## Finish

Tell Michael, in a few plain lines: how many lines you settled, the rules you
wrote, and the lines you left waiting with why (what you would need to know).
If a line looks like a charge he did not expect, a duplicate, or a vendor he
may have stopped using, say so. No em dashes, anywhere.
