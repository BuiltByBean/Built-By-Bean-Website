# Deployment Checklist — Merging Project Manager into Built-By-Bean-Website

Follow these steps in order after reviewing the `merge-project-manager` branch.

## 1. Push the branch and open a PR

```bash
cd C:/Users/MBean/Documents/Built-By-Bean-Website
git push -u origin merge-project-manager
```

Open a PR on GitHub. Do NOT merge to `main` until every step below is done and verified.

## 2. Set environment variables on the Built-By-Bean-Website Railway service

Log into Railway → Built-By-Bean-Website project → web service → Variables. Add every variable from `.env.example` with real values.

**Critical variables to copy from the old Project-Manager Railway service:**

- `SECRET_KEY` — copy exactly (reusing it keeps any existing session cookies valid)
- `DATABASE_URL` — **must** point at the same Postgres as PM. See step 3.
- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `AWS_S3_BUCKET`
- `AWS_S3_REGION`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `ADMIN_PASSWORD` (only if you want to re-seed on fresh DB; can leave blank)

**Already set on website (leave as-is):**

- `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `CONTACT_EMAIL`

## 3. Point DATABASE_URL at the existing PM Postgres

You have two options:

**Option A (simpler):** Copy the Postgres connection string from the old Project-Manager Railway project and paste it as `DATABASE_URL` on the Built-By-Bean-Website service. Both services will connect to the same DB — harmless because step 6 shuts PM down.

**Option B (cleaner long-term):** In Railway, move the Postgres service from the Project-Manager project into the Built-By-Bean-Website project. Use the Railway UI: project settings → service → "Move to another project."

Either way, your existing clients, projects, tasks, invoices, Stripe customer IDs, and everything else stay intact. When the merged app boots, `flask db upgrade` runs and is a no-op because the schema is already at head.

## 4. Merge the PR and deploy

Once env vars are set, merge the `merge-project-manager` PR into `main`. Railway will auto-deploy.

**Watch the deploy logs.** You should see:

```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
```

with no "Running upgrade" lines (schema already at head). Then gunicorn starts.

## 5. Smoke test the deployed URL

Visit your Railway deploy URL (or `builtbybean.com` if DNS already points there):

1. `/` — marketing homepage loads. "Log In" button visible top-right.
2. Click "Log In" → `/login` renders with dark theme.
3. Log in with your existing credentials (Michael.Bean, etc.).
4. You land on `/admin` — tile grid with "Project Manager" tile.
5. Click the tile → `/admin/pm/` loads your dashboard with real data.
6. Verify: client list, a specific client detail, a project detail, tasks list, Stripe invoices list, service-costs dashboard.
7. Log out → back to `/` as anonymous. "Log In" button visible again.

## 6. Update the Stripe webhook URL

Log into [Stripe Dashboard → Developers → Webhooks](https://dashboard.stripe.com/webhooks). Find the webhook endpoint currently pointing at:

```
https://project-manager-production-ec5b.up.railway.app/stripe/webhook
```

Edit the endpoint and change it to:

```
https://builtbybean.com/admin/pm/stripe/webhook
```

(Substitute your actual Railway URL if DNS isn't cut over yet.)

The signing secret stays the same — no need to change `STRIPE_WEBHOOK_SECRET`.

**Test it:** Send a test event from Stripe Dashboard (the "Send test event" button). You should see `200 OK` in the webhook delivery log. Alternatively, create a small test invoice in Stripe for a test customer and confirm it shows up in `/admin/pm/stripe/invoices`.

## 7. DNS cutover (if needed)

If `builtbybean.com` currently points at the old Built-By-Bean-Website Railway service, **no DNS change is needed** — you redeployed that same service with new code. The domain still resolves correctly.

If you had DNS pointing at the old Project-Manager service for any reason, update it in Cloudflare / your DNS provider to point at the Built-By-Bean-Website service.

## 8. Retire the old Project-Manager Railway service

**Only after steps 5 and 6 are verified working.**

In Railway, go to the old Project-Manager project:

1. Confirm nothing is pointing at it anymore (Stripe webhook, DNS, bookmarks)
2. **If you chose Option 3A** (both services share a Postgres): just delete the *web service*, NOT the Postgres. You're still using it from the merged app.
3. **If you chose Option 3B** (Postgres moved to website project): you can delete the entire old PM project.

## 9. Delete the local Project-Manager directory (optional)

Once you're confident the merge is stable, you can delete `C:/Users/MBean/Documents/Project-Manager` from your local disk. The merged `Built-By-Bean-Website` repo now contains everything. (I wouldn't rush this — leave it around for a week as a reference.)

---

## Rollback plan

If anything goes wrong after deploy:

1. In Railway, revert the deploy to the previous commit (the pre-merge state) via the deployments tab.
2. Re-add the Stripe webhook URL pointing back at the old PM Railway service.
3. Re-enable the old PM Railway service if you deleted it.

Because the DB was never modified by the merge (schema is already at head), your data is untouched even if you roll back the code.

---

## What changed in the code

- `app.py` — was a 71-line marketing site, now a 1990-line `create_app()` factory registering the marketing routes plus a `pm_bp` blueprint mounted at `/admin/pm`.
- `pm/` — new package containing `stripe_routes.py` and `service_costs_routes.py` (PM's existing blueprints, repointed to `/admin/pm/stripe` and `/admin/pm/service-costs`).
- `models.py`, `forms.py`, `config.py`, `stripe_service.py`, `service_costs_service.py`, `seed_user.py` — copied from Project-Manager.
- `migrations/` — copied from Project-Manager. Current head is `b2c3d4e5f7a1`.
- `templates/pm/` — all 30 PM templates, moved into a namespaced subfolder. All `url_for('xxx')` calls rewritten to `url_for('pm.xxx')` where needed.
- `templates/login.html` — new, styled to match the marketing site dark theme.
- `templates/admin_hub.html` — new, tile grid landing page after login.
- `templates/index.html` — added Log In / Admin button in top-right nav.
- `static/pm/fonts/DancingScript.ttf` — PM's signature font for SOW PDFs.
- `static/css/style.css` — appended ~250 lines of scoped styles for login page, hub, tiles, and nav login button.
- `Procfile` — now runs `flask db upgrade` before starting gunicorn.
- `requirements.txt` — now includes all PM deps.
- `.env.example` — merged with all PM env vars.
- `.gitignore` — adds `data/`, `static/uploads/`, `*.db`, `.claude/`.

## URL structure

| Public | Auth-required |
|---|---|
| `GET /` marketing homepage | `GET /admin` hub |
| `POST /api/contact` contact form | `GET /admin/pm/` PM dashboard |
| `GET /login` login page | `GET /admin/pm/clients` etc. |
| `POST /login` login submit | `GET /admin/pm/stripe/invoices` etc. |
| `POST /admin/pm/stripe/webhook` Stripe webhook | `GET /logout` |
