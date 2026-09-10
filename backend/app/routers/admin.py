"""Admin-only endpoints: inspector account management, rule CRUD, audit log."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, serializers
from ..database import get_db
from ..deps import get_current_user, require_roles
from ..schemas import InspectorCreate, InspectorUpdate, RuleUpsert
from ..security import hash_password
from ..services.audit import record

router = APIRouter(tags=["admin"])

admin = require_roles("admin")


# ---------------------------------------------------------------------------
# Inspector accounts
# ---------------------------------------------------------------------------
@router.get("/admin/inspectors")
def list_inspectors(db: Session = Depends(get_db), _: models.User = Depends(admin),
                    status: str | None = Query(default=None)):
    query = db.query(models.User).filter(models.User.role == "inspector")
    if status:
        query = query.filter(models.User.status == status)
    users = query.order_by(models.User.id).all()
    return {"items": [serializers.user_dict(u) for u in users], "count": len(users)}


@router.post("/admin/inspectors")
def create_inspector(body: InspectorCreate, db: Session = Depends(get_db),
                     user: models.User = Depends(admin)):
    if db.query(models.User).filter(models.User.username == body.username.strip()).first():
        raise HTTPException(409, "Username already exists.")
    if body.status not in ("active", "pending", "inactive"):
        raise HTTPException(422, "status must be active | pending | inactive")
    inspector = models.User(
        username=body.username.strip(),
        full_name=body.full_name,
        department=body.department,
        role="inspector",
        status=body.status,
        password_hash=hash_password(body.password),
    )
    db.add(inspector)
    db.commit()
    record(db, actor_user=user, action="inspector_created", entity_type="user",
           entity_id=inspector.username, details={"status": body.status})
    return serializers.user_dict(inspector)


@router.patch("/admin/inspectors/{user_id}")
def update_inspector(user_id: int, body: InspectorUpdate,
                     db: Session = Depends(get_db), user: models.User = Depends(admin)):
    inspector = db.query(models.User).filter(models.User.id == user_id,
                                             models.User.role == "inspector").first()
    if inspector is None:
        raise HTTPException(404, "Inspector not found.")
    if body.status in ("active", "pending", "inactive"):
        inspector.status = body.status
    if body.full_name is not None:
        inspector.full_name = body.full_name
    if body.department is not None:
        inspector.department = body.department
    if body.role in ("inspector", "admin"):
        inspector.role = body.role
    db.commit()
    record(db, actor_user=user, action="inspector_updated", entity_type="user",
           entity_id=inspector.username,
           details={"status": body.status, "role": body.role})
    return serializers.user_dict(inspector)


@router.get("/admin/audit")
def audit_log(db: Session = Depends(get_db), _: models.User = Depends(admin),
              limit: int = Query(default=60, le=500), actor: str | None = Query(default=None)):
    query = db.query(models.AuditLog)
    if actor:
        query = query.filter(models.AuditLog.actor == actor)
    rows = query.order_by(models.AuditLog.id.desc()).limit(limit).all()
    return {"items": [serializers.audit_dict(a) for a in rows]}


# ---------------------------------------------------------------------------
# Rule engine table (versioned rows)
# ---------------------------------------------------------------------------
@router.get("/rules")
def list_rules(db: Session = Depends(get_db), user: models.User = Depends(get_current_user),
               status: str | None = Query(default=None),
               type: str | None = Query(default=None)):
    query = db.query(models.Rule)
    if status:
        query = query.filter(models.Rule.status == status)
    if type:
        query = query.filter(models.Rule.type == type)
    rows = query.order_by(models.Rule.sort_order, models.Rule.id).all()
    return {"items": [serializers.rule_dict(r) for r in rows], "count": len(rows)}


@router.get("/rules/{rule_id}")
def get_rule(rule_id: int, db: Session = Depends(get_db),
             user: models.User = Depends(get_current_user)):
    rule = db.query(models.Rule).filter(models.Rule.id == rule_id).first()
    if rule is None:
        raise HTTPException(404, "Rule not found.")
    return serializers.rule_dict(rule)


@router.post("/admin/rules")
def create_rule(body: RuleUpsert, db: Session = Depends(get_db),
                user: models.User = Depends(admin)):
    try:
        eff_from = dt.date.fromisoformat(body.effective_from)
        eff_to = dt.date.fromisoformat(body.effective_to) if body.effective_to else None
    except ValueError as exc:
        raise HTTPException(422, "effective dates must be ISO (YYYY-MM-DD).") from exc
    rule = models.Rule(
        rule_id=f"PC-ADMIN-{db.query(models.Rule).count() + 1}",
        rule_number=body.rule_number, sub_rule=body.sub_rule, title=body.title, type=body.type,
        category=body.category, requirement=body.requirement, description=body.description,
        field=body.field, required=body.required, applicability=body.applicability,
        conditions=body.conditions, validation=body.validation, severity=body.severity,
        evidence_required=body.evidence_required, effective_from=eff_from, effective_to=eff_to,
        version=body.version, source=body.source, status=body.status,
        sort_order=(db.query(models.Rule).count() + 1) * 10,
    )
    db.add(rule)
    db.commit()
    record(db, actor_user=user, action="rule_created", entity_type="rule",
           entity_id=rule.rule_id, details={"sub_rule": body.sub_rule, "status": body.status})
    return serializers.rule_dict(rule)


@router.patch("/admin/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleUpsert, db: Session = Depends(get_db),
                user: models.User = Depends(admin)):
    rule = db.query(models.Rule).filter(models.Rule.id == rule_id).first()
    if rule is None:
        raise HTTPException(404, "Rule not found.")
    updates = body.model_dump(exclude_unset=True)
    if "effective_from" in updates:
        try:
            rule.effective_from = dt.date.fromisoformat(updates["effective_from"])
        except ValueError as exc:
            raise HTTPException(422, "effective_from must be ISO date.") from exc
    if "effective_to" in updates:
        rule.effective_to = dt.date.fromisoformat(updates["effective_to"]) if updates["effective_to"] else None
    for key in ("rule_number", "sub_rule", "title", "type", "category", "requirement",
                "description", "field", "required", "applicability", "conditions",
                "validation", "severity", "evidence_required", "version", "source", "status"):
        if key in updates and key not in ("effective_from", "effective_to"):
            setattr(rule, key, updates[key])
    db.commit()
    record(db, actor_user=user, action="rule_updated", entity_type="rule",
           entity_id=rule.rule_id, details={"fields": list(updates.keys())})
    return serializers.rule_dict(rule)


@router.delete("/admin/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db),
                user: models.User = Depends(admin)):
    rule = db.query(models.Rule).filter(models.Rule.id == rule_id).first()
    if rule is None:
        raise HTTPException(404, "Rule not found.")
    rule_id_str = rule.rule_id
    rule.status = "superseded"  # never hard-delete; keep the audit trail intact
    db.commit()
    record(db, actor_user=user, action="rule_deactivated", entity_type="rule",
           entity_id=rule_id_str)
    return {"status": "superseded", "rule_id": rule_id_str}
