---
name: legal
description: Keep the Legal library on the Built by Bean board current - re-check every law's official source for changes, read the ones that moved against their copies, update the entries, and look for new laws that touch the products. Use when Michael says "legal check", "re-check the law", "run legal", or asks whether anything in the law has changed. Runs on his Claude plan, never the paid API, and nothing it writes is legal advice.
---

# Legal

Michael, 2026-11-07: "best practices make our app function well, legal keeps us
not in jail or sued"; buttoned up as much as we can without a lawyer, and kept
apart from Best Practices because it needs extra care. The library at
builtbybeans.com/admin/legal holds, for every decision a product made that the
law touches, the law behind it with a proof copy, what it requires, the decision
and where it is recorded, its status, the apps and functions it touches, and
when it was last checked. "Eventually we will put it on an overnight job along
with that best practice checks and gaps check; for now it will just [be] done
periodically via usage from the plans." This run is that job, done by you in
this session.

Everything goes through the board's door with the pm-guidance tools
(`get_legal`, `file_legal`, `legal_recheck`). Never edit the board's database
any other way. Nothing you write is legal advice; where only a lawyer can settle
a point, say so on the entry (status `lawyer`, a `lawyer_question`) and leave it
on the lawyer list (EntertainHQ issue #311).

## 1. Re-check the sources

1. `legal_recheck` with no sources: the board fetches every official document
   again and compares it with its copy. Wait for the run (it polls); report the
   counts in one line.
2. For each source it says CHANGED: open the source's URL and the board's copy
   (Legal, Sources, "the board's copy") and read what changed. A change of page
   chrome is nothing; a change of words is something. For each entry that cites
   it, decide whether the decision still stands, and update the entry through
   `file_legal` (the product's register in `docs/legal/library/entries.json` is
   the source of truth for EntertainHQ: change it there, re-run
   `python scripts/legal_library.py recheck --keep` and `export`, and file the
   export). Keep the old copy's checksum in the entry's notes with the day.
3. For each source it says UNREACHABLE: try the URL yourself. A moved page gets
   its new official address in `sources.json`; a site that now refuses scripts
   becomes `fetch: browser` and its copy is saved by hand
   (`python scripts/legal_library.py import-browser <id> <file>`).
4. For each source read BY HAND: open it in a browser and compare with the copy.

## 2. New laws

Look for laws that touch what the products do and that the library does not
yet name: a new state automatic-renewal or privacy law reaching business buyers,
a change to the FTC's negative-option rule, a Texas session's bills on texting,
AI, minors, data or taxes. Official sources only (a legislature's own site,
govinfo, ecfr, the agency). A law-firm note may point you at one, never stand as
the source. A new law becomes an entry with its proof copy, through the
product's register and `file_legal`, with status `watch` until a decision is
recorded.

## 3. Report

One short message: how many sources checked, which changed and what you did
about each, which entries moved status, what is new on the lawyer list, and the
next date the check should run. No hours. No em dashes.
