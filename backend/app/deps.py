"""FastAPI dependencies for auth + role checks."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .security import decode_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> models.User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")
    user = db.query(models.User).filter(models.User.username == payload.get("sub")).first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found.")
    if user.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is not active.")
    return user


def require_roles(*roles: str):
    def _dep(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions.")
        return user

    return _dep


def require_owner_or_admin(inspection: models.Inspection, user: models.User) -> None:
    if user.role != "admin" and inspection.inspector_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Inspection does not belong to this inspector.")


def get_inspection_or_404(inspection_id: int, db: Session) -> models.Inspection:
    inspection = db.query(models.Inspection).filter(models.Inspection.id == inspection_id).first()
    if inspection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inspection not found.")
    return inspection
