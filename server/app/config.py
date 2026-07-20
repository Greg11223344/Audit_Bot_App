import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Loads server/.env if present (local dev convenience only -- in production, env vars are set
# directly by the hosting platform, and there is no .env file in the deployed image/repo).
load_dotenv(BASE_DIR / ".env")

ENVIRONMENT = os.environ.get("AUDIT_BOT_ENVIRONMENT", "development")
IS_PRODUCTION = ENVIRONMENT == "production"

# Storage (uploaded photos, generated PDF reports): override with AUDIT_BOT_STORAGE_DIR to point
# at a mounted persistent volume in production -- most PaaS platforms wipe the local filesystem
# on every redeploy, so the default (a folder next to the code) only works for local dev.
STORAGE_DIR = Path(os.environ.get("AUDIT_BOT_STORAGE_DIR", str(BASE_DIR / "storage")))
ATTACHMENTS_DIR = STORAGE_DIR / "attachments"
REPORTS_DIR = STORAGE_DIR / "reports"

ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_database_url(url: str) -> str:
    # Render/Railway/Heroku-style managed Postgres add-ons hand out "postgres://" URLs, but
    # SQLAlchemy 1.4+ requires the "postgresql://" scheme -- and pin the driver explicitly so
    # it doesn't depend on whichever psycopg variant happens to be importable.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


# AUDIT_BOT_DATABASE_URL is this app's own explicit override. Falling back to plain DATABASE_URL
# matters because that's the exact variable name Render/Railway auto-inject when you attach
# their managed Postgres add-on -- no manual wiring needed if you just use their default name.
_raw_database_url = (
    os.environ.get("AUDIT_BOT_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or f"sqlite:///{BASE_DIR / 'audit_bot.db'}"
)
DATABASE_URL = _normalize_database_url(_raw_database_url)

SECRET_KEY = os.environ.get("AUDIT_BOT_SECRET_KEY", "dev-secret-change-me-in-production")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 14  # 14 days, field engineers need long offline sessions
