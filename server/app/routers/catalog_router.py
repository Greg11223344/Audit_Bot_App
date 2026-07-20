from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas
from ..auth import get_current_user, require_roles
from ..database import get_db

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


# ---------- Machine Models ----------

@router.get("/machine-models", response_model=list[schemas.MachineModelOut])
def list_machine_models(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return db.query(models.MachineModel).order_by(models.MachineModel.name).all()


@router.post("/machine-models", response_model=schemas.MachineModelOut)
def create_machine_model(
    payload: schemas.MachineModelCreate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_roles("admin")),
):
    existing = db.query(models.MachineModel).filter(models.MachineModel.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Machine model with this name already exists")

    machine_model = models.MachineModel(name=payload.name)
    db.add(machine_model)
    db.commit()
    db.refresh(machine_model)
    return machine_model


# ---------- Machines ----------

@router.get("/machines", response_model=list[schemas.MachineOut])
def list_machines(
    search: str = "",
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    query = db.query(models.Machine).options(joinedload(models.Machine.machine_model))

    if search:
        like = f"%{search}%"
        query = query.filter(
            (models.Machine.serial_number.ilike(like))
            | (models.Machine.customer.ilike(like))
            | (models.Machine.site.ilike(like))
        )

    return query.order_by(models.Machine.customer).all()


@router.post("/machines", response_model=schemas.MachineOut)
def create_machine(
    payload: schemas.MachineCreate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_roles("admin")),
):
    machine_model = db.get(models.MachineModel, payload.machine_model_id)
    if machine_model is None:
        raise HTTPException(status_code=404, detail="Machine model not found")

    machine = models.Machine(**payload.model_dump())
    db.add(machine)
    db.commit()
    db.refresh(machine)
    return machine


@router.put("/machines/{machine_id}", response_model=schemas.MachineOut)
def update_machine(
    machine_id: int,
    payload: schemas.MachineUpdate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_roles("admin")),
):
    machine = db.get(models.Machine, machine_id)
    if machine is None:
        raise HTTPException(status_code=404, detail="Machine not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(machine, field, value)

    db.commit()
    db.refresh(machine)
    return machine


# ---------- Audit Types ----------

@router.get("/audit-types", response_model=list[schemas.AuditTypeOut])
def list_audit_types(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return (
        db.query(models.AuditType)
        .filter(models.AuditType.is_active == True)  # noqa: E712
        .order_by(models.AuditType.order_index)
        .all()
    )


# ---------- Systems / Sub-Modules / Checklist ----------

@router.get("/system-defs", response_model=list[schemas.SystemDefOut])
def list_system_defs(
    audit_type_id: int | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    # include_inactive is for admin display purposes only (e.g. resolving a legacy audit's
    # system name) -- the field-app's new-audit flow must never pass it, since inactive/legacy
    # systems (see rebuild_and_seed.py) exist only to keep old audits resolving, not to be
    # offered again.
    query = db.query(models.SystemDef).options(
        joinedload(models.SystemDef.sub_modules).joinedload(models.SubModuleDef.items)
    )

    if audit_type_id is not None:
        query = query.filter(models.SystemDef.audit_type_id == audit_type_id)
    if not include_inactive:
        query = query.filter(models.SystemDef.is_active == True)  # noqa: E712

    system_defs = query.order_by(models.SystemDef.order_index).all()

    # Inactive items (retired bad data, e.g. the matrix-parser header-row bug) must never be
    # offered on a *new* audit, even though they stay in the DB for old audits that already
    # reference them (see ChecklistItem.is_active).
    result = []
    for sd in system_defs:
        sub_modules_out = []
        for sm in sd.sub_modules:
            active_items = sorted((i for i in sm.items if i.is_active), key=lambda i: i.order_index)
            if not active_items:
                continue
            sub_modules_out.append(
                schemas.SubModuleDefOut(
                    id=sm.id,
                    name=sm.name,
                    order_index=sm.order_index,
                    items=[schemas.ChecklistItemOut.model_validate(i) for i in active_items],
                )
            )
        result.append(
            schemas.SystemDefOut(
                id=sd.id,
                audit_type_id=sd.audit_type_id,
                name=sd.name,
                order_index=sd.order_index,
                sub_modules=sub_modules_out,
            )
        )
    return result


@router.post("/system-defs", response_model=schemas.SystemDefOut)
def create_system_def(
    payload: schemas.SystemDefCreate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_roles("admin")),
):
    audit_type = db.get(models.AuditType, payload.audit_type_id)
    if audit_type is None:
        raise HTTPException(status_code=404, detail="Audit type not found")

    system_def = models.SystemDef(**payload.model_dump())
    db.add(system_def)
    db.commit()
    db.refresh(system_def)
    return system_def


# ---------- Users (admin) ----------

@router.get("/users", response_model=list[schemas.UserOut])
def list_users(db: Session = Depends(get_db), _admin: models.User = Depends(require_roles("admin"))):
    return db.query(models.User).order_by(models.User.name).all()
