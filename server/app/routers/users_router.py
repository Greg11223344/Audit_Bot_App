from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import hash_password, require_roles
from ..database import get_db

router = APIRouter(prefix="/api/users", tags=["users"])


@router.post("", response_model=schemas.UserOut)
def create_user(
    payload: schemas.UserCreate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_roles("admin")),
):
    email = payload.email.strip().lower()
    existing = db.query(models.User).filter(models.User.email == email).first()
    if existing:
        raise HTTPException(status_code=409, detail="A user with this email already exists")

    if payload.role not in [role.value for role in models.UserRole]:
        raise HTTPException(status_code=400, detail="Invalid role")

    user = models.User(
        name=payload.name,
        email=email,
        role=models.UserRole(payload.role),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    payload: schemas.UserUpdate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(require_roles("admin")),
):
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    data = payload.model_dump(exclude_unset=True)

    if "password" in data:
        password = data.pop("password")
        if password:
            user.password_hash = hash_password(password)

    if "role" in data and data["role"] is not None:
        if data["role"] not in [role.value for role in models.UserRole]:
            raise HTTPException(status_code=400, detail="Invalid role")
        user.role = models.UserRole(data.pop("role"))

    for field, value in data.items():
        if value is not None:
            setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user
