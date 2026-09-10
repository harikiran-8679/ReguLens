"""Shared builders for per-violation evidence blocks.

Every surface that shows evidence (Violation Details, Evidence Management,
Final Report Preview and the generated PDF/DOCX) renders the SAME block shape:

    Evidence for: <rule_id / violation title>
    Source image: <original image filename/id, e.g. IMG-00129-01 (front)>
    Description:  <short, data-derived description of what the evidence shows>
    [image with region overlay]

Descriptions are generated from the persisted rule_result / finding rows
(observed vs expected, field, category, rule citation) — never from static
placeholder text. Source image metadata is always resolved to the real
InspectionImage row so the browser can load the file and the PDF/DOCX
generator can embed it.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from .. import models
from ..config import settings

REGULATION_NAME = "Legal Metrology (Packaged Commodities) Rules, 2011"


def _field_label(field_name: str | None) -> str:
    if not field_name:
        return ""
    from .matcher import FIELD_CATALOG  # local import avoids circular deps

    label = FIELD_CATALOG.get(field_name, {}).get("label")
    if label:
        return label
    return " ".join(w.capitalize() for w in field_name.split("_"))


def format_observed(observed: dict | None) -> str:
    """Human-readable rendering of a rule_result.observed payload."""
    if not observed:
        return ""
    if observed.get("status") == "NOT_DETECTED":
        return "declaration not detected on the captured panels"
    if observed.get("status") in ("DETECTED", "UNCERTAIN", "present", "CORRECTED"):
        if observed.get("status") == "UNCERTAIN":
            return "declaration possibly present (low OCR confidence)"
        return "declaration present on the package"
    if "estimated_height_ratio" in observed:
        return f"estimated declared text height ratio {observed['estimated_height_ratio']}"
    if "value_1" in observed or "value_2" in observed:
        a, b = observed.get("value_1") or {}, observed.get("value_2") or {}
        src_a = a.get("source") or "package declaration"
        src_b = b.get("source") or "compared source"
        return f"{_fmt_raw(a)} ({src_a}) vs {_fmt_raw(b)} ({src_b})"
    if "error" in observed and "reason" in observed:
        return str(observed["reason"])
    if "value" in observed:
        val = str(observed["value"])
        if observed.get("currency"):
            val = f"{observed['currency']} {val}"
        if observed.get("unit") and observed["unit"] not in val:
            val = f"{val} {observed['unit']}"
        return val
    pieces = [f"{k}: {v}" for k, v in observed.items() if k not in ("status",)]
    return "; ".join(pieces) if pieces else ""


def _fmt_raw(v: dict | str | int | None) -> str:
    if not isinstance(v, dict):
        return str(v) if v is not None else "—"
    val = v.get("value")
    if val is None and v.get("image_id"):
        return f"({v['image_id']})"
    if val is None:
        return "—"
    return str(val)


def format_expected(expected: dict | None, fallback: str = "") -> str:
    """Human-readable rendering of a rule_result.expected payload."""
    if not expected:
        return fallback
    if len(expected) == 1 and expected.get("required") is True:
        return "required declaration present on the package"
    if "minimum_ratio" in expected:
        return f"minimum estimated declared text height ratio {expected['minimum_ratio']}"
    if expected.get("standard_unit") is True:
        return "net quantity expressed in a standard unit of mass/volume"
    if expected.get("matches_listing") is True:
        return "package declaration must match the online listing value"
    if "format" in expected:
        return f"formatted as {expected['format']}"
    pieces = [f"{k}: {v}" for k, v in expected.items()]
    return "; ".join(pieces) if pieces else fallback


def describe_violation(finding: models.Finding | None,
                       rule_result: models.RuleResult | None = None,
                       evidence: models.Evidence | None = None) -> str:
    """Auto-generate a specific description from real compliance data.

    Combines the field (with a human label), the persisted observed/expected
    values and the rule citation — e.g.:

      “MRP (Retail Sale Price) declaration — observed estimated declared text
       height ratio 0.0177; expected minimum estimated declared text height
       ratio 0.02 according to Rule 7 · 7(3) (as amended) — Legal Metrology
       (Packaged Commodities) Rules, 2011.”
    """
    finding = finding or models.Finding()
    field = (
        (evidence.field_name if evidence and evidence.field_name else "")
        or finding.source_field
        or (rule_result.field if rule_result else "")
    )
    category = (rule_result.category if rule_result else None) or finding.finding_type
    cat_label = (category or "compliance").replace("_", " ").strip().title()
    region_label = _field_label(field) or cat_label or "Declaration region"

    obs = format_observed(rule_result.observed if rule_result else None)
    exp = format_expected(rule_result.expected if rule_result else None,
                          fallback=finding.expected_condition or "")

    parts = [region_label]
    if obs:
        parts.append(f"observed {obs}")
    if exp:
        parts.append(f"expected {exp}")

    citation = " ".join([finding.rule_number or "", finding.sub_rule or ""]).strip()
    if not citation and rule_result:
        citation = " ".join([rule_result.rule_number or "",
                             rule_result.sub_rule or ""]).strip()
    if rule_result and rule_result.rule and rule_result.rule.rule_id:
        citation = f"{citation} ({rule_result.rule.rule_id})".strip()

    text = " — ".join(parts).rstrip("; ") + "."
    if citation:
        text += f" Rule citation: {citation} — {REGULATION_NAME}."
    return text
def source_image_payload(img: models.InspectionImage | None,
                         bbox_px: list | None = None) -> dict | None:
    """Browser + PDF renderable description of the source image row."""
    if img is None:
        return None
    return {
        "id": img.id,
        "image_id": img.image_id,
        "side": img.side,
        "width": img.width,
        "height": img.height,
        "storage_path": img.storage_path,
        "bbox_px": bbox_px,
    }


def normalized_bbox_from_px(img: models.InspectionImage | None,
                            px: list | None) -> dict | None:
    if not img or not px or len(px) != 4:
        return None
    x0, y0, x1, y1 = (max(0.0, float(v)) for v in px)
    w = max(img.width or 1, 1)
    h = max(img.height or 1, 1)
    nx0, ny0, nx1, ny1 = x0 / w, y0 / h, min(x1 / w, 1.0), min(y1 / h, 1.0)
    return {"x": nx0, "y": ny0, "width": nx1 - nx0, "height": ny1 - ny0}


def build_context(inspection: models.Inspection) -> dict:
    """Shared lookup tables for one inspection (no extra DB queries)."""
    images = sorted(inspection.images, key=lambda i: i.id)
    img_by_pub = {i.image_id: i for i in images}
    img_by_id = {i.id: i for i in images}
    rr_by_id = {rr.id: rr for rr in (inspection.rule_results or [])}
    ocr_by_image: dict[int, list[models.OcrResult]] = defaultdict(list)
    for r in (inspection.ocr_results or []):
        ocr_by_image[r.image_id].append(r)
    return {"images": images, "img_by_pub": img_by_pub,
            "img_by_id": img_by_id, "rr_by_id": rr_by_id,
            "ocr_by_image": ocr_by_image}


def _region_bbox(ctx: dict, img: models.InspectionImage | None,
                 region_id: str) -> dict | None:
    if not img or not region_id:
        return None
    for r in ctx["ocr_by_image"].get(img.id, []):
        if r.region_id == region_id:
            return r.bbox or None
    return None


def enrich_finding(finding: models.Finding, ctx: dict) -> dict:
    """Enrich a Finding dict for the Violation Details page."""
    from .. import serializers as _ser  # local import avoids circular at module level
    rr = ctx["rr_by_id"].get(finding.rule_result_id)
    img = ctx["img_by_pub"].get(finding.source_image_id or "")
    bbox_norm = _region_bbox(ctx, img, finding.ocr_region_id)
    if bbox_norm is None and rr and rr.evidence:
        ev_img = ctx["img_by_pub"].get((rr.evidence or {}).get("image_id") or "")
        bbox_norm = normalized_bbox_from_px(
            ev_img, (rr.evidence or {}).get("bbox") or None)
    return {
        "id": finding.id,
        "finding_id": finding.finding_id,
        "finding_type": finding.finding_type,
        "requirement": finding.requirement,
        "detected_condition": finding.detected_condition,
        "expected_condition": finding.expected_condition,
        "engine_result": finding.engine_result,
        "severity": finding.severity,
        "confidence": finding.confidence,
        "source_image_id": finding.source_image_id,
        "ocr_region_id": finding.ocr_region_id,
        "source_field": finding.source_field,
        "rule_number": finding.rule_number,
        "sub_rule": finding.sub_rule,
        "inspector_status": finding.inspector_status,
        # B2: human-readable label so UI never shows raw 'rejected'/'confirmed'
        "inspector_status_label": _ser._inspector_status_label(
            finding.inspector_status, finding.inspector_result),
        "inspector_result": finding.inspector_result,
        "inspector_note": finding.inspector_note,
        "rule_id": (rr.rule.rule_id if rr and rr.rule else None),
        "category": (rr.category if rr else finding.finding_type),
        "title": (rr.title if rr and rr.title else finding.requirement),
        "rule_citation": " ".join([finding.rule_number or "",
                                   finding.sub_rule or ""]).strip(),
        "observed": rr.observed if rr else None,
        "expected": rr.expected if rr else None,
        "violation_description": describe_violation(finding, rr),
        "source_image": source_image_payload(img),
        "bbox_normalized": bbox_norm,
    }


def auto_evidence_description(evidence: models.Evidence,
                              finding: models.Finding | None,
                              rule_result: models.RuleResult | None) -> str:
    if finding is None and rule_result is None:
        return evidence.description or ""
    return describe_violation(finding, rule_result, evidence)


def violation_evidence_blocks(db: Session,
                              inspection: models.Inspection) -> list[dict]:
    """Per-violation evidence blocks for the report preview and PDF/DOCX.

    Each violation gets its own section with a labelled evidence entry —
    one evidence block per violation, never a shared generic gallery.
    """
    ctx = build_context(inspection)
    findings = sorted(inspection.findings or [], key=lambda f: f.sort_order)
    evidence_rows = db.query(models.Evidence).filter(
        models.Evidence.inspection_id == inspection.id).order_by(
        models.Evidence.sort_order).all() if inspection.id else []
    ev_by_finding: dict[str, list[models.Evidence]] = defaultdict(list)
    for e in evidence_rows:
        if e.finding_id:
            ev_by_finding[e.finding_id].append(e)

    blocks = []
    for f in findings:
        rr = ctx["rr_by_id"].get(f.rule_result_id)
        items = []
        for e in ev_by_finding.get(f.finding_id, []):
            img = ctx["img_by_pub"].get(e.source_image_id or "")
            items.append({
                "evidence_id": e.evidence_id,
                "evidence_type": e.evidence_type,
                "rule_id": e.rule_id,
                "field_name": e.field_name,
                "region_id": e.region_id,
                "status": e.status,
                "description": auto_evidence_description(e, f, rr),
                "source_image": source_image_payload(
                    img, _rule_result_bbox_px(rr)),
                "bbox_normalized": _region_bbox(ctx, img, e.region_id) if img else None,
            })
        # Fallback: no Evidence row linked — derive the block straight from the
        # persisted rule_result evidence (image id + region bounding box).
        if not items and rr and rr.evidence:
            img = ctx["img_by_pub"].get((rr.evidence or {}).get("image_id") or "")
            if img:
                items.append({
                    "evidence_id": f.finding_id,
                    "evidence_type": "evidence_region",
                    "rule_id": (rr.rule.rule_id if rr.rule else None),
                    "field_name": rr.field or f.source_field,
                    "region_id": f.ocr_region_id,
                    "status": "linked",
                    "description": describe_violation(f, rr),
                    "source_image": source_image_payload(
                        img, (rr.evidence or {}).get("bbox") or None),
                    "bbox_normalized": normalized_bbox_from_px(
                        img, (rr.evidence or {}).get("bbox") or None),
                })
        if not items:
            continue

        img = ctx["img_by_pub"].get(f.source_image_id or "")
        blocks.append({
            "finding_id": f.finding_id,
            "rule_id": (rr.rule.rule_id if rr and rr.rule else None),
            "rule_citation": " ".join([f.rule_number or "",
                                       f.sub_rule or ""]).strip(),
            "title": (rr.title if rr and rr.title else f.requirement),
            "category": (rr.category if rr else f.finding_type),
            "requirement": f.requirement,
            "detected": f.detected_condition,
            "expected": f.expected_condition,
            "inspector_status": f.inspector_status,
            "details_present": bool(rr),
            "description": describe_violation(f, rr),
            "source_image": source_image_payload(img),
            "evidence": items,
        })
    return blocks


def _rule_result_bbox_px(rr: models.RuleResult | None) -> list | None:
    if rr and rr.evidence:
        return (rr.evidence or {}).get("bbox") or None
    return None


def crop_evidence_image(storage_path: str,
                        bbox_px: list | None = None,
                        bbox_norm: dict | None = None):
    """Return a cropped BytesIO JPEG of the evidenced region (or full image).

    Returns None when the underlying file is missing so the report builder
    degrades gracefully instead of failing generation.
    """
    import io

    from PIL import Image

    path = settings.storage_dir / storage_path
    if not path.exists():
        return None
    try:
        im = Image.open(path).convert("RGB")
        box = None
        if bbox_px and len(bbox_px) == 4:
            x0, y0, x1, y1 = bbox_px
            cw, ch = im.size
            box = (max(0, int(x0)), max(0, int(y0)),
                   min(cw, max(1, int(x1))), min(ch, max(1, int(y1))))
        elif bbox_norm:
            w, h = im.size
            x0 = bbox_norm.get("x", 0) * w
            y0 = bbox_norm.get("y", 0) * h
            x1 = (bbox_norm.get("x", 0) + bbox_norm.get("width", 1)) * w
            y1 = (bbox_norm.get("y", 0) + bbox_norm.get("height", 1)) * h
            box = (max(0, int(x0)), max(0, int(y0)),
                   min(w, max(1, int(x1))), min(h, max(1, int(y1))))
        if box and (box[2] - box[0]) > 4 and (box[3] - box[1]) > 4:
            im = im.crop(box)
            im.thumbnail((900, 900))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        buf.seek(0)
        return buf
    except Exception:  # pragma: no cover - defensive: never kill report generation
        return None