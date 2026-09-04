# Standing order: the project manager is the authority

This is the user-level instruction file for every Claude session on a
machine that has the bridge registered. It lives in the repo so it can be
put back on any machine in one copy:

    .\tools\bootstrap_guidance.ps1 -Key <PM_GUIDANCE_KEY>

which also registers the bridge. The order alone is one copy:

    Copy-Item tools\STANDING_ORDER.md $HOME\.claude\CLAUDE.md

Every session on this machine carries the pm-guidance tools: get_rules,
get_feature_guidance, get_playbook, report_lesson, suggest_update,
get_clients, upsert_project, log_expense, log_time and
register_hosting_resource. They talk to the deployed board at
https://builtbybeans.com, which is the one copy every machine and every
session agrees on. The bridge is registered at user scope and reads
PM_GUIDANCE_KEY from the environment.

- Before building anything, call get_rules and follow the brief. When a
  feature is in play, call get_feature_guidance for it. Setting up a
  vendor: get_playbook.
- When Michael says "new rule", "rule" or "never again", it becomes a
  catalogue rule right then: suggest_update with kind rule, mode create,
  a category from the board's list, and a payload carrying the name, the
  summary, the gold standard and the pitfalls, written for any project.
  Do this before the code change, not after. A note in a repo's
  CLAUDE.md is not the rule; the catalogue row is. Confirm by name and
  say that the Rules count went up.
- When a lesson costs something (a bug that shipped, a vendor screen that
  moved, a better file to copy), file it through report_lesson or
  suggest_update the moment it is learned, not at the end of the work.
- Doing real client work: upsert_project for the project, log_time and
  log_expense as they happen, register_hosting_resource for anything
  stood up.
- If the tools are missing from a session, or answer 401, say so first
  and do not pretend the loop is working. The fix is the registration in
  ~/.claude.json and PM_GUIDANCE_KEY in the environment, then a fresh
  session.
- Never through the door: contacting a client, resolving a ticket,
  sending a contract. Those are Michael's, and the API has no route for
  them on purpose.
