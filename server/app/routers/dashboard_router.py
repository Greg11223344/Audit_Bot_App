from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

TREND_WEEKS = 12


@router.get("/kpis", response_model=schemas.KpiOut)
def kpis(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    not_deleted = models.Audit.is_deleted == False  # noqa: E712

    audits_this_month = (
        db.query(func.count(models.Audit.id))
        .filter(models.Audit.started_at >= month_start, not_deleted)
        .scalar()
        or 0
    )

    open_tasks = (
        db.query(func.count(models.Task.id))
        .join(models.Audit, models.Audit.id == models.Task.audit_id)
        .filter(models.Task.status != models.TaskStatus.closed, not_deleted)
        .scalar()
        or 0
    )

    total_results = (
        db.query(func.count(models.AuditResult.id))
        .join(models.Audit, models.Audit.id == models.AuditResult.audit_id)
        .filter(models.AuditResult.result != "", not_deleted)
        .scalar()
        or 0
    )
    fail_results = (
        db.query(func.count(models.AuditResult.id))
        .join(models.Audit, models.Audit.id == models.AuditResult.audit_id)
        .filter(models.AuditResult.result == "Fail", not_deleted)
        .scalar()
        or 0
    )
    fail_rate = round((fail_results / total_results) * 100, 1) if total_results else 0.0

    top_machines_rows = (
        db.query(
            models.Machine.id,
            models.Machine.customer,
            models.Machine.serial_number,
            func.count(models.AuditResult.id).label("findings"),
        )
        .join(models.Audit, models.Audit.machine_id == models.Machine.id)
        .join(models.AuditResult, models.AuditResult.audit_id == models.Audit.id)
        .filter(models.AuditResult.result.in_(["Fail", "Near Fail"]), not_deleted)
        .group_by(models.Machine.id)
        .order_by(func.count(models.AuditResult.id).desc())
        .limit(5)
        .all()
    )

    top_machines = [
        {"machine_id": row.id, "customer": row.customer, "serial_number": row.serial_number, "findings": row.findings}
        for row in top_machines_rows
    ]

    # Weekly audit-count trend for the last TREND_WEEKS weeks, bucketed in Python rather than
    # with Postgres date-truncation SQL -- keeps this simple and avoids depending on a specific
    # timezone/week-start convention on the DB side.
    trend_start = now - timedelta(weeks=TREND_WEEKS)
    week_counts = [0] * TREND_WEEKS
    recent_started_ats = (
        db.query(models.Audit.started_at)
        .filter(models.Audit.started_at >= trend_start, not_deleted)
        .all()
    )
    for (started_at,) in recent_started_ats:
        if started_at is None:
            continue
        weeks_ago = (now - started_at).days // 7
        index = TREND_WEEKS - 1 - weeks_ago
        if 0 <= index < TREND_WEEKS:
            week_counts[index] += 1

    audits_trend = []
    for i in range(TREND_WEEKS):
        week_date = (now - timedelta(weeks=TREND_WEEKS - 1 - i)).date()
        week_start = week_date - timedelta(days=week_date.weekday())
        audits_trend.append({"period": week_start.isoformat(), "count": week_counts[i]})

    return schemas.KpiOut(
        audits_this_month=audits_this_month,
        open_tasks=open_tasks,
        fail_rate_percent=fail_rate,
        top_machines_by_findings=top_machines,
        audits_trend=audits_trend,
    )
