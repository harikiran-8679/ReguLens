"""Analysis endpoints: applicable rule set, rule-engine run, compliance result,
findings/violations, font & readability and placement/format analysis."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, serializers
from ..database import get_db
from ..deps import get_current_user, get_inspection_or_404, require_owner_or_admin
from ..schemas import FindingDecision
from ..services.audit import record
from ..services.evidence_blocks import build_context, enrich_finding
from ..services.rule_engine import (
    aggregate_counts,
    aggregate_counts_with_overrides,
    applicable,
    build_context as engine_build_context,   # aliased to avoid shadowing evidence_blocks.build_context
    run_cross_checks,
    run_rule_analysis,
    select_rules,
)

router = APIRouter(prefix="/inspections", tags=["analysis"])


def _load(db: Session, inspection_id: int, user: models.User) -> models.Inspection:
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    return inspection


@router.get("/{inspection_id}/rule-set")
def rule_set(inspection_id: int, db: Session = Depends(get_db),
             user: models.User = Depends(get_current_user)):
    inspection = _load(db, inspection_id, user)
    snapshot = inspection.rule_set_snapshot or {}
    rules = select_rules(db, inspection)
    # Count rules that pass the per-inspection applicability check so the UI
    # "Rules Selected" header matches the evaluated-rule count exactly.
    ctx = engine_build_context(db, inspection)
    applicable_rules = [r for r in rules if applicable(ctx, r)[0]]
    return {
        "snapshot": snapshot,
        "rule_set_version": snapshot.get("rule_set_version", "Current consolidated rule set"),
        "effective_date": snapshot.get("effective_date") or str(inspection.inspection_date.date()),
        "rules": [serializers.rule_dict(r) for r in rules],
        "rules_count": len(applicable_rules),         # applicable to THIS inspection (post-filter)
        "rules_in_window": len(rules),                # all rules in date window (pre-filter)
        "rules_skipped": len(rules) - len(applicable_rules),
    }


@router.post("/{inspection_id}/analysis/run")
def run_analysis(inspection_id: int, db: Session = Depends(get_db),
                 user: models.User = Depends(get_current_user)):
    inspection = _load(db, inspection_id, user)
    result = run_rule_analysis(db, inspection)
    record(db, actor_user=user, inspection_id=inspection.id, action="rule_analysis_run",
           entity_type="inspection", entity_id=inspection.inspection_id,
           details={"counts": result["counts"], "automated_result": result["automated_result"]})
    return result


@router.get("/{inspection_id}/rule-results")
def rule_results(inspection_id: int, db: Session = Depends(get_db),
                 user: models.User = Depends(get_current_user)):
    inspection = _load(db, inspection_id, user)
    persisted = db.query(models.RuleResult).filter(
        models.RuleResult.inspection_id == inspection.id).order_by(
        models.RuleResult.sort_order).all()
    counts = aggregate_counts(persisted)
    return {"counts": counts, "results": [serializers.rule_result_dict(r) for r in persisted]}


@router.get("/{inspection_id}/compliance")
def compliance_result(inspection_id: int, db: Session = Depends(get_db),
                      user: models.User = Depends(get_current_user)):
    """The compliance_result document (Section 5 of the build spec):

      inspection_id / inspection_date / rules_version /
      summary {rules_checked, compliant, non_compliant, manual_review,
               potential_non_compliance} — computed from the persisted results
      array, never hardcoded /
      results[] — each exactly one of the four status shapes.
    """
    inspection = _load(db, inspection_id, user)
    persisted = db.query(models.RuleResult).filter(
        models.RuleResult.inspection_id == inspection.id).order_by(
        models.RuleResult.sort_order).all()
    findings = db.query(models.Finding).filter(
        models.Finding.inspection_id == inspection.id).order_by(
        models.Finding.sort_order).all()
    # Use inspector-aware counts: inspector decisions (satisfied/not_satisfied/inconclusive)
    # are layered on top of the automated rule_results.result without modifying that column.
    counts = aggregate_counts_with_overrides(db, inspection.id, persisted)
    failed = [f for f in findings if f.engine_result == "fail"]
    review = [f for f in findings if f.engine_result == "review"]
    snapshot = inspection.rule_set_snapshot or {}
    return {
        "inspection_id": inspection.inspection_id,
        "inspection_date": str(_inspection_date(inspection)),
        "rules_version": snapshot.get("rule_set_version", "Current consolidated rule set (seeded)"),
        "summary": {
            "rules_checked": counts["rules_checked"],
            "compliant": counts["compliant"],
            "non_compliant": counts["non_compliant"],
            "manual_review": counts["manual_review"],
            "potential_non_compliance": counts["potential_non_compliance"],
        },
        "results": [serializers.rule_result_dict(p) for p in persisted],
        "automated_result": inspection.automated_result,
        "inspection_status": inspection.status,
        "final_compliance_status": inspection.final_compliance_status,
        "online_listing": inspection.online_listing,
        "counts": counts,
        "coverage_note": snapshot.get("coverage_note", ""),
        "snapshot": snapshot,
        "failed": [serializers.finding_dict(f) for f in failed],
        "review": [serializers.finding_dict(f) for f in review],
    }


def _inspection_date(inspection: models.Inspection):
    return inspection.inspection_date.date() if isinstance(inspection.inspection_date, dt.datetime) else inspection.inspection_date


@router.post("/{inspection_id}/online-listing")
def save_online_listing(inspection_id: int, body: dict,
                        db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Store a manually entered online-listing value for cross-source comparison
    and immediately re-run the cross checks (other rule results untouched)."""
    inspection = _load(db, inspection_id, user)
    if inspection.status == "finalized":
        raise HTTPException(400, "Finalised inspections are read-only.")
    field = (body.get("field") or "").strip()
    value = (body.get("value") or "").strip()
    source = (body.get("source") or "Online listing").strip()
    if field not in ("net_quantity", "mrp_value"):
        raise HTTPException(422, "field must be net_quantity or mrp_value.")
    if not value:
        raise HTTPException(422, "value is required.")
    inspection.online_listing = {"field": field, "value": value, "source": source}
    db.commit()
    result = run_cross_checks(db, inspection)
    record(db, actor_user=user, inspection_id=inspection.id, action="online_listing_saved",
           entity_type="inspection", entity_id=inspection.inspection_id,
           details={"field": field, "value": value, "source": source, "counts": result["counts"]})
    return {
        "online_listing": inspection.online_listing,
        "automated_result": inspection.automated_result,
        "counts": result["counts"],
        "summary": {
            "rules_checked": result["counts"]["rules_checked"],
            "compliant": result["counts"]["compliant"],
            "non_compliant": result["counts"]["non_compliant"],
            "manual_review": result["counts"]["manual_review"],
            "potential_non_compliance": result["counts"]["potential_non_compliance"],
        },
    }


@router.get("/{inspection_id}/findings")
def findings_view(inspection_id: int, db: Session = Depends(get_db),
                  user: models.User = Depends(get_current_user)):
    inspection = _load(db, inspection_id, user)
    persisted = db.query(models.RuleResult).filter(
        models.RuleResult.inspection_id == inspection.id).order_by(
        models.RuleResult.sort_order).all()
    findings = db.query(models.Finding).filter(
        models.Finding.inspection_id == inspection.id).order_by(
        models.Finding.sort_order).all()
    # Use inspector-aware counts so the Violation Details page reflects overrides.
    counts = aggregate_counts_with_overrides(db, inspection.id, persisted)
    ctx = build_context(inspection)
    failed = [enrich_finding(f, ctx) for f in findings if f.engine_result == "fail"]
    review = [enrich_finding(f, ctx) for f in findings if f.engine_result == "review"]
    return {
        "counts": counts,
        "inspection_status": inspection.status,
        "failed": failed,
        "review": review,
    }


@router.get("/{inspection_id}/font-analysis")
def font_analysis(inspection_id: int, db: Session = Depends(get_db),
                  user: models.User = Depends(get_current_user)):
    inspection = _load(db, inspection_id, user)
    rows = db.query(models.FontAnalysis).filter(
        models.FontAnalysis.inspection_id == inspection.id).all()
    # B3 FIX: derive summary counts from rule_results (authoritative 4-state results)
    # font_analyses.automated_result uses 'pass'/'review'/'potential_fail' which is
    # an internal signal; rule_results.result carries the canonical compliance state.
    font_results = db.query(models.RuleResult).join(
        models.Rule, models.Rule.id == models.RuleResult.rule_id
    ).filter(
        models.RuleResult.inspection_id == inspection.id,
        models.Rule.type == "font",
    ).all()
    return {
        "summary": {
            "declarations_analysed": len(font_results),
            "readability_acceptable": sum(1 for r in font_results if r.result == "COMPLIANT"),
            "manual_review_required": sum(1 for r in font_results if r.result == "MANUAL_REVIEW"),
            "potential_issues": sum(1 for r in font_results if r.result in ("NON_COMPLIANT", "POTENTIAL_NON_COMPLIANCE")),
            # Legacy counts from font_analyses table for backward compat
            "analysed": len(rows),
            "readable": len([r for r in rows if r.readability == "good"]),
            "review_required": len([r for r in rows if r.manual_review_required]),
            "potential": len([r for r in rows if r.automated_result == "potential_fail"]),
        },
        "items": [serializers.font_dict(r) for r in rows],
        "rule_results": [serializers.rule_result_dict(r) for r in font_results],
    }


@router.patch("/font-analyses/{analysis_id}")
def font_assessment(analysis_id: int, body: FindingDecision,
                    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    analysis = db.query(models.FontAnalysis).filter(models.FontAnalysis.id == analysis_id).first()
    if analysis is None:
        raise HTTPException(404, "Font analysis not found.")
    inspection = get_inspection_or_404(analysis.inspection_id, db)
    require_owner_or_admin(inspection, user)
    analysis.inspector_result = body.inspector_result
    analysis.inspector_note = body.note
    db.commit()
    record(db, actor_user=user, inspection_id=inspection.id, action="font_assessment",
           entity_type="font_analysis", entity_id=str(analysis.id), details={"result": body.inspector_result})
    return serializers.font_dict(analysis)


@router.get("/{inspection_id}/placement-analysis")
def placement_analysis(inspection_id: int, db: Session = Depends(get_db),
                       user: models.User = Depends(get_current_user)):
    inspection = _load(db, inspection_id, user)
    rows = db.query(models.PlacementAnalysis).filter(
        models.PlacementAnalysis.inspection_id == inspection.id).all()
    # B3 FIX: derive summary counts from rule_results (authoritative 4-state results)
    placement_results = db.query(models.RuleResult).join(
        models.Rule, models.Rule.id == models.RuleResult.rule_id
    ).filter(
        models.RuleResult.inspection_id == inspection.id,
        models.Rule.type.in_(["placement", "spacing", "format"]),
    ).all()
    return {
        "summary": {
            "declarations_analysed": len(placement_results),
            "placement_acceptable": sum(1 for r in placement_results if r.result == "COMPLIANT"),
            "manual_review_required": sum(1 for r in placement_results if r.result == "MANUAL_REVIEW"),
            "potential_issues": sum(1 for r in placement_results if r.result in ("NON_COMPLIANT", "POTENTIAL_NON_COMPLIANCE")),
            # Legacy counts from placement_analyses table for backward compat
            "checked": len(rows),
            "passed": len([r for r in rows if r.automated_result == "pass"]),
            "review_required": len([r for r in rows if r.manual_review_required]),
            "potential": len([r for r in rows if r.automated_result == "potential_issue"]),
        },
        "items": [serializers.placement_dict(r) for r in rows],
        "rule_results": [serializers.rule_result_dict(r) for r in placement_results],
    }


@router.patch("/placement-analyses/{analysis_id}")
def placement_assessment(analysis_id: int, body: FindingDecision,
                         db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    analysis = db.query(models.PlacementAnalysis).filter(models.PlacementAnalysis.id == analysis_id).first()
    if analysis is None:
        raise HTTPException(404, "Placement analysis not found.")
    inspection = get_inspection_or_404(analysis.inspection_id, db)
    require_owner_or_admin(inspection, user)
    analysis.inspector_result = body.inspector_result
    analysis.inspector_note = body.note
    db.commit()
    record(db, actor_user=user, inspection_id=inspection.id, action="placement_assessment",
           entity_type="placement_analysis", entity_id=str(analysis.id), details={"result": body.inspector_result})
    return serializers.placement_dict(analysis)
