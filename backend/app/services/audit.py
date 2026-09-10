"""Audit logging helper — every inspector/admin action worth keeping is recorded."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .. import models


def record(db: Session, *, actor_user: models.User | None = None, inspection_id: int | None = None,
           action: str, entity_type: str = "", entity_id: str = "",
           details: dict[str, Any] | None = None) -> None:
    db.add(models.AuditLog(
        inspection_id=inspection_id,
        actor_id=actor_user.id if actor_user else None,
        actor=actor_user.username if actor_user else "system",
        actor_role=actor_user.role if actor_user else "system",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
    ))
    db.commit()
