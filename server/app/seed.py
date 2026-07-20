import os

from sqlalchemy.orm import Session

from . import models
from .auth import hash_password
from .config import IS_PRODUCTION

DEFAULT_ADMIN_EMAIL = "admin@auditbot.local"
DEFAULT_ADMIN_PASSWORD = "ChangeMe123!"


def ensure_seed_admin(db: Session) -> None:
    has_any_user = db.query(models.User).first() is not None
    if has_any_user:
        return

    email = os.environ.get("AUDIT_BOT_ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL)
    password = os.environ.get("AUDIT_BOT_ADMIN_PASSWORD")

    if password is None:
        if IS_PRODUCTION:
            raise RuntimeError(
                "AUDIT_BOT_ENVIRONMENT=production but AUDIT_BOT_ADMIN_PASSWORD is not set -- "
                "refusing to seed the first admin account with the well-known dev default "
                "password. Set AUDIT_BOT_ADMIN_PASSWORD (and optionally AUDIT_BOT_ADMIN_EMAIL) "
                "and restart."
            )
        password = DEFAULT_ADMIN_PASSWORD

    admin = models.User(
        name="Admin",
        email=email,
        role=models.UserRole.admin,
        password_hash=hash_password(password),
    )
    db.add(admin)
    db.commit()

    print("=" * 60)
    print("Audit_bot: created default admin user")
    print(f"  email:    {email}")
    if password == DEFAULT_ADMIN_PASSWORD:
        print(f"  password: {password}")
        print("  Please change this password after first login.")
    else:
        print("  password: (set via AUDIT_BOT_ADMIN_PASSWORD)")
    print("=" * 60)
