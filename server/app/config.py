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
    # Supabase (and Render/Railway/Heroku-style add-ons) hand out "postgres://" URLs, but
    # SQLAlchemy 1.4+ requires the "postgresql://" scheme -- and pin the driver explicitly so
    # it doesn't depend on whichever psycopg variant happens to be importable.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


# Postgres is the only supported database -- no local-file fallback. AUDIT_BOT_DATABASE_URL is
# this app's own explicit variable; falling back to plain DATABASE_URL matters because that's
# the name most platforms (Render, Railway, Supabase docs) use by convention.
_raw_database_url = os.environ.get("AUDIT_BOT_DATABASE_URL") or os.environ.get("DATABASE_URL")
if not _raw_database_url:
    raise RuntimeError(
        "No database configured. Set DATABASE_URL (or AUDIT_BOT_DATABASE_URL) to your Postgres "
        "connection string, e.g.: "
        "postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres"
    )
DATABASE_URL = _normalize_database_url(_raw_database_url)

# Who may embed the front-ends in an <iframe> (sent as CSP frame-ancestors on every response).
# Default: this server itself plus the Microsoft Teams hosts, so /app/ and /admin/ can run as a
# Teams tab without being framable by arbitrary sites. teams.cloud.microsoft is the new Teams web
# client's address. Override with a space- or comma-separated list in AUDIT_BOT_FRAME_ANCESTORS.
_DEFAULT_FRAME_ANCESTORS = (
    "'self' https://teams.microsoft.com https://*.teams.microsoft.com "
    "https://*.office.com https://teams.cloud.microsoft"
)
_raw_frame_ancestors = os.environ.get("AUDIT_BOT_FRAME_ANCESTORS", "").strip() or _DEFAULT_FRAME_ANCESTORS
FRAME_ANCESTORS = " ".join(a for a in _raw_frame_ancestors.replace(",", " ").split() if a)

SECRET_KEY = os.environ.get("AUDIT_BOT_SECRET_KEY", "dev-secret-change-me-in-production")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 14  # 14 days, field engineers need long offline sessions
