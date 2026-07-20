import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..audit_helpers import AUDIT_DETAIL_LOAD_OPTIONS, apply_critical_flag_tasks, load_audit, to_detail_out
from ..auth import get_current_user, require_roles
from ..config import ATTACHMENTS_DIR
from ..database import get_db

router = APIRouter(prefix="/api/audits", tags=["audits"])


@router.get("", response_model=list[schemas.AuditDetailOut])
def list_audits(
    status: str | None = None,
    machine_id: int | None = None,
    engineer_id: int | None = None,
    system_def_id: int | None = None,
    started_after: datetime | None = None,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    query = db.query(models.Audit).options(*AUDIT_DETAIL_LOAD_OPTIONS).filter(models.Audit.is_deleted == False)  # noqa: E712

    if status:
        query = query.filter(models.Audit.status == status)
    if machine_id:
        query = query.filter(models.Audit.machine_id == machine_id)
    if engineer_id:
        query = query.filter(models.Audit.engineer_id == engineer_id)
    if system_def_id:
        query = query.join(models.AuditSystem, models.AuditSystem.audit_id == models.Audit.id).filter(
            models.AuditSystem.system_def_id == system_def_id
        )
    if started_after:
        query = query.filter(models.Audit.started_at >= started_after)

    audits = query.order_by(models.Audit.updated_at.desc()).distinct().all()
    return [to_detail_out(a) for a in audits]


@router.get("/drafts", response_model=list[schemas.AuditDetailOut])
def list_open_drafts(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    """Open (draft) audits, visible to all field engineers so any of them can resume one (spec 5.3)."""
    audits = (
        db.query(models.Audit)
        .options(*AUDIT_DETAIL_LOAD_OPTIONS)
        .filter(models.Audit.status == models.AuditStatus.draft, models.Audit.is_deleted == False)  # noqa: E712
        .order_by(models.Audit.updated_at.desc())
        .all()
    )
    return [to_detail_out(a) for a in audits]


@router.get("/{audit_id}", response_model=schemas.AuditDetailOut)
def get_audit(audit_id: int, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    audit = load_audit(db, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")
    return to_detail_out(audit)


def _checklist_items_for_systems(db: Session, system_def_ids: list[int]) -> dict:
    items = (
        db.query(models.ChecklistItem)
        .join(models.SubModuleDef)
        .filter(models.SubModuleDef.system_def_id.in_(system_def_ids))
        .all()
    )
    return {item.id: item for item in items}


@router.post("/sync", response_model=schemas.SyncResponse)
def sync_audits(
    payload: schemas.SyncRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    response_items = []

    for incoming in payload.audits:
        existing = (
            db.query(models.Audit)
            .filter(models.Audit.client_uuid == incoming.client_uuid)
            .first()
        )

        if existing is not None and existing.is_deleted:
            # An admin deleted this audit server-side; the client must drop its local copy
            # rather than silently resurrecting it by treating "not found" as "create new".
            response_items.append(
                schemas.SyncResponseItem(client_uuid=incoming.client_uuid, status="deleted", audit=None)
            )
            continue

        if existing is not None and incoming.base_version != 0 and existing.version != incoming.base_version:
            # Someone else already pushed a newer version since this client last synced.
            # No silent auto-merge -- surface an explicit conflict (spec 4.2 / decision log 11).
            audit = load_audit(db, existing.id)
            response_items.append(
                schemas.SyncResponseItem(
                    client_uuid=incoming.client_uuid,
                    status="conflict",
                    conflict=schemas.SyncConflict(
                        client_uuid=incoming.client_uuid,
                        reason="Audit was updated from another source since your last sync.",
                        server_audit=to_detail_out(audit),
                    ),
                )
            )
            continue

        if existing is None:
            audit = models.Audit(
                client_uuid=incoming.client_uuid,
                machine_id=incoming.machine_id,
                engineer_id=current_user.id,
                audit_type=incoming.audit_type,
                status=models.AuditStatus(incoming.status),
                notes=incoming.notes,
                version=1,
                started_at=incoming.started_at or datetime.utcnow(),
                completed_at=incoming.completed_at,
            )
            db.add(audit)
            db.flush()
        else:
            audit = existing
            audit.audit_type = incoming.audit_type
            audit.status = models.AuditStatus(incoming.status)
            audit.notes = incoming.notes
            audit.completed_at = incoming.completed_at
            audit.version += 1

        # Sync chosen systems (replace set)
        db.query(models.AuditSystem).filter(models.AuditSystem.audit_id == audit.id).delete()
        for system_def_id in incoming.system_def_ids:
            db.add(models.AuditSystem(audit_id=audit.id, system_def_id=system_def_id))

        # Upsert results by checklist_item_id
        existing_results = {r.checklist_item_id: r for r in audit.results}
        for result_in in incoming.results:
            result_row = existing_results.get(result_in.checklist_item_id)
            if result_row is None:
                result_row = models.AuditResult(
                    audit_id=audit.id,
                    checklist_item_id=result_in.checklist_item_id,
                )
                db.add(result_row)
            result_row.result = result_in.result
            result_row.comment = result_in.comment
            result_row.flagged_critical = result_in.flagged_critical

        db.flush()
        db.refresh(audit)

        checklist_items_by_id = _checklist_items_for_systems(db, incoming.system_def_ids)
        apply_critical_flag_tasks(db, audit, checklist_items_by_id)

        db.commit()

        audit = load_audit(db, audit.id)
        response_items.append(
            schemas.SyncResponseItem(client_uuid=incoming.client_uuid, status="ok", audit=to_detail_out(audit))
        )

    return schemas.SyncResponse(results=response_items)


@router.post("/{audit_id}/attachments", response_model=schemas.AttachmentOut)
def upload_attachment(
    audit_id: int,
    client_uuid: str = Form(...),
    audit_result_id: int | None = Form(None),
    taken_at: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    audit = db.get(models.Audit, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    existing = db.query(models.Attachment).filter(models.Attachment.client_uuid == client_uuid).first()
    if existing is not None:
        return existing  # idempotent retry from an offline queue

    folder = ATTACHMENTS_DIR / str(audit_id)
    folder.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "photo.jpg").suffix or ".jpg"
    dest_path = folder / f"{client_uuid}{suffix}"

    with dest_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    parsed_taken_at = datetime.fromisoformat(taken_at) if taken_at else datetime.utcnow()

    attachment = models.Attachment(
        client_uuid=client_uuid,
        audit_id=audit_id,
        audit_result_id=audit_result_id,
        file_path=str(dest_path.relative_to(ATTACHMENTS_DIR.parent)),
        taken_at=parsed_taken_at,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


@router.delete("/{audit_id}", status_code=204)
def delete_audit(
    audit_id: int,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_roles("admin")),
):
    """Admin-only soft delete: keeps the row (and its results/attachments/tasks) for audit-trail
    purposes, but hides it from every normal read path immediately."""
    audit = load_audit(db, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    audit.is_deleted = True
    db.commit()
