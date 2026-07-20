"""Test-session setup.

Must run before any `app.*` import: makes sure `import app` resolves to this project's
server/app package rather than the legacy C:\\Audit_Bot\\app.py script that shares the same
top-level name.

Postgres is the only supported database (see app/config.py) -- there is no throwaway local-file
fallback for tests. Set AUDIT_BOT_DATABASE_URL (or DATABASE_URL) to a scratch/staging Postgres
before running pytest, e.g. a dedicated test schema on the same Supabase project, or a separate
Supabase project entirely. Never point it at a database with real data: this suite creates and
drops tables freely.
"""
import os
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER_DIR))

if "AUDIT_BOT_DATABASE_URL" not in os.environ and "DATABASE_URL" not in os.environ:
    raise RuntimeError(
        "Set AUDIT_BOT_DATABASE_URL (or DATABASE_URL) to a scratch/staging Postgres connection "
        "string before running the test suite -- there is no local-file fallback. Example: "
        "AUDIT_BOT_DATABASE_URL=postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres pytest"
    )
