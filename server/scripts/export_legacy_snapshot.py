"""Safety-net export of every real audit currently in the DB, taken right before the
AuditType -> System -> SubModule -> ChecklistItem schema migration. Captures everything needed
to recreate these audits faithfully under the new schema: machine/engineer identity, each
result's full item text (module/sub_module/description/check_number as they existed), photos,
tasks, and reports.
"""
import json
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402

OUT_PATH = SERVER_DIR / "scripts" / "legacy_audit_snapshot.json"


def main():
    db = SessionLocal()
    try:
        audits = db.query(models.Audit).order_by(models.Audit.id).all()
        snapshot = []

        for audit in audits:
            snapshot.append(
                {
                    "id": audit.id,
                    "client_uuid": audit.client_uuid,
                    "audit_type_label": audit.audit_type,
                    "status": audit.status.value,
                    "notes": audit.notes,
                    "version": audit.version,
                    "started_at": audit.started_at.isoformat() if audit.started_at else None,
                    "completed_at": audit.completed_at.isoformat() if audit.completed_at else None,
                    "updated_at": audit.updated_at.isoformat() if audit.updated_at else None,
                    "machine": {
                        "serial_number": audit.machine.serial_number,
                        "customer": audit.machine.customer,
                        "site": audit.machine.site,
                        "region": audit.machine.region,
                        "engineer_owner": audit.machine.engineer_owner,
                        "machine_model_name": audit.machine.machine_model.name,
                    },
                    "engineer": {
                        "name": audit.engineer.name,
                        "email": audit.engineer.email,
                        "role": audit.engineer.role.value,
                    },
                    "systems": [
                        {"name": link.system_def.name} for link in audit.systems
                    ],
                    "results": [
                        {
                            "module": r.checklist_item.module,
                            "sub_module": r.checklist_item.sub_module,
                            "check_number": r.checklist_item.check_number,
                            "description": r.checklist_item.description,
                            "result": r.result,
                            "comment": r.comment,
                            "flagged_critical": r.flagged_critical,
                            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                        }
                        for r in audit.results
                    ],
                    "attachments": [
                        {
                            "client_uuid": a.client_uuid,
                            "file_path": a.file_path,
                            "taken_at": a.taken_at.isoformat() if a.taken_at else None,
                            "result_item_description": a.audit_result.checklist_item.description
                            if a.audit_result
                            else None,
                            "result_item_module": a.audit_result.checklist_item.module if a.audit_result else None,
                        }
                        for a in audit.attachments
                    ],
                    "tasks": [
                        {
                            "description": task.description,
                            "status": task.status.value,
                            "resolution_note": task.resolution_note,
                            "created_at": task.created_at.isoformat() if task.created_at else None,
                            "closed_at": task.closed_at.isoformat() if task.closed_at else None,
                            "result_item_description": task.audit_result.checklist_item.description
                            if task.audit_result
                            else None,
                        }
                        for task in audit.tasks
                    ],
                    "reports": [
                        {"file_path": r.file_path, "generated_at": r.generated_at.isoformat()}
                        for r in audit.reports
                    ],
                }
            )

        OUT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Exported {len(snapshot)} audits to {OUT_PATH}")
        for a in snapshot:
            print(f"  audit {a['id']}: {a['engineer']['name']}, {len(a['results'])} results, {len(a['attachments'])} attachments")
    finally:
        db.close()


if __name__ == "__main__":
    main()
