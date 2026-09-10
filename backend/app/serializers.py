"""Small ORM -> dict serialisers shared by the API routers."""
from __future__ import annotations

import datetime as dt

from . import models


def _dt(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.isoformat()
    return str(v)


def user_dict(u: models.User) -> dict:
    return {
        "id": u.id, "username": u.username, "full_name": u.full_name,
        "role": u.role, "department": u.department, "status": u.status,
        "last_active_at": _dt(u.last_active_at),
    }


def inspection_brief(i: models.Inspection) -> dict:
    return {
        "id": i.id,
        "inspection_id": i.inspection_id,
        "inspector": i.inspector.username,
        "inspector_name": i.inspector.full_name,
        "product_name": i.product_name,
        "product_category": i.product_category,
        "brand": i.brand,
        "retailer_store": i.retailer_store,
        "location": i.location,
        "inspection_date": _dt(i.inspection_date),
        "status": i.status,
        "current_step": i.current_step,
        "automated_result": i.automated_result,
        "final_compliance_status": i.final_compliance_status,
        "violations_count": len([f for f in i.findings if f.engine_result == "fail"]),
        "review_count": len([f for f in i.findings if f.engine_result == "review"]),
        "images_count": len(i.images),
        "updated_at": _dt(i.updated_at),
    }


def inspection_full(i: models.Inspection) -> dict:
    d = inspection_brief(i)
    d.update({
        "product_description": i.product_description,
        "package_type": i.package_type,
        "premises_type": i.premises_type,
        "country_of_origin_claimed": i.country_of_origin_claimed,
        "inspector_observation": i.inspector_observation,
        "final_remarks": i.final_remarks,
        "reviewed_at": _dt(i.reviewed_at),
        "rule_set_snapshot": i.rule_set_snapshot,
        "online_listing": i.online_listing,
    })
    return d


def image_dict(img: models.InspectionImage) -> dict:
    return {
        "id": img.id,
        "image_id": img.image_id,
        "inspection_id": img.inspection_id,
        "side": img.side,
        "source": img.source,
        "storage_path": img.storage_path,
        "file_hash": img.file_hash,
        "width": img.width,
        "height": img.height,
        "format": img.format,
        "quality": img.quality,
        "ocr_suitability": img.ocr_suitability,
        "processing_status": img.processing_status,
        "ocr_engine": img.ocr_engine,
        "ocr_fallback_used": img.ocr_fallback_used,
        "is_duplicate": img.is_duplicate,
        "duplicate_of": img.duplicate_of,
        "captured_at": _dt(img.captured_at),
        "meta": img.meta,
    }


def field_dict(f: models.ExtractedField) -> dict:
    """product_facts shape: value + unit/currency where relevant, status
    (DETECTED/NOT_DETECTED/UNCERTAIN), confidence, evidence (image_id + bbox),
    reason (populated for UNCERTAIN / NOT_DETECTED)."""
    from .services.matcher import FIELD_CATALOG
    from .services.normalizer import normalize_amount, normalize_quantity

    meta = FIELD_CATALOG.get(f.field_name, {})
    img_id = None
    img_width = img_height = None
    if f.image_id is not None:
        for i in f.inspection.images if hasattr(f, "inspection") else []:
            if i.id == f.image_id:
                img_id = i.image_id
                img_width, img_height = i.width, i.height
                break
    unit = None
    currency = None
    if f.field_name == "net_quantity" and f.value:
        hit = normalize_quantity(f.value) or normalize_quantity(f.raw_text or "")
        if hit:
            unit = hit["unit"]
    elif f.field_name == "mrp_value" and f.value:
        hit = normalize_amount(f.value) or normalize_amount(f.raw_text or "")
        if hit:
            currency = hit["currency"]
    evidence = None
    if img_id:
        bbox = f.bbox or {}
        px = None
        if bbox and img_width and img_height:
            x, y = float(bbox.get("x", 0)), float(bbox.get("y", 0))
            w, h = float(bbox.get("width", 0)), float(bbox.get("height", 0))
            px = [round(x * img_width), round(y * img_height),
                  round((x + w) * img_width), round((y + h) * img_height)]
        evidence = {"image_id": img_id, "bbox": px}
    return {
        "id": f.id,
        "field_name": f.field_name,
        "label": meta.get("label", f.field_name.replace("_", " ").title()),
        "category": f.category,
        "value": f.value,
        "raw_text": f.raw_text,
        "confidence": f.confidence,
        "status": f.status,
        "reason": f.reason,
        "unit": unit,
        "currency": currency,
        "verified": f.verified,
        "source": f.source,
        "original_value": f.original_value,
        "correction_reason": f.correction_reason,
        "image_public_id": img_id,
        "region_id": f.region_id,
        "bbox": f.bbox,
        "evidence": evidence,
    }


def ocr_region_dict(r: models.OcrResult) -> dict:
    return {
        "id": r.id,
        "region_id": r.region_id,
        "image_id": r.image_id,
        "text": r.text,
        "confidence": r.confidence,
        "bbox": r.bbox,
    }


def rule_dict(r: models.Rule) -> dict:
    return {
        "id": r.id,
        "rule_id": r.rule_id,
        "rule_number": r.rule_number,
        "sub_rule": r.sub_rule,
        "title": r.title,
        "type": r.type,
        "scope": r.scope,
        "category": r.category,
        "requirement": r.requirement,
        "description": r.description,
        "field": r.field,
        "required": r.required,
        "applicability": r.applicability,
        "conditions": r.conditions,
        "validation": r.validation,
        "severity": r.severity,
        "evidence_required": r.evidence_required,
        "effective_from": str(r.effective_from),
        "effective_to": str(r.effective_to) if r.effective_to else None,
        "version": r.version,
        "source": r.source,
        "status": r.status,
        "sort_order": r.sort_order,
    }


def rule_result_dict(rr: models.RuleResult) -> dict:
    """One compliance_result row — matches the four allowed shapes exactly
    (status is one of COMPLIANT / NON_COMPLIANT / MANUAL_REVIEW /
    POTENTIAL_NON_COMPLIANCE; MANUAL_REVIEW carries a reason;
    POTENTIAL_NON_COMPLIANCE carries dual observed values)."""
    return {
        "id": rr.id,
        "rule_id": rr.rule_id,
        "rule_number": rr.rule_number,
        "sub_rule": rr.sub_rule,
        "title": rr.title,
        "category": rr.category,
        "type": rr.type,
        "requirement": rr.requirement,
        "status": rr.result,   # kept for backward-compat; prefer "result" below
        "result": rr.result,    # Bug 1 fix: frontend RuleAnalysis reads r.result
        "observed": rr.observed,
        "expected": rr.expected,
        "evidence": rr.evidence,
        "reason": rr.reason,
        "input_value": rr.input_value,
        "expected_value": rr.expected_value,
        "note": rr.note,
        "confidence": rr.confidence,
        "severity": rr.severity,
        "field": rr.field,
        "evidence_required": rr.evidence_required,
    }


# B2: Human-readable labels for inspector_status
# Raw status 'rejected' means the inspector overrode a fail finding (requirement satisfied),
# which is confusing when displayed as 'REJECTED'. Map to clear display labels.
_INSPECTOR_STATUS_LABELS: dict[str, str] = {
    "pending":     "Pending Review",
    "confirmed":   "Violation Confirmed",
    "rejected":    "Compliant (Overridden)",  # inspector said finding was wrong
    "inconclusive": "Inconclusive — Needs Follow-up",
    "modified":    "Modified by Inspector",
}


def _inspector_status_label(status: str | None, inspector_result: str | None) -> str:
    """Return a clear human-readable label for an inspector review status.

    Guards against None — findings created before B2 fix may have None status.
    """
    status = status or "pending"   # None → treat as pending
    if status == "rejected" and inspector_result == "satisfied":
        return "Compliant (Overridden)"
    if status == "confirmed" and inspector_result == "not_satisfied":
        return "Violation Confirmed"
    if status == "confirmed" and inspector_result == "satisfied":
        return "Confirmed Compliant"
    return _INSPECTOR_STATUS_LABELS.get(status, status.replace("_", " ").title())


def finding_dict(f: models.Finding) -> dict:
    return {
        "id": f.id,
        "finding_id": f.finding_id,
        "inspection_id": f.inspection_id,
        "finding_type": f.finding_type,
        "requirement": f.requirement,
        "detected_condition": f.detected_condition,
        "expected_condition": f.expected_condition,
        "engine_result": f.engine_result,
        "severity": f.severity,
        "confidence": f.confidence,
        "source_image_id": f.source_image_id,
        "ocr_region_id": f.ocr_region_id,
        "source_field": f.source_field,
        "rule_number": f.rule_number,
        "sub_rule": f.sub_rule,
        "inspector_status": f.inspector_status,
        # B2: human-readable label (does not say REJECTED for overrides)
        "inspector_status_label": _inspector_status_label(f.inspector_status, f.inspector_result),
        "inspector_result": f.inspector_result,
        "inspector_note": f.inspector_note,
        "decision_reason": f.decision_reason,
        "reviewed_by": f.reviewed_by,
        "reviewed_at": _dt(f.reviewed_at),
    }


def font_dict(fa: models.FontAnalysis) -> dict:
    return {
        "id": fa.id,
        "field": fa.field,
        "image_id": fa.image_id,
        "region_id": fa.region_id,
        "detected_text": fa.detected_text,
        "readability_score": fa.readability_score,
        "readability": fa.readability,
        "font_estimate": fa.font_estimate,
        "measurement_unit": fa.measurement_unit,
        "measurement_method": fa.measurement_method,
        "calibration_available": fa.calibration_available,
        "measurement_confidence": fa.measurement_confidence,
        "applicable_rule": fa.applicable_rule,
        "required_condition": fa.required_condition,
        "automated_result": fa.automated_result,
        "manual_review_required": fa.manual_review_required,
        "inspector_result": fa.inspector_result,
        "inspector_note": fa.inspector_note,
        "finding_id": fa.finding_id,
    }


def placement_dict(pa: models.PlacementAnalysis) -> dict:
    return {
        "id": pa.id,
        "field": pa.field,
        "image_id": pa.image_id,
        "region_id": pa.region_id,
        "detected_location": pa.detected_location,
        "detected_panel": pa.detected_panel,
        "position_confidence": pa.position_confidence,
        "format_observation": pa.format_observation,
        "format_confidence": pa.format_confidence,
        "applicable_rule": pa.applicable_rule,
        "requirement": pa.requirement,
        "expected_condition": pa.expected_condition,
        "detected_condition": pa.detected_condition,
        "automated_result": pa.automated_result,
        "evidence_sufficient": pa.evidence_sufficient,
        "manual_review_required": pa.manual_review_required,
        "inspector_result": pa.inspector_result,
        "inspector_note": pa.inspector_note,
        "finding_id": pa.finding_id,
    }


def evidence_dict(e: models.Evidence) -> dict:
    return {
        "id": e.id,
        "evidence_id": e.evidence_id,
        "inspection_id": e.inspection_id,
        "evidence_type": e.evidence_type,
        "source_image_id": e.source_image_id,
        "region_id": e.region_id,
        "finding_id": e.finding_id,
        "rule_id": e.rule_id,
        "field_name": e.field_name,
        "description": e.description,
        "status": e.status,
        "relevance": e.relevance,
        "observation": e.observation,
        "file_reference": e.file_reference,
        "captured_by": e.captured_by,
    }


def report_dict(r: models.Report) -> dict:
    return {
        "id": r.id,
        "report_id": r.report_id,
        "inspection_id": r.inspection_id,
        "report_version": r.report_version,
        "report_type": r.report_type,
        "template_id": r.template_id,
        "template_version": r.template_version,
        "rule_set_version": r.rule_set_version,
        "generated_by": r.generated_by,
        "generated_at": _dt(r.generated_at),
        "file_reference": r.file_reference,
        "generation_status": r.generation_status,
        "validation_status": r.validation_status,
        "included_sections": r.included_sections,
    }


def audit_dict(a: models.AuditLog) -> dict:
    return {
        "id": a.id,
        "inspection_id": a.inspection_id,
        "actor": a.actor,
        "actor_role": a.actor_role,
        "action": a.action,
        "entity_type": a.entity_type,
        "entity_id": a.entity_id,
        "details": a.details,
        "created_at": _dt(a.created_at),
    }
