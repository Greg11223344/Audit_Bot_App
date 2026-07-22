# Deploying Audit_bot to Render + Supabase

This covers the path chosen: Render.com for the app (Docker-based web service + a persistent
disk for uploaded photos/PDF reports), Supabase for Postgres (the only supported database --
there is no local-file fallback). Everything in this repo is ready for it; the steps below are
what you do outside Claude Code.

## 1. Push this repo to GitHub

Render deploys from a git repo (GitHub or GitLab). Create a new repo on GitHub, then:

```
git remote add origin <your-github-repo-url>
git push -u origin main
```

(This repo has already been `git init`'d and committed locally -- see "What's already done" below.)

## 2. Get your Supabase connection string ready

You already have a Supabase project. From the Supabase dashboard -> Project Settings ->
Database -> Connection string, use the **direct connection** (port `5432`), not the pgbouncer
pooler (port `6543`): this app keeps a persistent SQLAlchemy connection pool, which is what the
direct port is meant for. It looks like:

```
postgresql://postgres:<your-password>@db.<project-ref>.supabase.co:5432/postgres
```

Keep this string somewhere private (a password manager) -- you'll paste it into Render's
dashboard in the next step, never into a file in this repo.

## 3. Create a Render account and deploy the blueprint

1. Sign up at render.com (needs a payment method for the "starter" plan used below; there's a
   free tier too if you want to try it before paying).
2. In the Render dashboard: **New +** -> **Blueprint**, connect your GitHub account, pick this
   repo. Render reads `render.yaml` at the repo root and provisions the web service and the
   persistent disk (no Render-managed database -- Supabase is the database).
3. Render will ask you to fill in the env vars marked `sync: false` in `render.yaml`:
   - `DATABASE_URL` -- paste your Supabase connection string from step 2.
   - `AUDIT_BOT_ADMIN_EMAIL` -- the email for the first admin account (e.g. yours).
   - `AUDIT_BOT_ADMIN_PASSWORD` -- pick a strong password now; the app refuses to boot in
     production without one (no well-known default password is ever used in production).
   - `AUDIT_BOT_SECRET_KEY` is generated automatically by Render -- you don't need to touch it.
4. Click deploy. Render builds the `Dockerfile`, boots the container -- which creates all tables
   in your Supabase database on first boot (see "Schema initialization" below) -- and gives you
   a URL like `https://audit-bot.onrender.com`.

## 4. First login and verification

- Admin dashboard: `https://<your-app>.onrender.com/admin/`
- Field app: `https://<your-app>.onrender.com/app/`
- Log in with the `AUDIT_BOT_ADMIN_EMAIL` / `AUDIT_BOT_ADMIN_PASSWORD` you set in step 3.
- From the admin Users page, create real accounts for your field engineers and internal staff.

## 5. (Optional) Attach a custom domain

Render dashboard -> your service -> Settings -> Custom Domains -> add your domain and follow
Render's instructions for the DNS record to add (a `CNAME` pointing at your Render URL, usually).
This is done in your domain registrar's DNS settings, which Claude Code cannot access.

## 6. Validate against Supabase before relying on it

This dev machine has no local Postgres and no Docker, and I don't have your real Supabase
password -- so the Postgres path was verified by static review only (no raw SQL anywhere in the
app, no SQLite-specific column types -- see `server/app/models.py`), not an actual run. Before
you trust it in production, run the test suite against Supabase yourself once, against a
throwaway/staging setup, **not** the real database once it has real users' data in it:

```
cd server
AUDIT_BOT_DATABASE_URL=<your Supabase connection string> ../venv/Scripts/python.exe -m pytest tests/ -v
```

**Important**: importing the app also seeds the first admin account (using the well-known dev
default `admin@auditbot.local` / `ChangeMe123!` unless you also set `AUDIT_BOT_ADMIN_PASSWORD` in
your local shell first). Running this against a database that already has your real
`AUDIT_BOT_ADMIN_PASSWORD`-seeded admin in it won't overwrite anything (seeding only happens "if
no user exists yet"), so it's safe to run once after Render's first successful deploy -- but if
you run it against a **fresh, empty** Supabase database *before* deploying to Render, that test
run's default admin becomes the permanent one (Render's later seed attempt will skip, since a
user already exists). Simplest safe order: deploy to Render first (step 3, which seeds your real
chosen admin password), *then* run this test suite afterward -- not before.

## 7. Seeding real checklist/machine data

The dev environment's data (checklist templates, machines, historical audits) was local-only
testing and was never meant to ship as-is into Supabase. Decide what you actually want in
production:

- **Checklist content** (`server/scripts/checklist_data_v2.json`): run
  `python scripts/rebuild_and_seed.py` once against your Supabase `DATABASE_URL` to import the
  same audit types/systems/checklists. This also wipes non-preserved data, so only do this on a
  genuinely empty production DB, before anyone has started using it, and after you've already
  confirmed you don't need step 6's test run to happen afterward (rebuild_and_seed.py preserves
  existing users the same way, but re-running things multiple times against a DB people are
  actively using is not something this script is designed for).
- **Historical audits** (the real ones from local dev, e.g. "Greg"'s test usage) are local-only
  test/dev activity -- there's no reason to carry those into production. Start production clean.

## Schema initialization ("run on first boot")

There's no separate migration/init SQL script to run -- `server/app/main.py` already calls
`Base.metadata.create_all(bind=engine)` at startup, which creates every table (from
`server/app/models.py`) if it doesn't already exist, every time the app boots. Against a fresh
Supabase database, the very first boot creates the full schema automatically; against an
already-initialized one, it's a no-op. This is the same mechanism local dev has always used.
Verified directly against this project's Supabase instance: boot creates all 13 tables.

**Gotcha carried over from real Postgres (didn't show up against local SQLite dev)**: Postgres
actually enforces the foreign keys defined in `models.py`. A bulk `db.query(Model).delete()` skips
SQLAlchemy's ORM-level cascade and Postgres correctly rejects it with a `ForeignKeyViolation` if
child rows still reference it. To delete cascading data (e.g. wiping test fixtures), delete
through the ORM instead -- `for obj in db.query(Model).all(): db.delete(obj)` -- so the
`cascade="all, delete-orphan"` relationships actually fire, and delete parents-before-children in
FK order (audits before audit types/machines, etc.).

## What's already done in the codebase

- **Postgres-only**: `server/app/config.py` requires `DATABASE_URL` (or `AUDIT_BOT_DATABASE_URL`)
  to be set -- there is no SQLite fallback anywhere anymore. It normalizes `postgres://` (what
  Supabase/Render/Railway hand out) to the SQLAlchemy-compatible `postgresql+psycopg2://` form.
- **No hardcoded secrets**: `SECRET_KEY` and the first-run admin password are both read from
  environment variables; the app **refuses to start** in production (`AUDIT_BOT_ENVIRONMENT=production`)
  if either is left at its insecure dev default. `render.yaml` never contains your real Supabase
  password -- `DATABASE_URL` is marked `sync: false`, meaning you paste it into Render's dashboard
  directly, and it's never written to this repo.
- **Persistent storage**: `AUDIT_BOT_STORAGE_DIR` controls where uploaded photos and generated
  PDF reports live -- `render.yaml` points it at the mounted disk (`/data/storage`) so it survives
  redeploys.
- **`Dockerfile`** builds the FastAPI backend and both static frontends (`field-app/`, `admin-app/`)
  into one image; the container respects the `$PORT` most PaaS platforms inject.
- **`.env.example`** documents every environment variable the app reads, including the required
  `AUDIT_BOT_DATABASE_URL`.

## What you still need to do yourself (outside Claude Code)

- Create the GitHub repo and push (step 1).
- Have your real Supabase connection string ready (step 2) -- I never had your real password.
- Create the Render account, connect it to GitHub, and fill in the `sync: false` secrets
  (`DATABASE_URL`, `AUDIT_BOT_ADMIN_EMAIL`, `AUDIT_BOT_ADMIN_PASSWORD`) when the blueprint asks
  (step 3).
- If you want a custom domain: buy/own it and configure its DNS (step 5).
- Run the test-suite validation yourself against Supabase (step 6) -- I can't reach it from here.
- Change the admin password after first login if you ever want to hand it off or reset it later.
- If you ever want a true native mobile app (push notifications, app-store distribution) instead
  of the installable PWA: an Apple Developer account ($99/yr) and a Google Play Developer account
  ($25 one-time). Not needed for the current PWA-based setup.
