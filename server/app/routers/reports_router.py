from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models
from ..audit_helpers import load_audit
from ..auth import get_current_user
from ..database import get_db
from ..pdf_report import generate_audit_pdf

router = APIRouter(prefix="/api/audits", tags=["reports"])


@router.post("/{audit_id}/report")
def generate_report(audit_id: int, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    audit = load_audit(db, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    file_path = generate_audit_pdf(audit)

    report = models.Report(audit_id=audit.id, file_path=str(file_path))
    db.add(report)
    db.commit()
    db.refresh(report)

    return {"report_id": report.id, "download_url": f"/api/audits/{audit_id}/report/{report.id}/download"}


@router.get("/{audit_id}/report/{report_id}/download")
def download_report(
    audit_id: int, report_id: int, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    report = db.get(models.Report, report_id)
    if report is None or report.audit_id != audit_id:
        raise HTTPException(status_code=404, detail="Report not found")

    return FileResponse(report.file_path, media_type="application/pdf", filename=f"audit_{audit_id}_report.pdf")
