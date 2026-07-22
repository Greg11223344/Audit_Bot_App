"""Seeds the AuditType -> System -> SubModule -> ChecklistItem schema from authoritative sources.
Targets whatever Postgres database DATABASE_URL/AUDIT_BOT_DATABASE_URL points at (Supabase in
production, a local/staging Postgres otherwise) -- this app has no SQLite fallback.

Default (full) behavior:
  1. Preserves any existing users (name/email/role/password_hash) -- never overwrites a real
     account's password. If the database is empty, seeds the default admin instead.
  2. Ensures the schema exists (`Base.metadata.create_all` -- creates missing tables, never
     drops or truncates existing data).
  3. Imports scripts/checklist_data_v2.json -- the authoritative, hand-verified checklist data
     (2 audit types, each with systems -> sub-modules -> full-text checks).
  4. Imports data/customers.xlsx -> Machine records.
  5. Re-creates historical dev/test audits from scripts/legacy_audit_snapshot.json under a hidden
     "Legacy" audit type, preserving each result's exact original text/value/attachments/tasks.

Pass --checklist-only to skip steps 4-5 -- use this against a production database that should
start clean of local dev/test data (customers.xlsx machines, historical test audits).

Not idempotent for the checklist import specifically: re-running adds another copy of each audit
type/system/sub-module/item rather than updating in place, since nothing here dedupes against
existing rows by name. Run it once per target database.
"""
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SERVER_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SERVER_DIR))

import pandas as pd  # noqa: E402

from app import models  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.auth import hash_password  # noqa: E402

CHECKLIST_JSON_PATH = Path(__file__).parent / "checklist_data_v2.json"
LEGACY_SNAPSHOT_PATH = Path(__file__).parent / "legacy_audit_snapshot.json"
CUSTOMERS_EXCEL = PROJECT_ROOT / "data" / "customers.xlsx"

DEFAULT_MACHINE_MODEL_NAME = "HP Scitex C5X0"

IMAGE_KEYWORDS = [
    "picture", "photo", "image", "add picture", "add photo",
    "take picture", "take photo", "send pic", "scanner picture", "scanners",
]


def requires_photo(text: str) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in IMAGE_KEYWORDS)


# ---------- Step 1: preserve existing users ----------

def capture_existing_users() -> list[dict]:
    """Postgres only now -- there's no local file whose existence would tell us "empty DB" the
    way the old SQLite check did, so just query directly. Table may not exist yet on a genuinely
    fresh database, which is exactly the "nothing to capture" case."""
    db = SessionLocal()
    try:
        return [
            {
                "name": u.name,
                "email": u.email,
                "role": u.role.value,
                "password_hash": u.password_hash,
                "is_active": u.is_active,
            }
            for u in db.query(models.User).all()
        ]
    except Exception:
        return []
    finally:
        db.close()


# ---------- Step 3: checklist_data_v2.json import ----------

def import_checklist_json(db) -> dict:
    data = json.loads(CHECKLIST_JSON_PATH.read_text(encoding="utf-8"))

    stats = {"audit_types": 0, "systems": 0, "sub_modules": 0, "items": 0}

    for at_index, audit_type_data in enumerate(data["audit_types"]):
        audit_type = models.AuditType(
            key=audit_type_data["audit_type_key"],
            label=audit_type_data["audit_type_label"],
            order_index=at_index,
        )
        db.add(audit_type)
        db.flush()
        stats["audit_types"] += 1

        for sys_index, system_data in enumerate(audit_type_data["systems"]):
            system_def = models.SystemDef(
                audit_type_id=audit_type.id,
                name=system_data["system"],
                order_index=sys_index,
            )
            db.add(system_def)
            db.flush()
            stats["systems"] += 1

            for sm_index, sub_module_data in enumerate(system_data["sub_modules"]):
                sub_module = models.SubModuleDef(
                    system_def_id=system_def.id,
                    name=sub_module_data["sub_module"],
                    order_index=sm_index,
                )
                db.add(sub_module)
                db.flush()
                stats["sub_modules"] += 1

                for item_index, check_text in enumerate(sub_module_data["checks"]):
                    db.add(
                        models.ChecklistItem(
                            sub_module_id=sub_module.id,
                            description=check_text,
                            requires_photo=requires_photo(check_text),
                            order_index=item_index,
                        )
                    )
                    stats["items"] += 1

    db.commit()
    return stats


# ---------- Step 4: customers.xlsx -> Machines ----------

def load_customers_dataframe(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    df.columns = [str(c).strip() for c in df.columns]

    def find_col(names):
        norm = {str(c).strip().lower(): c for c in df.columns}
        for n in names:
            if n.strip().lower() in norm:
                return norm[n.strip().lower()]
        return None

    site_col = find_col(["Site", "Customer Name", "Customer", "Client"])
    serial_col = find_col(["SN", "S/N", "Machine Serial Number", "Machine SN"])
    region_col = find_col(["Region"])
    machine_type_col = find_col(["Machine Type", "Machine", "Model", "Machine Model"])
    engineer_col = find_col(["Engineer Owner", "Engineer", "Owner"])

    out = pd.DataFrame()
    out["customer"] = df[site_col].fillna("").astype(str).str.strip() if site_col else ""
    out["serial_number"] = df[serial_col].fillna("").astype(str).str.strip() if serial_col else ""
    out["region"] = df[region_col].fillna("").astype(str).str.strip() if region_col else ""
    out["machine_type"] = df[machine_type_col].fillna("").astype(str).str.strip() if machine_type_col else ""
    out["engineer_owner"] = df[engineer_col].fillna("").astype(str).str.strip() if engineer_col else ""

    return out[(out["customer"] != "") & (out["serial_number"] != "")]


def get_or_create_machine_model(db, machine_model_by_name: dict, name: str) -> models.MachineModel:
    obj = machine_model_by_name.get(name)
    if obj is not None:
        return obj
    obj = db.query(models.MachineModel).filter(models.MachineModel.name == name).first()
    if obj is None:
        obj = models.MachineModel(name=name)
        db.add(obj)
        db.flush()
    machine_model_by_name[name] = obj
    return obj


def get_or_create_machine(
    db, machine_model_by_name: dict, customer: str, serial_number: str,
    site: str = "", region: str = "", engineer_owner: str = "", machine_type: str = "",
) -> models.Machine:
    machine = (
        db.query(models.Machine)
        .filter(models.Machine.serial_number == serial_number, models.Machine.customer == customer)
        .first()
    )
    if machine is not None:
        return machine

    model_name = machine_type.strip() or DEFAULT_MACHINE_MODEL_NAME
    machine_model = get_or_create_machine_model(db, machine_model_by_name, model_name)

    machine = models.Machine(
        machine_model_id=machine_model.id,
        serial_number=serial_number,
        customer=customer,
        site=site or customer,
        region=region,
        engineer_owner=engineer_owner,
    )
    db.add(machine)
    db.flush()
    return machine


def import_customers(db, machine_model_by_name: dict) -> int:
    if not CUSTOMERS_EXCEL.exists():
        print(f"  WARNING: {CUSTOMERS_EXCEL} not found, skipping customer import.")
        return 0

    customers_df = load_customers_dataframe(CUSTOMERS_EXCEL)
    for row in customers_df.itertuples(index=False):
        get_or_create_machine(
            db, machine_model_by_name,
            customer=row.customer, serial_number=row.serial_number,
            site=row.customer, region=row.region,
            engineer_owner=row.engineer_owner, machine_type=row.machine_type,
        )
    db.commit()
    return len(customers_df)


# ---------- Step 5: re-import historical audits under a hidden "Legacy" audit type ----------

def get_or_create_user_from_snapshot(db, engineer_snapshot: dict) -> models.User:
    user = db.query(models.User).filter(models.User.email == engineer_snapshot["email"]).first()
    if user is not None:
        return user
    # Shouldn't normally happen (users are restored in step 1), but fall back safely.
    user = models.User(
        name=engineer_snapshot["name"],
        email=engineer_snapshot["email"],
        role=models.UserRole(engineer_snapshot["role"]),
        password_hash=hash_password(uuid.uuid4().hex),
    )
    db.add(user)
    db.flush()
    return user


def reimport_legacy_audits(db, machine_model_by_name: dict) -> int:
    if not LEGACY_SNAPSHOT_PATH.exists():
        print(f"  WARNING: {LEGACY_SNAPSHOT_PATH} not found, skipping historical audit re-import.")
        return 0

    snapshot = json.loads(LEGACY_SNAPSHOT_PATH.read_text(encoding="utf-8"))

    legacy_audit_type = models.AuditType(key="legacy", label="Legacy (migrated data)", order_index=999, is_active=False)
    db.add(legacy_audit_type)
    db.flush()

    system_defs_by_name: dict[str, models.SystemDef] = {}
    sub_modules_by_key: dict[tuple, models.SubModuleDef] = {}
    items_by_key: dict[tuple, models.ChecklistItem] = {}

    def get_or_create_legacy_system(name: str) -> models.SystemDef:
        if name not in system_defs_by_name:
            sd = models.SystemDef(audit_type_id=legacy_audit_type.id, name=name, order_index=len(system_defs_by_name), is_active=False)
            db.add(sd)
            db.flush()
            system_defs_by_name[name] = sd
        return system_defs_by_name[name]

    def get_or_create_legacy_sub_module(system_def: models.SystemDef, name: str) -> models.SubModuleDef:
        key = (system_def.id, name)
        if key not in sub_modules_by_key:
            count = sum(1 for k in sub_modules_by_key if k[0] == system_def.id)
            sm = models.SubModuleDef(system_def_id=system_def.id, name=name, order_index=count)
            db.add(sm)
            db.flush()
            sub_modules_by_key[key] = sm
        return sub_modules_by_key[key]

    def get_or_create_legacy_item(sub_module: models.SubModuleDef, description: str) -> models.ChecklistItem:
        key = (sub_module.id, description)
        if key not in items_by_key:
            count = sum(1 for k in items_by_key if k[0] == sub_module.id)
            item = models.ChecklistItem(
                sub_module_id=sub_module.id, description=description, order_index=count, is_active=False,
            )
            db.add(item)
            db.flush()
            items_by_key[key] = item
        return items_by_key[key]

    created = 0
    for audit_snapshot in snapshot:
        engineer = get_or_create_user_from_snapshot(db, audit_snapshot["engineer"])
        machine = get_or_create_machine(
            db, machine_model_by_name,
            customer=audit_snapshot["machine"]["customer"],
            serial_number=audit_snapshot["machine"]["serial_number"],
            site=audit_snapshot["machine"]["site"],
            region=audit_snapshot["machine"]["region"],
            engineer_owner=audit_snapshot["machine"]["engineer_owner"],
            machine_type=audit_snapshot["machine"]["machine_model_name"],
        )

        audit = models.Audit(
            client_uuid=audit_snapshot["client_uuid"],
            machine_id=machine.id,
            engineer_id=engineer.id,
            audit_type=audit_snapshot["audit_type_label"],
            status=models.AuditStatus(audit_snapshot["status"]),
            notes=audit_snapshot["notes"] or "",
            version=audit_snapshot["version"],
            started_at=datetime.fromisoformat(audit_snapshot["started_at"]) if audit_snapshot["started_at"] else datetime.utcnow(),
            completed_at=datetime.fromisoformat(audit_snapshot["completed_at"]) if audit_snapshot["completed_at"] else None,
            updated_at=datetime.fromisoformat(audit_snapshot["updated_at"]) if audit_snapshot["updated_at"] else datetime.utcnow(),
        )
        db.add(audit)
        db.flush()

        for system_snapshot in audit_snapshot["systems"]:
            system_def = get_or_create_legacy_system(system_snapshot["name"])
            db.add(models.AuditSystem(audit_id=audit.id, system_def_id=system_def.id))

        # All of this audit's results live under whichever legacy system(s) it was linked to;
        # use the first (audits here only ever had exactly one system selected).
        primary_system = get_or_create_legacy_system(audit_snapshot["systems"][0]["name"]) if audit_snapshot["systems"] else get_or_create_legacy_system("Unknown")

        # Old flat data had two independent free-text fields (module, sub_module); different
        # modules legitimately reused the same sub_module name (e.g. both "OPV" and "Print
        # Engine Bridge" had their own "Valves" section with an identical check under it), so
        # the module must stay part of the grouping key or unrelated items collide.
        result_by_module_description: dict[tuple, models.AuditResult] = {}
        result_by_description: dict[str, models.AuditResult] = {}
        for result_snapshot in audit_snapshot["results"]:
            module = result_snapshot["module"] or "General"
            raw_sub_module = (result_snapshot["sub_module"] or "").strip()
            if not raw_sub_module or raw_sub_module.lower() == "sub module":
                sub_module_name = module
            else:
                sub_module_name = f"{module} / {raw_sub_module}"

            sub_module = get_or_create_legacy_sub_module(primary_system, sub_module_name)
            item = get_or_create_legacy_item(sub_module, result_snapshot["description"])

            audit_result = models.AuditResult(
                audit_id=audit.id,
                checklist_item_id=item.id,
                result=result_snapshot["result"],
                comment=result_snapshot["comment"],
                flagged_critical=result_snapshot["flagged_critical"],
                updated_at=datetime.fromisoformat(result_snapshot["updated_at"]) if result_snapshot["updated_at"] else datetime.utcnow(),
            )
            db.add(audit_result)
            db.flush()
            result_by_module_description[(module, result_snapshot["description"])] = audit_result
            result_by_description.setdefault(result_snapshot["description"], audit_result)

        for attachment_snapshot in audit_snapshot["attachments"]:
            key = (attachment_snapshot["result_item_module"], attachment_snapshot["result_item_description"])
            matching_result = result_by_module_description.get(key) or result_by_description.get(
                attachment_snapshot["result_item_description"]
            )
            db.add(
                models.Attachment(
                    client_uuid=attachment_snapshot["client_uuid"],
                    audit_id=audit.id,
                    audit_result_id=matching_result.id if matching_result else None,
                    file_path=attachment_snapshot["file_path"],
                    taken_at=datetime.fromisoformat(attachment_snapshot["taken_at"]) if attachment_snapshot["taken_at"] else datetime.utcnow(),
                )
            )

        for task_snapshot in audit_snapshot["tasks"]:
            matching_result = result_by_description.get(task_snapshot["result_item_description"])
            db.add(
                models.Task(
                    audit_id=audit.id,
                    audit_result_id=matching_result.id if matching_result else None,
                    description=task_snapshot["description"],
                    status=models.TaskStatus(task_snapshot["status"]),
                    resolution_note=task_snapshot["resolution_note"] or "",
                    created_at=datetime.fromisoformat(task_snapshot["created_at"]) if task_snapshot["created_at"] else datetime.utcnow(),
                    closed_at=datetime.fromisoformat(task_snapshot["closed_at"]) if task_snapshot["closed_at"] else None,
                )
            )

        db.commit()
        created += 1
        print(f"  re-created audit {audit.id} ({engineer.name}, {machine.customer}/{machine.serial_number}, {len(audit_snapshot['results'])} results)")

    return created


# ---------- Main ----------

def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checklist-only",
        action="store_true",
        help=(
            "Only import checklist_data_v2.json (audit types/systems/sub-modules/checks). "
            "Skips customers.xlsx -> Machines and re-importing historical dev/test audits -- "
            "use this against a production database that should start clean of local dev data."
        ),
    )
    args = parser.parse_args()

    print("1. Capturing existing users (to preserve real passwords)...")
    existing_users = capture_existing_users()
    print(f"   Found {len(existing_users)} existing users.")

    print("2. Ensuring schema exists (creates any missing tables; never drops data)...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        if existing_users:
            print(f"   {len(existing_users)} user(s) already present -- left untouched.")
        else:
            from app.seed import ensure_seed_admin
            ensure_seed_admin(db)

        print("3. Importing checklist_data_v2.json...")
        stats = import_checklist_json(db)
        print(f"   {stats}")

        if args.checklist_only:
            print("--checklist-only set: skipping customers.xlsx import and historical audit re-import.")
        else:
            print("4. Importing customers.xlsx -> Machines...")
            machine_model_by_name: dict[str, models.MachineModel] = {}
            count = import_customers(db, machine_model_by_name)
            print(f"   Imported/ensured {count} machines.")

            print("5. Re-importing historical audits under a hidden Legacy audit type...")
            count = reimport_legacy_audits(db, machine_model_by_name)
            print(f"   Re-created {count} historical audits.")

        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
