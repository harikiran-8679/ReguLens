"""Inspector review endpoints — the human verification stage.

The inspector confirms / rejects / modifies automated findings; the original
engine result is never overwritten (both values are retained for the audit
trail). Finalisation records a final compliance assessment.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, serializers
from ..database import get_db
from ..deps import get_current_user, get_inspection_or_404, require_owner_or_admin
from ..schemas import FinalizeRequest, FindingDecision, ObservationRequest
from ..services.audit import record
from ..utils import INSP_STATUS_FINALIZED, INSP_STATUS_PENDING_REVIEW

router = APIRouter(prefix="/inspections", tags=["review"])


def _load(db: Session, inspection_id: int, user: models.User) -> models.Inspection:
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    return inspection


@router.get("/{inspection_id}/review")
def review_board(inspection_id: int, db: Session = Depends(get_db),
                 user: models.User = Depends(get_current_user)):
    inspection = _load(db, inspection_id, user)
    findings = db.query(models.Finding).filter(
        models.Finding.inspection_id == inspection.id).order_by(
        models.Finding.sort_order).all()
    evidence = db.query(models.Evidence).filter(
        models.Evidence.inspection_id == inspection.id).count()
    persisted = db.query(models.RuleResult).filter(
        models.RuleResult.inspection_id == inspection.id).all()
    from ..services.rule_engine import aggregate_counts_with_overrides

    # Use inspector-aware counts so the header cards reflect reviewed decisions,
    # not the stale automated result that never changes in rule_results.result.
    counts = aggregate_counts_with_overrides(db, inspection.id, persisted)
    reviewed = [f for f in findings if f.inspector_status != "pending"]
    return {
        "inspection_status": inspection.status,
        "automated_result": inspection.automated_result,
        "counts": counts,
        "findings": [serializers.finding_dict(f) for f in findings],
        "pending": [f.finding_id for f in findings if f.inspector_status == "pending"],
        "reviewed": len(reviewed),
        "total_findings": len(findings),
        "evidence_coverage": {"linked": evidence, "findings": len(findings)},
        "review_progress": len(reviewed),
        "inspector_observation": inspection.inspector_observation,
        "snapshot": inspection.rule_set_snapshot,
    }



@router.patch("/findings/{finding_id}")
def decide_finding(finding_id: int, body: FindingDecision,
                   db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    finding = db.query(models.Finding).filter(models.Finding.id == finding_id).first()
    if finding is None:
        raise HTTPException(404, "Finding not found.")
    inspection = get_inspection_or_404(finding.inspection_id, db)
    require_owner_or_admin(inspection, user)
    if body.inspector_result not in ("satisfied", "not_satisfied", "inconclusive"):
        raise HTTPException(422, "inspector_result must be satisfied | not_satisfied | inconclusive")
    if inspection.status == "finalized":
        raise HTTPException(400, "Inspection is finalised and read-only.")

    finding.inspector_result = body.inspector_result
    finding.decision_reason = body.decision_reason
    finding.inspector_note = body.note
    finding.reviewed_by = user.username
    finding.reviewed_at = dt.datetime.now(dt.timezone.utc)
    # Map engine result + inspector decision -> inspector status (engine result preserved)
    if body.inspector_result == "satisfied":
        finding.inspector_status = "rejected" if finding.engine_result == "fail" else "confirmed"
    elif body.inspector_result == "not_satisfied":
        finding.inspector_status = "confirmed"
    else:
        finding.inspector_status = "inconclusive"
    db.commit()
    record(db, actor_user=user, inspection_id=inspection.id, action="finding_reviewed",
           entity_type="finding", entity_id=finding.finding_id,
           details={"engine_result": finding.engine_result, "inspector_result": body.inspector_result,
                    "status": finding.inspector_status, "reason": body.decision_reason})
    return serializers.finding_dict(finding)


@router.patch("/{inspection_id}/observation")
def save_observation(inspection_id: int, body: ObservationRequest,
                     db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    inspection = _load(db, inspection_id, user)
    inspection.inspector_observation = body.text
    db.commit()
    record(db, actor_user=user, inspection_id=inspection.id, action="observation_saved",
           entity_type="inspection", entity_id=inspection.inspection_id)
    return {"inspector_observation": inspection.inspector_observation}


@router.post("/{inspection_id}/finalize")
def finalize(inspection_id: int, body: FinalizeRequest,
             db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    inspection = _load(db, inspection_id, user)
    if inspection.status == "finalized":
        raise HTTPException(400, "Inspection is already finalised.")
    allowed_final = ("COMPLIANT", "NON_COMPLIANT", "MANUAL_REVIEW", "POTENTIAL_NON_COMPLIANCE")
    if body.final_compliance_status not in allowed_final:
        raise HTTPException(422, "final_compliance_status must be one of COMPLIANT | NON_COMPLIANT | MANUAL_REVIEW | POTENTIAL_NON_COMPLIANCE")

    pending = db.query(models.Finding).filter(
        models.Finding.inspection_id == inspection.id,
        models.Finding.inspector_status == "pending").all()
    if pending and not body.allow_unresolved:
        raise HTTPException(
            400,
            f"{len(pending)} finding(s) still require review: "
            + ", ".join(f.finding_id for f in pending)
            + ". Review them or explicitly allow finalisation with an unresolved reason.",
        )
    if pending and body.allow_unresolved and not body.unresolved_reason.strip():
        raise HTTPException(400, "A reason is required when finalising with unresolved findings.")

    inspection.status = INSP_STATUS_FINALIZED
    inspection.final_compliance_status = body.final_compliance_status
    inspection.final_remarks = body.final_remarks
    inspection.reviewed_by = user.username
    inspection.reviewed_at = dt.datetime.now(dt.timezone.utc)
    inspection.current_step = 7
    db.commit()
    record(db, actor_user=user, inspection_id=inspection.id, action="inspection_finalized",
           entity_type="inspection", entity_id=inspection.inspection_id,
           details={"final": body.final_compliance_status,
                    "automated": inspection.automated_result,
                    "unresolved_reason": body.unresolved_reason})
    return {
        "status": inspection.status,
        "final_compliance_status": inspection.final_compliance_status,
        "automated_result": inspection.automated_result,
        "reviewed_by": user.username,
        "reviewed_at": str(inspection.reviewed_at) if inspection.reviewed_at is not None else None,
    }
