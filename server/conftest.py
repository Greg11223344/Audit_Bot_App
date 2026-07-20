"""Test-session setup.

Must run before any `app.*` import: points the app at a throwaway temp SQLite file (instead of
the real audit_bot.db) and makes sure `import app` resolves to this project's server/app package
rather than the legacy C:\\Audit_Bot\\app.py script that shares the same top-level name.

To validate the same test suite against a real Postgres before cutting a production deploy over
(e.g. Render's external connection string for the database this app will actually use), set
AUDIT_BOT_DATABASE_URL yourself before running pytest -- it's respected as-is and the throwaway
SQLite file is skipped. Point it at a scratch/staging database, never a database with real data:
this suite creates and drops tables freely.
"""
import os
import sys
import tempfile
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER_DIR))

if "AUDIT_BOT_DATABASE_URL" not in os.environ:
    _test_db_path = Path(tempfile.gettempdir()) / f"audit_bot_test_{os.getpid()}.db"
    if _test_db_path.exists():
        _test_db_path.unlink()
    os.environ["AUDIT_BOT_DATABASE_URL"] = f"sqlite:///{_test_db_path}"
