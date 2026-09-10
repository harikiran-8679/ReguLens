"""Dashboard aggregates for the inspector workspace and the admin control room."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, serializers
from ..database import get_db
from ..deps import get_current_user, require_roles
from ..utils import FINAL_COMPLIANT, FINAL_NON_COMPLIANT

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _status_counts(db: Session, base_query) -> dict:
    rows = db.query(models.Inspection.status, func.count(models.Inspection.id)).group_by(
        models.Inspection.status).all()
    return {k: v for k, v in rows}


@router.get("/inspector")
def inspector_dashboard(db: Session = Depends(get_db),
                        user: models.User = Depends(get_current_user)):
    inspections = db.query(models.Inspection).filter(
        models.Inspection.inspector_id == user.id).order_by(models.Inspection.id.desc()).all()

    total = len(inspections)
    compliant = len([i for i in inspections if i.status == "finalized" and i.final_compliance_status == FINAL_COMPLIANT])
    non_compliant = len([i for i in inspections if i.status == "finalized" and i.final_compliance_status == FINAL_NON_COMPLIANT])
    pending_review = len([i for i in inspections if i.status == "pending_review"])
    drafts = len([i for i in inspections if i.status == "draft"])

    # outcome chart across analysed/finalised records (automated result, distinct from status)
    outcome: dict[str, int] = {}
    for i in inspections:
        if i.automated_result:
            outcome[i.automated_result] = outcome.get(i.automated_result, 0) + 1

    recent = [serializers.inspection_brief(i) for i in inspections[:6]]
    pending = [serializers.inspection_brief(i) for i in inspections if i.status == "pending_review"][:8]
    return {
        "stats": {
            "total": total, "compliant": compliant, "non_compliant": non_compliant,
            "pending_review": pending_review, "drafts": drafts,
        },
        "outcome_chart": outcome,
        "recent": recent,
        "pending": pending,
        "notifications": _inspector_notifications(db, user),
    }


def _inspector_notifications(db: Session, user: models.User) -> list[dict]:
    items = []
    pending = db.query(models.Inspection).filter(
        models.Inspection.inspector_id == user.id,
        models.Inspection.status == "pending_review").count()
    if pending:
        items.append({"type": "warning", "text": f"{pending} inspection(s) require your review."})
    reports = db.query(models.Report).join(models.Inspection).filter(
        models.Inspection.inspector_id == user.id).count()
    if reports:
        items.append({"type": "info", "text": f"{reports} report(s) generated in your history."})
    ocr_todo = db.query(models.Inspection).filter(
        models.Inspection.inspector_id == user.id,
        models.Inspection.status.in_(["draft", "under_analysis"])).count()
    if ocr_todo:
        items.append({"type": "info", "text": f"{ocr_todo} draft inspection(s) awaiting capture / OCR."})
    if not items:
        items.append({"type": "info", "text": "No pending notifications."})
    return items


@router.get("/admin")
def admin_dashboard(db: Session = Depends(get_db),
                    _: models.User = Depends(require_roles("admin"))):
    inspectors = db.query(models.User).filter(models.User.role == "inspector").all()
    inspections = db.query(models.Inspection).order_by(models.Inspection.id.desc()).all()

    total_inspectors = len(inspectors)
    active = len([u for u in inspectors if u.status == "active"])
    pending_access = len([u for u in inspectors if u.status == "pending"])
    inactive = len([u for u in inspectors if u.status == "inactive"])

    total_inspections = len(inspections)
    compliant = len([i for i in inspections if i.status == "finalized" and i.final_compliance_status == FINAL_COMPLIANT])
    non_compliant = len([i for i in inspections if i.status == "finalized" and i.final_compliance_status == FINAL_NON_COMPLIANT])
    pending_review = len([i for i in inspections if i.status == "pending_review"])

    by_category: dict[str, int] = {}
    for i in inspections:
        key = i.product_category or "other"
        by_category[key] = by_category.get(key, 0) + 1

    recent_activity = (
        db.query(models.AuditLog).order_by(models.AuditLog.id.desc()).limit(8).all()
    )
    alerts = 0
    alerts += db.query(models.Inspection).filter(models.Inspection.status == "pending_review").count()
    alerts += db.query(models.Rule).filter(models.Rule.status == "draft").count()
    alerts += db.query(models.User).filter(models.User.status == "pending").count()

    per_inspector = [
        {
            "username": u.username, "full_name": u.full_name, "status": u.status,
            "inspections": len([i for i in inspections if i.inspector_id == u.id]),
            "pending_review": len([i for i in inspections if i.inspector_id == u.id and i.status == "pending_review"]),
        }
        for u in sorted(inspectors, key=lambda x: x.id)
    ]
    return {
        "stats": {
            "total_inspectors": total_inspectors, "active_inspectors": active,
            "pending_access": pending_access, "inactive": inactive,
            "total_inspections": total_inspections, "compliant": compliant,
            "non_compliant": non_compliant, "pending_review": pending_review,
            "system_alerts": alerts,
        },
        "inspector_access": per_inspector,
        "inspections_by_category": by_category,
        "activity": [serializers.audit_dict(a) for a in recent_activity],
    }
