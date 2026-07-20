import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


def new_uuid() -> str:
    return str(uuid.uuid4())


class UserRole(str, enum.Enum):
    field_engineer = "field_engineer"
    internal = "internal"
    admin = "admin"


class AuditStatus(str, enum.Enum):
    draft = "draft"
    completed = "completed"


class ResultValue(str, enum.Enum):
    not_checked = ""
    pass_ = "Pass"
    near_fail = "Near Fail"
    fail = "Fail"
    na = "N/A"


class TaskStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    closed = "closed"


class SyncStatus(str, enum.Enum):
    pending = "pending"
    synced = "synced"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    email = Column(String(200), nullable=False, unique=True, index=True)
    password_hash = Column(String(200), nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.field_engineer)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    audits = relationship("Audit", back_populates="engineer")
    assigned_tasks = relationship("Task", back_populates="assignee")


class MachineModel(Base):
    __tablename__ = "machine_models"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    machines = relationship("Machine", back_populates="machine_model")


class Machine(Base):
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True)
    machine_model_id = Column(Integer, ForeignKey("machine_models.id"), nullable=False)
    serial_number = Column(String(120), nullable=False, index=True)
    customer = Column(String(200), nullable=False)
    site = Column(String(200), default="")
    region = Column(String(120), default="")
    engineer_owner = Column(String(120), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("serial_number", "customer", name="uq_machine_serial_customer"),)

    machine_model = relationship("MachineModel", back_populates="machines")
    audits = relationship("Audit", back_populates="machine")


class AuditType(Base):
    """A distinct audit procedure with its own system/checklist content (e.g. Machine Audit vs
    Post Installation Audit). The user picks one of these before picking systems to check."""

    __tablename__ = "audit_types"

    id = Column(Integer, primary_key=True)
    key = Column(String(80), nullable=False, unique=True)
    label = Column(String(200), nullable=False)
    order_index = Column(Integer, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    # Inactive audit types (e.g. a "legacy" bucket holding pre-migration data under its old,
    # since-superseded content) are hidden from the new-audit flow but still resolve historically.
    created_at = Column(DateTime, default=datetime.utcnow)

    systems = relationship("SystemDef", back_populates="audit_type", cascade="all, delete-orphan")


class SystemDef(Base):
    """A checkable subsystem/component within an audit type (e.g. PreFeeder, Dryer)."""

    __tablename__ = "system_defs"

    id = Column(Integer, primary_key=True)
    audit_type_id = Column(Integer, ForeignKey("audit_types.id"), nullable=False)
    name = Column(String(200), nullable=False)
    order_index = Column(Integer, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    audit_type = relationship("AuditType", back_populates="systems")
    sub_modules = relationship(
        "SubModuleDef", back_populates="system_def", cascade="all, delete-orphan", order_by="SubModuleDef.order_index"
    )
    audit_links = relationship("AuditSystem", back_populates="system_def")


class SubModuleDef(Base):
    """A named grouping of checks within a system (e.g. 'Pistons', 'Tornado'). Drives the
    checklist screen's section headings so a field engineer can see what they're checking."""

    __tablename__ = "sub_module_defs"

    id = Column(Integer, primary_key=True)
    system_def_id = Column(Integer, ForeignKey("system_defs.id"), nullable=False)
    name = Column(String(200), nullable=False)
    order_index = Column(Integer, default=0)

    system_def = relationship("SystemDef", back_populates="sub_modules")
    items = relationship(
        "ChecklistItem", back_populates="sub_module", cascade="all, delete-orphan", order_by="ChecklistItem.order_index"
    )


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id = Column(Integer, primary_key=True)
    sub_module_id = Column(Integer, ForeignKey("sub_module_defs.id"), nullable=False)
    description = Column(Text, nullable=False)
    requires_photo = Column(Boolean, default=False)
    order_index = Column(Integer, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    # Inactive items are hidden from new audits (e.g. retired bad data) but stay in the DB so
    # historical AuditResults that already reference them keep resolving correctly.

    sub_module = relationship("SubModuleDef", back_populates="items")
    results = relationship("AuditResult", back_populates="checklist_item")


class Audit(Base):
    __tablename__ = "audits"

    id = Column(Integer, primary_key=True)
    client_uuid = Column(String(36), nullable=False, unique=True, default=new_uuid, index=True)
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=False)
    engineer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    audit_type = Column(String(120), default="Full Audit")
    status = Column(Enum(AuditStatus), nullable=False, default=AuditStatus.draft)
    notes = Column(Text, default="")
    version = Column(Integer, nullable=False, default=1)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, nullable=False, default=False)
    # Soft delete (admin-only): keeps the row -- and its results/attachments/tasks -- for audit
    # trail purposes, but hidden from every normal read path (list, drafts, get, dashboard, sync).

    machine = relationship("Machine", back_populates="audits")
    engineer = relationship("User", back_populates="audits")
    systems = relationship("AuditSystem", back_populates="audit", cascade="all, delete-orphan")
    results = relationship("AuditResult", back_populates="audit", cascade="all, delete-orphan")
    attachments = relationship("Attachment", back_populates="audit", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="audit", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="audit", cascade="all, delete-orphan")


class AuditSystem(Base):
    __tablename__ = "audit_systems"

    id = Column(Integer, primary_key=True)
    audit_id = Column(Integer, ForeignKey("audits.id"), nullable=False)
    system_def_id = Column(Integer, ForeignKey("system_defs.id"), nullable=False)

    __table_args__ = (UniqueConstraint("audit_id", "system_def_id", name="uq_audit_system"),)

    audit = relationship("Audit", back_populates="systems")
    system_def = relationship("SystemDef", back_populates="audit_links")


class AuditResult(Base):
    __tablename__ = "audit_results"

    id = Column(Integer, primary_key=True)
    audit_id = Column(Integer, ForeignKey("audits.id"), nullable=False)
    checklist_item_id = Column(Integer, ForeignKey("checklist_items.id"), nullable=False)
    result = Column(String(20), default="")
    comment = Column(Text, default="")
    flagged_critical = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("audit_id", "checklist_item_id", name="uq_audit_checklist_item"),)

    audit = relationship("Audit", back_populates="results")
    checklist_item = relationship("ChecklistItem", back_populates="results")
    attachments = relationship("Attachment", back_populates="audit_result")
    task = relationship("Task", back_populates="audit_result", uselist=False)


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True)
    client_uuid = Column(String(36), nullable=False, unique=True, default=new_uuid, index=True)
    audit_id = Column(Integer, ForeignKey("audits.id"), nullable=False)
    audit_result_id = Column(Integer, ForeignKey("audit_results.id"), nullable=True)
    file_path = Column(String(500), nullable=False)
    taken_at = Column(DateTime, default=datetime.utcnow)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    audit = relationship("Audit", back_populates="attachments")
    audit_result = relationship("AuditResult", back_populates="attachments")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    audit_id = Column(Integer, ForeignKey("audits.id"), nullable=False)
    audit_result_id = Column(Integer, ForeignKey("audit_results.id"), nullable=True, unique=True)
    description = Column(Text, default="")
    status = Column(Enum(TaskStatus), nullable=False, default=TaskStatus.open)
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolution_note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    audit = relationship("Audit", back_populates="tasks")
    audit_result = relationship("AuditResult", back_populates="task")
    assignee = relationship("User", back_populates="assigned_tasks")


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    audit_id = Column(Integer, ForeignKey("audits.id"), nullable=False)
    file_path = Column(String(500), nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow)

    audit = relationship("Audit", back_populates="reports")
