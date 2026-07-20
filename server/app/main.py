import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import models
from .config import ATTACHMENTS_DIR, BASE_DIR, IS_PRODUCTION, SECRET_KEY
from .database import Base, SessionLocal, engine
from .routers import (
    audits_router,
    auth_router,
    catalog_router,
    dashboard_router,
    reports_router,
    tasks_router,
    users_router,
)
from .seed import ensure_seed_admin

if IS_PRODUCTION and SECRET_KEY == "dev-secret-change-me-in-production":
    raise RuntimeError(
        "AUDIT_BOT_ENVIRONMENT=production but AUDIT_BOT_SECRET_KEY is unset (still using the "
        "dev default). Set a real random secret before running in production -- e.g.: "
        "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )

Base.metadata.create_all(bind=engine)

db = SessionLocal()
try:
    ensure_seed_admin(db)
finally:
    db.close()

app = FastAPI(title="Audit_bot API")

app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(catalog_router.router)
app.include_router(audits_router.router)
app.include_router(tasks_router.router)
app.include_router(reports_router.router)
app.include_router(dashboard_router.router)

app.mount("/attachments", StaticFiles(directory=str(ATTACHMENTS_DIR)), name="attachments")

# Override with AUDIT_BOT_FIELD_APP_DIR/AUDIT_BOT_ADMIN_APP_DIR if a deployment platform lays
# the checked-out repo out differently than the local dev convention (field-app/admin-app as
# siblings of server/, i.e. BASE_DIR.parent).
FIELD_APP_DIR = Path(os.environ["AUDIT_BOT_FIELD_APP_DIR"]) if "AUDIT_BOT_FIELD_APP_DIR" in os.environ else BASE_DIR.parent / "field-app"
ADMIN_APP_DIR = Path(os.environ["AUDIT_BOT_ADMIN_APP_DIR"]) if "AUDIT_BOT_ADMIN_APP_DIR" in os.environ else BASE_DIR.parent / "admin-app"

if FIELD_APP_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(FIELD_APP_DIR), html=True), name="field-app")

if ADMIN_APP_DIR.exists():
    app.mount("/admin", StaticFiles(directory=str(ADMIN_APP_DIR), html=True), name="admin-app")


@app.get("/api/health")
def health():
    return {"status": "ok"}
