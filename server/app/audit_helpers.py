from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from . import models, schemas


AUDIT_DETAIL_LOAD_OPTIONS = [
    joinedload(models.Audit.machine).joinedload(models.Machine.machine_model),
    joinedload(models.Audit.engineer),
    joinedload(models.Audit.systems),
    joinedload(models.Audit.results)
    .joinedload(models.AuditResult.checklist_item)
    .joinedload(models.ChecklistItem.sub_module)
    .joinedload(models.SubModuleDef.system_def),
    joinedload(models.Audit.attachments),
    joinedload(models.Audit.tasks),
]


def load_audit(db: Session, audit_id: int, include_deleted: bool = False) -> models.Audit | None:
    query = db.query(models.Audit).options(*AUDIT_DETAIL_LOAD_OPTIONS).filter(models.Audit.id == audit_id)
    if not include_deleted:
        query = query.filter(models.Audit.is_deleted == False)  # noqa: E712
    return query.first()


def result_to_out(result: models.AuditResult) -> schemas.AuditResultOut:
    item = result.checklist_item
    sub_module = item.sub_module if item else None
    system = sub_module.system_def if sub_module else None
    return schemas.AuditResultOut(
        id=result.id,
        checklist_item_id=result.checklist_item_id,
        result=result.result,
        comment=result.comment,
        flagged_critical=result.flagged_critical,
        updated_at=result.updated_at,
        description=item.description if item else "",
        sub_module_name=sub_module.name if sub_module else "",
        system_name=system.name if system else "",
    )


def to_detail_out(audit: models.Audit) -> schemas.AuditDetailOut:
    return schemas.AuditDetailOut(
        id=audit.id,
        client_uuid=audit.client_uuid,
        machine_id=audit.machine_id,
        engineer_id=audit.engineer_id,
        audit_type=audit.audit_type,
        status=audit.status.value,
        notes=audit.notes or "",
        version=audit.version,
        started_at=audit.started_at,
        completed_at=audit.completed_at,
        updated_at=audit.updated_at,
        machine=schemas.MachineOut.model_validate(audit.machine),
        engineer=schemas.UserOut.model_validate(audit.engineer),
        system_def_ids=[link.system_def_id for link in audit.systems],
        results=[result_to_out(r) for r in audit.results],
        attachments=[schemas.AttachmentOut.model_validate(a) for a in audit.attachments],
        tasks=[schemas.TaskOut.model_validate(t) for t in audit.tasks],
    )


def apply_critical_flag_tasks(db: Session, audit: models.Audit, checklist_items_by_id: dict):
    for result in audit.results:
        existing_task = (
            db.query(models.Task).filter(models.Task.audit_result_id == result.id).first()
        )

        if result.flagged_critical and existing_task is None:
            item = checklist_items_by_id.get(result.checklist_item_id)
            description = item.description if item else "Critical issue flagged"
            db.add(
                models.Task(
                    audit_id=audit.id,
                    audit_result_id=result.id,
                    description=description,
                    status=models.TaskStatus.open,
                )
            )
        elif not result.flagged_critical and existing_task is not None and existing_task.status != models.TaskStatus.closed:
            existing_task.status = models.TaskStatus.closed
            existing_task.closed_at = datetime.utcnow()
            existing_task.resolution_note = (existing_task.resolution_note or "") + "\n[Auto-closed: item unflagged]"
