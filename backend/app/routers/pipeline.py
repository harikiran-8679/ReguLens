"""OCR & extraction endpoints: run OCR, review raw regions, correct fields,
mark inspector verification, then continue to the rule engine stage."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, serializers
from ..database import get_db
from ..deps import get_current_user, get_inspection_or_404, require_owner_or_admin
from ..schemas import FieldCorrection, FieldVerifyRequest
from ..services.audit import record
from ..services.pipeline import run_field_matching, run_ocr, ocr_summary

router = APIRouter(prefix="/inspections", tags=["pipeline"])

# Category grouping for the structured extraction panel (same as OCR spec)
CATEGORY_LABELS = [
    ("product", "Product Information"),
    ("quantity", "Quantity"),
    ("price", "Price"),
    ("manufacturer", "Manufacturer / Packer / Importer"),
    ("dates", "Dates"),
    ("consumer", "Consumer Information"),
    ("origin", "Origin"),
    ("other", "Other Detected Text"),
]


def _require_not_finalized(inspection: models.Inspection):
    if inspection.status == "finalized":
        raise HTTPException(400, "Finalised inspections are read-only.")


@router.post("/{inspection_id}/ocr/run")
def run_ocr_endpoint(inspection_id: int, db: Session = Depends(get_db),
                     user: models.User = Depends(get_current_user)):
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    _require_not_finalized(inspection)
    ocr_result = run_ocr(db, inspection)
    if "error" in ocr_result:
        raise HTTPException(400, ocr_result["error"])
    extraction = run_field_matching(db, inspection)
    inspection.current_step = max(inspection.current_step, 3)
    db.commit()
    record(db, actor_user=user, inspection_id=inspection.id, action="ocr_run",
           entity_type="inspection", entity_id=inspection.inspection_id, details=ocr_result)
    return {**ocr_result, **extraction, "summary": ocr_summary(db, inspection)}


@router.get("/{inspection_id}/ocr")
def ocr_view(inspection_id: int, db: Session = Depends(get_db),
             user: models.User = Depends(get_current_user)):
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    regions = db.query(models.OcrResult).filter(
        models.OcrResult.inspection_id == inspection.id).order_by(
        models.OcrResult.image_id, models.OcrResult.region_id).all()
    images = {i.id: serializers.image_dict(i) for i in inspection.images}
    return {
        "summary": ocr_summary(db, inspection),
        "images": list(images.values()),
        "regions": [serializers.ocr_region_dict(r) for r in regions],
    }


@router.get("/{inspection_id}/fields")
def fields_view(inspection_id: int, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    fields = db.query(models.ExtractedField).filter(
        models.ExtractedField.inspection_id == inspection.id).order_by(
        models.ExtractedField.category, models.ExtractedField.sort).all()
    images = {i.id: i.image_id for i in inspection.images}

    grouped: list[dict] = []
    by_cat: dict[str, list] = {}
    for f in fields:
        by_cat.setdefault(f.category, []).append(f)
    for cat, label in CATEGORY_LABELS:
        rows = by_cat.get(cat, [])
        grouped.append({
            "category": cat,
            "label": label,
            "fields": [{
                **serializers.field_dict(f),
                "image_public_id": images.get(f.image_id),
            } for f in rows],
        })
    # fields that belong to categories not in the ordered list
    known = {c for c, _ in CATEGORY_LABELS}
    extra = [f for cat, fs in by_cat.items() if cat not in known for f in fs]
    if extra:
        grouped.append({"category": "other", "label": "Other Detected Text", "fields": extra})
    return {"summary": ocr_summary(db, inspection), "groups": grouped}


@router.patch("/extracted-fields/{field_id}")
def correct_field(field_id: int, body: FieldCorrection,
                  db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    field = db.query(models.ExtractedField).filter(models.ExtractedField.id == field_id).first()
    if field is None:
        raise HTTPException(404, "Field not found.")
    inspection = get_inspection_or_404(field.inspection_id, db)
    require_owner_or_admin(inspection, user)
    _require_not_finalized(inspection)
    if not field.original_value:
        field.original_value = field.value
    field.value = body.value.strip() or field.value
    field.correction_reason = body.reason
    field.source = "inspector"
    field.status = "DETECTED"  # inspector-corrected facts keep status DETECTED; original preserved above
    field.reason = ""
    field.verified = True
    field.verified_by = user.username
    db.commit()
    record(db, actor_user=user, inspection_id=inspection.id, action="field_corrected",
           entity_type="extracted_field", entity_id=str(field.id),
           details={"field": field.field_name, "original": field.original_value, "new": body.value,
                    "reason": body.reason})
    return serializers.field_dict(field)


@router.post("/{inspection_id}/fields/verify")
def verify_fields(inspection_id: int, body: FieldVerifyRequest,
                  db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    _require_not_finalized(inspection)
    query = db.query(models.ExtractedField).filter(models.ExtractedField.inspection_id == inspection.id)
    if body.field_ids is not None:
        query = query.filter(models.ExtractedField.id.in_(body.field_ids))
    verified = 0
    for f in query.all():
        if f.status == "NOT_DETECTED":
            continue
        f.verified = True
        f.verified_by = user.username
        verified += 1
    inspection.current_step = max(inspection.current_step, 3)
    if inspection.status == "draft":
        inspection.status = "under_analysis"
    db.commit()
    record(db, actor_user=user, inspection_id=inspection.id, action="ocr_verified",
           entity_type="inspection", entity_id=inspection.inspection_id,
           details={"verified": verified})
    return {"verified": verified, "summary": ocr_summary(db, inspection)}
