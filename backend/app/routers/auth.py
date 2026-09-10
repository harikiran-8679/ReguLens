"""Authentication endpoints. No self-registration exists: accounts are
provisioned by an administrator (see admin router)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

from .. import models, serializers
from ..database import get_db
from ..deps import get_current_user
from ..schemas import LoginRequest
from ..security import create_access_token, verify_password
from ..services.audit import record

router = APIRouter(tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == body.username.strip()).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid username or password.")
    if user.status == "pending":
        raise HTTPException(403, "Your account has not yet been activated. Please contact your administrator.")
    if user.status == "inactive":
        raise HTTPException(403, "Your access is currently inactive. Please contact your administrator.")
    user.last_active_at = dt.datetime.now(dt.timezone.utc)
    token = create_access_token(user.username, user.role, {"uid": user.id})
    db.commit()
    record(db, actor_user=user, action="login", entity_type="user", entity_id=user.username)
    return {"token": token, "token_type": "bearer", "user": serializers.user_dict(user)}


@router.get("/me")
def me(user: models.User = Depends(get_current_user)):
    return serializers.user_dict(user)
