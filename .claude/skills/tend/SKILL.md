---
name: tend
description: Tend Best Practices on the Built by Bean board - fold the waiting notes into rules and playbooks, prune the rules, bring every blueprint and business map up to date with its repos, and file the gaps each app has against the others. Use when Michael says "tend", "run tend", "update best practices", or asks for the upkeep run. Runs on his Claude plan, never the paid API.
---

# Tend

Michael, 2026-11-04: he wants Best Practices to keep itself current (rules,
playbooks, blueprints, business maps) and to tell him where one app has fallen
behind another, without paying for the API every night. This run is that job,
done by you in this session, on his plan. The board's paid nightly curator is
switched off while this is how it is done (`CURATOR_ENABLED` on cost-sync).

Everything goes through the board's door with the pm-guidance tools, so every
change lands on the History tab with a Revert. Never edit the board's database
any other way, and never contact a client, resolve a ticket or send a contract.

## Before you start

1. You need the pm-guidance tools, including `tend_brief`, `close_note`,
   `get_map`, `change_map`, `file_gaps` and `tend_finished`. If they are
   missing, say so and stop: the bridge in `tools/pm_guidance_mcp.py` gains
   them in a session started after the repo was pulled.
2. Call `tend_brief`. Keep its counts: you report them at the end.
3. Tell Michael in one line what is waiting (notes, blueprints whose repos
   moved), then work without asking. He reads the result, not the plan.

## 1. The notes waiting

Each note is a section a core repo's CLAUDE.md gained or changed, or a held
change. For each one, decide:

- **Fold it** into the rule, feature or playbook it belongs to:
  `suggest_update` mode `append` (rules: `pitfalls_md` for what went wrong,
  `gold_standard_md` for how to build it; playbooks: `traps_md`). Then
  `close_note` outcome `folded`.
- **Add** a rule from it when it is a way of building that holds for any
  project and nothing covers it: `report_lesson`, or `suggest_update` mode
  `create` kind `rule` with a category. Then `close_note` outcome `added`.
- **Set it aside** when it was only true of that one repo, is a status note,
  or is already said: `close_note` outcome `discarded` with the reason.

Write for any project, not the repo the note came from. Name the repo in
brackets as the example. At most 60 notes a run; the rest wait.

## 2. The rules

The brief lists every rule with its size and where the audit finds it
broken. Aim for about 120 rules over several runs, not in one go. In one run
do at most: 10 merges (rewrite the keeper with `suggest_update` mode
`replace`, then `retire` the others with a reason naming the keeper), 10
tightens (a rule over about 6,000 characters rewritten shorter, keeping every
distinct lesson), and 15 retirements (true of one repo or vendor only,
superseded, or something nobody would get wrong). Never retire a rule the
audit still finds broken in a repo. That is a gap, not a dead rule.

## 3. The playbooks

When a note or a repo change is about a vendor, it belongs in that vendor's
playbook: append to `traps_md`, or replace `your_steps_md` when a screen moved.
`get_playbook` first and do not repeat what is already there.

## 4. The blueprints

For each blueprint in the brief, look at each of its repos. They are cloned
under `~/Documents/Apps` on Michael's machines (EntertainHQ, KuperPlumbing,
Data-Dungeon, and so on). If one is missing, `gh repo clone` it into the
scratchpad. Run `git fetch -q` and read `origin/main` without changing the
working tree, branch or files: `git log origin/main --since=<blueprint last
updated> --oneline`, `git diff <old>..origin/main -- CLAUDE.md`, and the files
the changes touch. If a repo has not moved since the blueprint was updated,
skip it.

When it has moved, bring the blueprint in line: `get_blueprint` for the
current text, then `suggest_update` kind `blueprint`. Use `append` for a new
trap or part. Use `replace` for a section whose facts changed (a service
swapped, a part moved host, a connection added). Use field `stages` with
`payload.stages` when the build order itself changed. Say in `reason` which
commit or section shows it. Never write a secret or a variable's value.

## 5. The business maps

For each blueprint with a business map, `get_map` it and hold it against the
blueprint's parts and connections. Then `change_map` so the map says what the
code says: a surface that moved host, a service swapped, a phone app now live,
an outcome now delivered, a line between systems that exists now. One
`change_map` call per business, with every change in it and the reason.
Change only what the repo or blueprint shows. A map node Michael added by
hand that nothing contradicts stays.

## 6. The gaps

Hold the blueprints against each other. Where one app does something
another of the same kind should and does not, file it for the app that lacks
it, with `from` naming the app that has it. Examples: a queue that retries
sends, an outage notice, backups off the host, a hub to the board, CSRF
exemptions for webhooks, a status site, a help bot. Where every app would
gain from something none does yet, it is an `enhancement`. Use the audit's
"broken in" counts too: a rule broken in one app's repo is a gap for that
app.

`file_gaps` once per app, at most 10 a run, the most worthwhile first. Each
needs a short plain title and a `detail_md` saying what to do and where it is
done already (repo and file). Skip anything the brief lists as closed.

## 7. Finish

Call `tend_finished` with the counts (added, folded, merged, tightened,
retired, discarded) and a note of what else changed: blueprints updated, maps
changed, gaps filed. Then tell Michael, in plain words and in a few lines:
what changed, the gaps worth his attention first, and anything you could not
do. No em dashes, anywhere.
