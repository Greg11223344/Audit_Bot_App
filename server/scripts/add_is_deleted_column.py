"""Adds the is_deleted column to the audits table on the existing dev DB (idempotent)."""
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from sqlalchemy import text  # noqa: E402

from app.database import engine  # noqa: E402


def main():
    with engine.connect() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(audits)"))]
        if "is_deleted" not in columns:
            conn.execute(text("ALTER TABLE audits ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT 0"))
            conn.commit()
            print("Added is_deleted column to audits.")
        else:
            print("is_deleted column already present.")


if __name__ == "__main__":
    main()
