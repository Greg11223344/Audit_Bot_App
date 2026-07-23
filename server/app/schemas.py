from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr


# ---------- Auth ----------

class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


# ---------- User ----------

class UserBase(BaseModel):
    name: str
    email: str
    role: str = "field_engineer"


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class UserOut(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool


# ---------- MachineModel ----------

class MachineModelCreate(BaseModel):
    name: str


class MachineModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


# ---------- Machine ----------

class MachineCreate(BaseModel):
    machine_model_id: int
    serial_number: str
    customer: str
    site: str = ""
    region: str = ""
    engineer_owner: str = ""


class MachineUpdate(BaseModel):
    serial_number: Optional[str] = None
    customer: Optional[str] = None
    site: Optional[str] = None
    region: Optional[str] = None
    engineer_owner: Optional[str] = None


class MachineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    machine_model_id: int
    serial_number: str
    customer: str
    site: str
    region: str
    engineer_owner: str
    machine_model: MachineModelOut


# ---------- Audit Types / Systems / Sub-Modules / Checklist ----------

class AuditTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    label_en: str
    label_he: str
    order_index: int


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    description: str
    requires_photo: bool
    order_index: int
    is_active: bool = True


class SubModuleDefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    order_index: int
    items: list[ChecklistItemOut] = []


class SystemDefCreate(BaseModel):
    audit_type_id: int
    name: str
    order_index: int = 0


class SystemDefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    audit_type_id: int
    name: str
    order_index: int
    sub_modules: list[SubModuleDefOut] = []


# ---------- Audit ----------

class AuditResultIn(BaseModel):
    checklist_item_id: int
    result: str = ""
    comment: str = ""
    flagged_critical: bool = False


class AuditCreate(BaseModel):
    client_uuid: Optional[str] = None
    machine_id: int
    audit_type: str = "Full Audit"
    system_def_ids: list[int]


class AuditResultOut(BaseModel):
    id: int
    checklist_item_id: int
    result: str
    comment: str
    flagged_critical: bool
    updated_at: datetime
    description: str
    sub_module_name: str
    system_name: str


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_uuid: str
    audit_result_id: Optional[int]
    file_path: str
    taken_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    audit_id: int
    audit_result_id: Optional[int]
    description: str
    status: str
    assignee_id: Optional[int]
    resolution_note: str
    created_at: datetime
    closed_at: Optional[datetime]


class TaskUpdate(BaseModel):
    status: Optional[str] = None
    assignee_id: Optional[int] = None
    resolution_note: Optional[str] = None


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    client_uuid: str
    machine_id: int
    engineer_id: int
    audit_type: str
    status: str
    notes: str
    version: int
    started_at: datetime
    completed_at: Optional[datetime]
    updated_at: datetime


class AuditDetailOut(AuditOut):
    machine: MachineOut
    engineer: UserOut
    system_def_ids: list[int]
    results: list[AuditResultOut]
    attachments: list[AttachmentOut]
    tasks: list[TaskOut]


# ---------- Sync ----------

class SyncResultIn(BaseModel):
    checklist_item_id: int
    result: str = ""
    comment: str = ""
    flagged_critical: bool = False


class SyncAuditIn(BaseModel):
    client_uuid: str
    base_version: int = 0  # version the client last synced from; 0 for brand-new audit
    machine_id: int
    audit_type: str = "Full Audit"
    system_def_ids: list[int]
    status: str = "draft"
    notes: str = ""
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    results: list[SyncResultIn] = []


class SyncConflict(BaseModel):
    client_uuid: str
    reason: str
    server_audit: AuditDetailOut


class SyncResponseItem(BaseModel):
    client_uuid: str
    status: str  # "ok" | "conflict" | "deleted"
    audit: Optional[AuditDetailOut] = None
    conflict: Optional[SyncConflict] = None


class SyncRequest(BaseModel):
    audits: list[SyncAuditIn]


class SyncResponse(BaseModel):
    results: list[SyncResponseItem]


# ---------- Dashboard ----------

class KpiOut(BaseModel):
    audits_this_month: int
    open_tasks: int
    fail_rate_percent: float
    top_machines_by_findings: list[dict]
    audits_trend: list[dict] = []
