# Standing order: the project manager is the authority

This is the user-level instruction for every Claude session on a machine that
has the bridge registered. It lives in the repo so it can be put back in one
command: `tools/bootstrap_guidance.sh` on a Mac (between markers, so the rest
of ~/.claude/CLAUDE.md is left alone) or `.\tools\bootstrap_guidance.ps1 -Key
<PM_GUIDANCE_KEY>` on Windows, which also register the bridge.

Every session on this machine carries the pm-guidance tools: get_rules,
get_feature_guidance, get_playbook, get_blueprint, report_lesson, suggest_update,
get_clients, upsert_project, log_expense, log_time,
register_hosting_resource and register_app. They talk to the deployed board at
https://builtbybeans.com, which is the one copy every machine and every
session agrees on. The bridge is registered at user scope and reads
PM_GUIDANCE_KEY from the environment. The bootstrap also installs three
hooks: the rules brief is in context at session start, and a session
cannot end a turn in which it wrote to a CLAUDE.md without filing the
lesson. That is the harness enforcing this order, not a request.

- Before building anything, call get_rules and follow the brief. When a
  feature is in play, call get_feature_guidance for it. Setting up a
  vendor: get_playbook. Starting a new app that resembles one already
  built (multi-tenant, phone apps, a trades back office): get_blueprint
  first, so the whole plan is lined up, and append to that blueprint when
  you change how an app with one fits together. All of this is Best
  Practices at /admin/practices,
  and it holds no prices: what something sells for is not yours to set.
- A new thing a client could ask for is a FEATURE, and it is what the MVP
  Builder picks from and the client reads: a short plain name ("Online
  booking", never a sentence or a lesson) and one sentence in the client's
  words, with the lesson in its guidance. A way of building is a RULE.
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
  stood up, and register_app the moment a public URL is verified - a
  build is not stood up until it is on My Apps, and a green
  register_hosting_resource without a url does NOT put it there.
- If the tools are missing from a session, or answer 401, say so once and
  do not pretend the loop is working, but never stop and never hand Michael
  a command: he does no terminal work. The same door answers at
  https://builtbybeans.com/api/guidance with the bearer key, which `railway
  variables --kv` reads in the Built-By-Bean-Website checkout. The fix is
  the registration in ~/.claude.json and PM_GUIDANCE_KEY in the environment,
  then a fresh session.
- Never through the door: contacting a client, resolving a ticket,
  sending a contract. Those are Michael's, and the API has no route for
  them on purpose.
