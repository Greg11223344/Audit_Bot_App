"""Imports data/customers.xlsx -> Machine records into whatever database DATABASE_URL/
AUDIT_BOT_DATABASE_URL points at, and nothing else -- does not touch checklist data, users, or
audits. Safe to run against a production database that already has real checklist content and a
real admin account (unlike `rebuild_and_seed.py` without --checklist-only, which also re-imports
historical local dev/test audits -- including attachment file paths that only exist on this dev
machine, not in production).

Safe to re-run: existing machines are matched by (serial_number, customer) and left untouched;
only genuinely new rows get added.
"""
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SERVER_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SERVER_DIR))

from app import models  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402

# Reuse the exact same parsing/import logic rebuild_and_seed.py uses -- no duplicated logic to
# drift out of sync.
from rebuild_and_seed import CUSTOMERS_EXCEL, import_customers  # noqa: E402


def main():
    if not CUSTOMERS_EXCEL.exists():
        print(f"ERROR: {CUSTOMERS_EXCEL} not found.")
        sys.exit(1)

    print("Ensuring schema exists (creates any missing tables; never drops data)...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        before = db.query(models.Machine).count()
        machine_model_by_name: dict[str, models.MachineModel] = {}
        count = import_customers(db, machine_model_by_name)
        after = db.query(models.Machine).count()

        print(f"Processed {count} rows from {CUSTOMERS_EXCEL.name}.")
        print(f"Machines: {before} -> {after} ({after - before} new).")

        for m in db.query(models.Machine).order_by(models.Machine.id).all():
            print(f"  #{m.id} {m.customer} / {m.serial_number} ({m.machine_model.name})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
