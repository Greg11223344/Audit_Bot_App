"""Test-session setup.

Must run before any `app.*` import: points the app at a throwaway temp SQLite file (instead of
the real audit_bot.db) and makes sure `import app` resolves to this project's server/app package
rather than the legacy C:\\Audit_Bot\\app.py script that shares the same top-level name.
"""
import os
import sys
import tempfile
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER_DIR))

_test_db_path = Path(tempfile.gettempdir()) / f"audit_bot_test_{os.getpid()}.db"
if _test_db_path.exists():
    _test_db_path.unlink()
os.environ["AUDIT_BOT_DATABASE_URL"] = f"sqlite:///{_test_db_path}"
