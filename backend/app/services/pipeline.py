"""Extraction pipeline: image -> OCR regions -> structured extracted fields.

Consumes the verified/structured field rows later (rule engine) and always keeps
raw OCR text + confidence + bounding box as evidence.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..utils import FIELD_DETECTED, FIELD_NOT_FOUND, FIELD_UNCERTAIN, IMG_STATUS_DONE
from .matcher import (
    HIGH_CONF,
    MANDATORY_FIELD_SET,
    OllamaFieldMatcher,
    classify_entity_line,
    classify_line,
    classify_plain_line,
)
from .ocr import OcrRegion, normalize_confidence, run_ocr_with_fallback


def _region_sort_key(img: models.InspectionImage):
    order = {"front": 0, "back": 1, "side": 2, "top": 3, "bottom": 4, "declaration": 5, "additional": 6}
    return (order.get(img.side, 9), img.id)


def run_ocr(db: Session, inspection: models.Inspection, image_ids: list[int] | None = None,
            engine_name: str | None = None) -> dict:
    """Run OCR over the inspection's images with Paddle-first / Tesseract-fallback
    semantics, and persist per-image which engine produced the regions."""
    images = [i for i in inspection.images if image_ids is None or i.id in image_ids]
    if not images:
        return {"error": "No images to process.", "engine": engine_name or settings.OCR_ENGINE}

    # remove stale results only for the images being (re)processed
    stale = [r for r in inspection.ocr_results if r.image_id in {i.id for i in images}]
    for r in stale:
        db.delete(r)
    db.flush()

    total_regions = 0
    engines_used: list[dict] = []
    fallbacks: list[dict] = []
    last_note = ""
    for img in images:
        path = settings.storage_dir / img.storage_path
        result = run_ocr_with_fallback(path, ground_truth=img.ground_truth, requested=engine_name)
        last_note = result.note
        # Engine-specific confidences are normalised onto the shared 0..1 scale
        # (see ocr.normalize_confidence) before anything downstream consumes them.
        regions = [
            OcrRegion(text=r.text, confidence=normalize_confidence(r.confidence, result.engine_code),
                      x=r.x, y=r.y, w=r.w, h=r.h)
            for r in result.regions
        ]
        regions.sort(key=lambda r: (r.y, r.x))
        for idx, reg in enumerate(regions, start=1):
            db.add(models.OcrResult(
                inspection_id=inspection.id,
                image_id=img.id,
                region_id=f"REGION-{idx:02d}",
                text=reg.text,
                confidence=reg.confidence,
                bbox={"x": reg.x, "y": reg.y, "width": reg.w, "height": reg.h},
            ))
        total_regions += len(regions)
        img.processing_status = IMG_STATUS_DONE if regions or img.ground_truth else "failed"
        img.ocr_engine = result.engine_code
        img.ocr_fallback_used = result.fallback_used
        engines_used.append({"image_id": img.image_id, **result.to_dict()})
        if result.fallback_used:
            fallbacks.append({"image_id": img.image_id, "chain": result.chain, "note": result.note})
    db.commit()
    return {
        "images_processed": len(images),
        "text_regions": total_regions,
        "engine": engines_used[0]["engine"] if engines_used else (engine_name or settings.OCR_ENGINE),
        "engine_label": engines_used[0]["engine_label"] if engines_used else "—",
        "engines_used": engines_used,
        "fallbacks": fallbacks,
        "engine_note": last_note,
    }


def _current_raw_texts(db: Session, inspection: models.Inspection) -> set[str]:
    rows = (
        db.query(models.OcrResult)
        .filter(models.OcrResult.inspection_id == inspection.id)
        .all()
    )
    return {r.text.strip() for r in rows}


def run_field_matching(db: Session, inspection: models.Inspection) -> dict:
    """Classify OCR regions into extracted declaration fields (structured data)."""
    # Preserve any inspector-made corrections whose original OCR text is still present.
    previous = (
        db.query(models.ExtractedField)
        .filter(models.ExtractedField.inspection_id == inspection.id)
        .all()
    )
    kept_corrections = {}
    for f in previous:
        if f.source == "inspector" and f.original_value in _current_raw_texts(db, inspection):
            kept_corrections[f.field_name] = {
                "value": f.value, "original": f.original_value, "reason": f.correction_reason,
            }
    for f in previous:
        db.delete(f)
    db.flush()

    ocr_rows = (
        db.query(models.OcrResult)
        .filter(models.OcrResult.inspection_id == inspection.id)
        .order_by(models.OcrResult.image_id, models.OcrResult.region_id)
        .all()
    )
    by_image: dict[int, list[models.OcrResult]] = {}
    for r in ocr_rows:
        by_image.setdefault(r.image_id, []).append(r)

    images = {i.id: i for i in inspection.images}
    # One candidate row per (field, image) — NOT a single best-per-field. Keeping
    # every image's reading lets the rule engine detect cross-field/cross-panel
    # mismatches (e.g. two different net_quantity values on the same package).
    candidates: dict[tuple[str, int], dict] = {}

    def consider(hit_field: str, hit_value: str, raw: str, conf: float, rule_name: str,
                 image_id: int, region_id: str, bbox: dict | None):
        if conf <= 0.30:
            return
        key = (hit_field, image_id)
        cur = candidates.get(key)
        if cur is None or conf > cur["confidence"]:
            candidates[key] = {
                "field": hit_field, "value": hit_value, "raw": raw, "confidence": conf,
                "rule": rule_name, "image_id": image_id, "region_id": region_id,
                "bbox": bbox, "verified": False,
            }

    unclassified: list[tuple[models.InspectionImage, models.OcrResult, OcrRegion]] = []
    tallest_row_ids: set[int] = set()
    for img_id in sorted(by_image, key=lambda k: _region_sort_key(images[k])):
        img = images[img_id]
        regs = by_image[img_id]
        if not regs:
            continue
        # Convert ORM rows into geometry-rich region objects once (bbox lives in JSON)
        items: list[tuple[models.OcrResult, OcrRegion]] = []
        for r in regs:
            bbox = r.bbox or {}
            items.append((r, OcrRegion(text=r.text, confidence=r.confidence, x=bbox.get("x", 0),
                                       y=bbox.get("y", 0), w=bbox.get("width", 0), h=bbox.get("height", 0))))
        # tallest text near the top => product heading candidate
        tallest_row: models.OcrResult | None = None
        tallest_region: OcrRegion | None = None
        for r, region in items:
            if region.y < 0.30 and (tallest_region is None or region.h > tallest_region.h):
                tallest_row, tallest_region = r, region
        if tallest_row is not None and tallest_row.id:
            tallest_row_ids.add(tallest_row.id)

        for r, region in items:
            bbox = region.to_dict()["bounding_box"]
            hits = classify_line(region)
            for h in hits:
                consider(h.field, h.value, h.raw, h.confidence, h.rule_name, img_id, r.region_id, bbox)
            entity = classify_entity_line(region)
            if entity:
                consider(entity.field, entity.value, entity.raw, entity.confidence, entity.rule_name,
                         img_id, r.region_id, bbox)
            if not hits and not entity:
                unclassified.append((img, r, region))

    # ---- Optional LLM pass for lines the deterministic matcher could not label ----
    llm_used = False
    if settings.FIELD_MATCHER == "ollama":
        llm = OllamaFieldMatcher()
        if llm.available():
            llm_used = True
            unresolved = [
                (r, region) for (_img, r, region) in unclassified
                if not classify_plain_line(region, top_zone=region.y < 0.30, is_tallest=False)
            ]
            mapping = llm.match([region.text for (_r, region) in unresolved])
            for idx, field_name in mapping.items():
                r, region = unresolved[idx]
                consider(field_name, region.text, region.text, region.confidence * 0.92, "llm",
                         r.image_id, r.region_id, region.to_dict()["bounding_box"])

    # ---- Deterministic fallbacks (address hints / product heading) ----
    for img, r, region in unclassified:
        bbox = region.to_dict()["bounding_box"]
        is_tallest = r.id in tallest_row_ids
        fallback = classify_plain_line(region, top_zone=region.y < 0.30, is_tallest=is_tallest)
        if fallback:
            consider(fallback.field, fallback.value, fallback.raw, fallback.confidence,
                     fallback.rule_name, r.image_id, r.region_id, bbox)

    # ---- Persist candidate fields (one row per field per image) ----
    sort_index = 0
    present_fields: set[str] = set()
    for key, hit in candidates.items():
        field_name = key[0]
        if hit["field"] in ("brand", "product_type") and field_name in present_fields:
            continue
        status = FIELD_DETECTED if hit["confidence"] >= HIGH_CONF else FIELD_UNCERTAIN
        reason = ""
        if status == FIELD_UNCERTAIN:
            reason = (f"Low OCR confidence ({hit['confidence']:.0%}); verify the value against the image.")
        db.add(models.ExtractedField(
            inspection_id=inspection.id,
            image_id=hit["image_id"],
            field_name=field_name,
            category=models_FIELD_CATEGORY(field_name),
            value=hit["value"],
            raw_text=hit["raw"],
            confidence=hit["confidence"],
            status=status,
            reason=reason,
            verified=False,
            source="ocr",
            bbox=hit["bbox"],
            region_id=hit["region_id"],
            sort=sort_index,
        ))
        present_fields.add(field_name)
        sort_index += 1

    # Re-apply inspector corrections
    for field_name, corr in kept_corrections.items():
        match = [f for f in candidates if f == field_name]
        if match:
            row = (
                db.query(models.ExtractedField)
                .filter(models.ExtractedField.inspection_id == inspection.id,
                        models.ExtractedField.field_name == field_name)
                .first()
            )
            if row:
                row.original_value = row.value
                row.value = corr["value"]
                row.correction_reason = corr["reason"]
                row.source = "inspector"
                row.status = FIELD_DETECTED
                row.reason = ""
                row.verified = True
    db.commit()

    # ---- Not-found rows for mandatory declarations (kept out of binary pass/fail) ----
    existing = {f.field_name for f in db.query(models.ExtractedField).filter(
        models.ExtractedField.inspection_id == inspection.id).all()}
    missing = [fn for fn in MANDATORY_FIELD_SET if fn not in existing]
    for fn in missing:
        if fn in ("country_of_origin", "best_before"):
            continue  # applicability is decided by the rule engine
        db.add(models.ExtractedField(
            inspection_id=inspection.id, image_id=None, field_name=fn,
            category=models_FIELD_CATEGORY(fn), value="", raw_text="", confidence=0.0,
            status=FIELD_NOT_FOUND, reason="Not identified across the captured package panels.",
            verified=False, source="ocr", sort=sort_index,
        ))
        sort_index += 1
    db.commit()

    fields = db.query(models.ExtractedField).filter(
        models.ExtractedField.inspection_id == inspection.id).order_by(models.ExtractedField.sort).all()
    high = [f for f in fields if f.confidence >= HIGH_CONF and f.status != FIELD_NOT_FOUND]
    low = [f for f in fields if 0 < f.confidence < HIGH_CONF]
    missing_rows = [f for f in fields if f.status == FIELD_NOT_FOUND]
    return {
        "fields_identified": len([f for f in fields if f.status != FIELD_NOT_FOUND]),
        "high_confidence": len(high),
        "needs_verification": [{"field": f.field_name, "label": f.field_name.replace("_", " ").title(),
                                "value": f.value, "confidence": f.confidence} for f in low],
        "not_detected": [{"field": f.field_name, "label": f.field_name.replace("_", " ").title()} for f in missing_rows],
        "llm_used": llm_used,
        "images_processed": len(images),
        "text_regions": len(ocr_rows),
    }


def models_FIELD_CATEGORY(field_name: str) -> str:
    from .matcher import FIELD_CATALOG

    return FIELD_CATALOG.get(field_name, {}).get("category", "other")


def ensure_field_rows(db: Session, inspection: models.Inspection) -> None:
    """Create default not_found rows for mandatory declarations (used for fresh inspections)."""
    existing = {f.field_name for f in db.query(models.ExtractedField).filter(
        models.ExtractedField.inspection_id == inspection.id).all()}
    for fn in MANDATORY_FIELD_SET:
        if fn not in existing:
            db.add(models.ExtractedField(
                inspection_id=inspection.id, image_id=None, field_name=fn,
                category=models_FIELD_CATEGORY(fn), value="", raw_text="", confidence=0.0,
                status=FIELD_NOT_FOUND, verified=False, source="ocr",
            ))
    db.commit()


def ocr_summary(db: Session, inspection: models.Inspection) -> dict:
    ocr_rows = db.query(models.OcrResult).filter(models.OcrResult.inspection_id == inspection.id).all()
    fields = db.query(models.ExtractedField).filter(
        models.ExtractedField.inspection_id == inspection.id).order_by(models.ExtractedField.sort).all()
    images = inspection.images
    engine_counts: dict[str, int] = {}
    fallback_images: list[str] = []
    for i in images:
        if i.ocr_engine:
            engine_counts[i.ocr_engine] = engine_counts.get(i.ocr_engine, 0) + 1
        if i.ocr_fallback_used:
            fallback_images.append(i.image_id)
    return {
        "images_total": len(images),
        "images_processed": len([i for i in images if i.processing_status == IMG_STATUS_DONE]),
        "text_regions": len(ocr_rows),
        "fields_total": len(fields),
        "fields_identified": len([f for f in fields if f.status != FIELD_NOT_FOUND]),
        "high_confidence": len([f for f in fields if f.confidence >= HIGH_CONF and f.status != FIELD_NOT_FOUND]),
        "needs_verification": len([f for f in fields if f.status == FIELD_UNCERTAIN]),
        "not_detected": len([f for f in fields if f.status == FIELD_NOT_FOUND]),
        "verified": len([f for f in fields if f.verified]),
        "engine_counts": engine_counts,
        "fallback_images": fallback_images,
        # Honest field-matcher disclosure: 'ollama' = real LLM (Qwen/Ollama)
        # actually consulted; anything else = deterministic rules only.
        "matcher_mode": settings.FIELD_MATCHER,
        "matcher_label": (
            "Ollama LLM (Qwen) — real field-matcher"
            if settings.FIELD_MATCHER == "ollama"
            else "Deterministic rules — simulated field-matcher"
        ),
    }
