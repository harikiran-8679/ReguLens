"""Inspection lifecycle endpoints (create, read, update, navigate steps)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, serializers
from ..database import get_db
from ..deps import get_current_user, get_inspection_or_404, require_owner_or_admin
from ..schemas import InspectionCreate, InspectionUpdate, NavigateRequest
from ..services.audit import record
from ..services.pipeline import ensure_field_rows

router = APIRouter(prefix="/inspections", tags=["inspections"])


def _next_inspection_id(db: Session) -> str:
    year = dt.date.today().year
    count = db.query(models.Inspection).count() + 1
    for candidate in range(count, count + 500):
        code = f"LM-{year}-{candidate:05d}"
        if db.query(models.Inspection).filter(models.Inspection.inspection_id == code).first() is None:
            return code
    return f"LM-{year}-{count + 999:05d}"


@router.post("")
def create_inspection(body: InspectionCreate, db: Session = Depends(get_db),
                      user: models.User = Depends(get_current_user)):
    if user.role != "inspector":
        raise HTTPException(403, "Only inspectors can create inspections.")
    inspection = models.Inspection(
        inspection_id=_next_inspection_id(db),
        inspector_id=user.id,
        product_name=body.product_name,
        brand=body.brand,
        product_description=body.product_description,
        product_category=body.product_category,
        package_type=body.package_type,
        retailer_store=body.retailer_store,
        location=body.location,
        premises_type=body.premises_type,
        country_of_origin_claimed=body.country_of_origin_claimed,
        status="draft",
        current_step=1,
        inspection_date=dt.datetime.now(dt.timezone.utc),
    )
    if body.inspection_date:
        try:
            inspection.inspection_date = dt.datetime.fromisoformat(body.inspection_date.replace("Z", "+00:00"))
        except ValueError:
            pass
    db.add(inspection)
    db.commit()
    ensure_field_rows(db, inspection)
    record(db, actor_user=user, inspection_id=inspection.id, action="inspection_created",
           entity_type="inspection", entity_id=inspection.inspection_id)
    return serializers.inspection_full(inspection)


@router.get("")
def list_inspections(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
):
    query = db.query(models.Inspection)
    if user.role == "inspector":
        query = query.filter(models.Inspection.inspector_id == user.id)
    if status:
        query = query.filter(models.Inspection.status == status)
    if q:
        query = query.filter(models.Inspection.product_name.ilike(f"%{q}%")
                             | models.Inspection.inspection_id.ilike(f"%{q}%"))
    items = query.order_by(models.Inspection.id.desc()).limit(limit).all()
    return {"items": [serializers.inspection_brief(i) for i in items], "count": len(items)}


@router.get("/{inspection_id}")
def get_inspection(inspection_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    return serializers.inspection_full(inspection)


@router.patch("/{inspection_id}")
def update_inspection(inspection_id: int, body: InspectionUpdate,
                      db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(inspection, field, value)
    db.commit()
    record(db, actor_user=user, inspection_id=inspection.id, action="inspection_updated",
           entity_type="inspection", entity_id=inspection.inspection_id, details={"fields": list(body.model_dump(exclude_none=True))})
    return serializers.inspection_full(inspection)


@router.post("/{inspection_id}/navigate")
def navigate(inspection_id: int, body: NavigateRequest,
             db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Advance the workflow stepper. Status moves to PENDING_REVIEW once the
    inspector reaches the findings/review stages (steps 5-6)."""
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    if inspection.status == "finalized":
        raise HTTPException(400, "Inspection is finalised and read-only.")
    inspection.current_step = body.step
    if body.step >= 5 and inspection.status not in ("finalized", "pending_review"):
        inspection.status = "pending_review"
    if inspection.status == "draft" and body.step >= 2:
        inspection.status = "under_analysis"
    db.commit()
    record(db, actor_user=user, inspection_id=inspection.id, action="navigate_step",
           entity_type="inspection", entity_id=inspection.inspection_id, details={"step": body.step})
    return serializers.inspection_full(inspection)
