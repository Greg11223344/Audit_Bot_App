"""Adds ONE audit type from checklist_data_v2.json to whatever database DATABASE_URL/
AUDIT_BOT_DATABASE_URL points at, without touching any existing audit types, systems, machines,
or users. Use this to add a new audit type (e.g. after editing checklist_data_v2.json) to a
database that's already seeded -- re-running import_checklist_json's full import would duplicate
the audit types that already exist there.

Usage:
    python scripts/import_new_audit_type.py fse_visit_check
"""
import json
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SERVER_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SERVER_DIR))

from app import models  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402

from rebuild_and_seed import CHECKLIST_JSON_PATH, import_one_audit_type  # noqa: E402


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/import_new_audit_type.py <audit_type_key>")
        sys.exit(1)

    target_key = sys.argv[1]

    data = json.loads(CHECKLIST_JSON_PATH.read_text(encoding="utf-8"))
    audit_type_data = next((at for at in data["audit_types"] if at["audit_type_key"] == target_key), None)
    if audit_type_data is None:
        available = [at["audit_type_key"] for at in data["audit_types"]]
        print(f"ERROR: '{target_key}' not found in {CHECKLIST_JSON_PATH.name}. Available: {available}")
        sys.exit(1)

    print("Ensuring schema exists (creates any missing tables; never drops data)...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        existing = db.query(models.AuditType).filter(models.AuditType.key == target_key).first()
        if existing is not None:
            print(f"ERROR: an AuditType with key '{target_key}' already exists (id={existing.id}) -- aborting to avoid a duplicate.")
            sys.exit(1)

        next_order_index = db.query(models.AuditType).count()
        stats = import_one_audit_type(db, audit_type_data, next_order_index)

        print(f"Added audit type '{target_key}': {stats}")

        created = db.query(models.AuditType).filter(models.AuditType.key == target_key).first()
        for s in created.systems:
            item_count = sum(len(sm.items) for sm in s.sub_modules)
            print(f"  - {s.name}: {len(s.sub_modules)} sub-module(s), {item_count} item(s)")

        print()
        print("Unaffected (confirm these match before/after):")
        print(f"  total audit types now: {db.query(models.AuditType).count()}")
        print(f"  machines: {db.query(models.Machine).count()}")
        print(f"  users: {db.query(models.User).count()}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
