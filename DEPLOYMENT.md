# Deploying Audit_bot to Render

This covers the path chosen: Render.com, Docker-based web service + managed Postgres + a
persistent disk for uploaded photos/PDF reports. Everything in this repo is ready for it; the
steps below are what you do outside Claude Code.

## 1. Push this repo to GitHub

Render deploys from a git repo (GitHub or GitLab). Create a new repo on GitHub, then:

```
git remote add origin <your-github-repo-url>
git push -u origin main
```

(This repo has already been `git init`'d and committed locally -- see "What's already done" below.)

## 2. Create a Render account and deploy the blueprint

1. Sign up at render.com (needs a payment method for the "starter" plans used below; both the
   web service and the database have a free tier too if you want to try it before paying).
2. In the Render dashboard: **New +** -> **Blueprint**, connect your GitHub account, pick this
   repo. Render reads `render.yaml` at the repo root and provisions the web service, the
   Postgres database, and the persistent disk together.
3. Render will ask you to fill in the env vars marked `sync: false` in `render.yaml`:
   - `AUDIT_BOT_ADMIN_EMAIL` -- the email for the first admin account (e.g. yours).
   - `AUDIT_BOT_ADMIN_PASSWORD` -- pick a strong password now; the app refuses to boot in
     production without one (no well-known default password is ever used in production).
   - `AUDIT_BOT_SECRET_KEY` is generated automatically by Render -- you don't need to touch it.
4. Click deploy. Render builds the `Dockerfile`, boots the container, and gives you a URL like
   `https://audit-bot.onrender.com`.

## 3. First login and verification

- Admin dashboard: `https://<your-app>.onrender.com/admin/`
- Field app: `https://<your-app>.onrender.com/app/`
- Log in with the `AUDIT_BOT_ADMIN_EMAIL` / `AUDIT_BOT_ADMIN_PASSWORD` you set in step 2.
- From the admin Users page, create real accounts for your field engineers and internal staff.

## 4. (Optional) Attach a custom domain

Render dashboard -> your service -> Settings -> Custom Domains -> add your domain and follow
Render's instructions for the DNS record to add (a `CNAME` pointing at your Render URL, usually).
This is done in your domain registrar's DNS settings, which Claude Code cannot access.

## 5. Seeding real checklist/machine data

The dev environment's data (checklist templates, machines, historical audits) lives in the local
SQLite file and was never meant to ship as-is into a fresh production database. Decide what you
actually want in production:

- **Checklist content** (`server/scripts/checklist_data_v2.json`): run
  `python scripts/rebuild_and_seed.py` once against the production `DATABASE_URL` to import the
  same audit types/systems/checklists. This also wipes non-preserved data, so only do this on a
  genuinely empty production DB, before anyone has started using it.
- **Historical audits** (the real ones from local dev, e.g. "Greg"'s test usage) are local-only
  test/dev activity -- there's no reason to carry those into production. Start production clean.

## What's already done in the codebase

- **Postgres support**: `server/app/config.py` normalizes both `postgres://` and `DATABASE_URL`
  (Render/Railway's auto-injected variable name) to the SQLAlchemy-compatible form. SQLite still
  works for local dev (default when no `DATABASE_URL`/`AUDIT_BOT_DATABASE_URL` is set).
- **No hardcoded secrets**: `SECRET_KEY` and the first-run admin password are both read from
  environment variables; the app **refuses to start** in production (`AUDIT_BOT_ENVIRONMENT=production`)
  if either is left at its insecure dev default.
- **Persistent storage**: `AUDIT_BOT_STORAGE_DIR` controls where uploaded photos and generated
  PDF reports live -- `render.yaml` points it at the mounted disk (`/data/storage`) so it survives
  redeploys.
- **`Dockerfile`** builds the FastAPI backend and both static frontends (`field-app/`, `admin-app/`)
  into one image; the container respects the `$PORT` most PaaS platforms inject.
- **`.env.example`** documents every environment variable the app reads.

## What you still need to do yourself (outside Claude Code)

- Create the GitHub repo and push (step 1).
- Create the Render account, connect it to GitHub, and fill in the two `sync: false` secrets
  when the blueprint asks (step 2).
- If you want a custom domain: buy/own it and configure its DNS (step 4).
- Change the admin password after first login if you ever want to hand it off or reset it later.
- If you ever want a true native mobile app (push notifications, app-store distribution) instead
  of the installable PWA: an Apple Developer account ($99/yr) and a Google Play Developer account
  ($25 one-time). Not needed for the current PWA-based setup.
