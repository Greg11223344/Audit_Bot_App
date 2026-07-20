from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[schemas.TaskOut])
def list_tasks(
    status: str | None = None,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    query = db.query(models.Task)
    if status:
        query = query.filter(models.Task.status == status)
    return query.order_by(models.Task.created_at.desc()).all()


@router.put("/{task_id}", response_model=schemas.TaskOut)
def update_task(
    task_id: int,
    payload: schemas.TaskUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    task = db.get(models.Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    data = payload.model_dump(exclude_unset=True)

    if "status" in data and data["status"] is not None:
        if data["status"] not in [s.value for s in models.TaskStatus]:
            raise HTTPException(status_code=400, detail="Invalid status")
        task.status = models.TaskStatus(data["status"])
        if task.status == models.TaskStatus.closed:
            task.closed_at = datetime.utcnow()
        else:
            task.closed_at = None

    if "assignee_id" in data:
        task.assignee_id = data["assignee_id"]

    if "resolution_note" in data and data["resolution_note"] is not None:
        task.resolution_note = data["resolution_note"]

    db.commit()
    db.refresh(task)
    return task
