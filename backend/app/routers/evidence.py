"""Evidence management endpoints (list/traceability, annotations, additions)."""
from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import models, serializers
from ..config import settings
from ..database import get_db
from ..deps import get_current_user, get_inspection_or_404, require_owner_or_admin
from ..schemas import EvidenceUpdate
from ..services.audit import record
from ..services import quality as quality_service
from ..services.evidence_blocks import (
    auto_evidence_description,
    build_context,
    source_image_payload,
)
from ..utils import IMG_SIDES

router = APIRouter(tags=["evidence"])


@router.get("/inspections/{inspection_id}/evidence")
def evidence_board(inspection_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    rows = db.query(models.Evidence).filter(
        models.Evidence.inspection_id == inspection.id).order_by(
        models.Evidence.sort_order).all()
    findings = db.query(models.Finding).filter(
        models.Finding.inspection_id == inspection.id).all()
    findings_linked = {f.finding_id: False for f in findings}
    for e in rows:
        if e.finding_id in findings_linked:
            findings_linked[e.finding_id] = True
    ctx = build_context(inspection)
    findings_by_id = {f.finding_id: f for f in findings}
    rr_by_finding = {f.finding_id: ctx["rr_by_id"].get(f.rule_result_id)
                     for f in findings}
    items = []
    for e in rows:
        d = serializers.evidence_dict(e)
        img = ctx["img_by_pub"].get(e.source_image_id or "")
        d["source_image"] = source_image_payload(img)
        f = findings_by_id.get(e.finding_id or "")
        rr = rr_by_finding.get(e.finding_id or "")
        d["auto_description"] = auto_evidence_description(e, f, rr)
        d["violation"] = None
        if f is not None:
            d["violation"] = {
                "finding_id": f.finding_id,
                "rule_id": (rr.rule.rule_id if rr and rr.rule else None),
                "title": (rr.title if rr and rr.title else f.requirement),
                "rule_citation": " ".join([f.rule_number or "",
                                           f.sub_rule or ""]).strip(),
            }
        items.append(d)
    images = {i.image_id: serializers.image_dict(i) for i in inspection.images}
    return {
        "summary": {
            "images": len(inspection.images),
            "findings": len(findings),
            "linked": len([e for e in rows if e.status == "linked"]),
            "review": len([e for e in rows if e.status == "review"]),
        },
        "items": items,
        "findings": [{"finding_id": f.finding_id, "requirement": f.requirement,
                      "supported": findings_linked[f.finding_id]} for f in findings],
        "images": list(images.values()),
    }


@router.patch("/evidence/{evidence_id}")
def update_evidence(evidence_id: int, body: EvidenceUpdate,
                    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    evidence = db.query(models.Evidence).filter(models.Evidence.id == evidence_id).first()
    if evidence is None:
        raise HTTPException(404, "Evidence item not found.")
    inspection = get_inspection_or_404(evidence.inspection_id, db)
    require_owner_or_admin(inspection, user)
    if body.observation is not None:
        evidence.observation = body.observation
    if body.relevance in ("relevant", "not_relevant", "inconclusive"):
        evidence.relevance = body.relevance
        if body.relevance == "not_relevant" and evidence.status == "linked":
            evidence.status = "not_used"
    if body.status in ("linked", "review", "available", "not_used", "insufficient"):
        evidence.status = body.status
    if body.finding_id:
        evidence.finding_id = body.finding_id
        evidence.status = "linked"
    db.commit()
    record(db, actor_user=user, inspection_id=inspection.id, action="evidence_updated",
           entity_type="evidence", entity_id=evidence.evidence_id,
           details={"observation": body.observation, "relevance": body.relevance, "status": body.status})
    return serializers.evidence_dict(evidence)


@router.post("/inspections/{inspection_id}/evidence/upload")
def add_evidence_photo(
    inspection_id: int,
    file: UploadFile = File(...),
    evidence_type: str = Form(default="inspector_photo"),
    related_finding: str = Form(default=""),
    description: str = Form(default=""),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    if inspection.status == "finalized":
        raise HTTPException(400, "Finalised inspections are read-only.")
    data = file.file.read()
    report = quality_service.quick_assess_bytes(data)
    if report["checks"][0]["metric"] == "image_load" and report["overall"] == "poor":
        raise HTTPException(400, "Uploaded file is not a readable image.")
    folder = settings.storage_dir / "evidence" / inspection.inspection_id
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "evidence.jpg").suffix or ".jpg"
    rel = f"evidence/{inspection.inspection_id}/{uuid.uuid4().hex}{suffix.lower()}"
    path = settings.storage_dir / rel
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    seq = db.query(models.Evidence).filter(models.Evidence.inspection_id == inspection.id).count() + 1
    item = models.Evidence(
        evidence_id=f"EVD-{inspection.inspection_id.split('-')[-1]}-{seq:03d}",
        inspection_id=inspection.id,
        evidence_type=evidence_type if evidence_type in (
            "source_image", "evidence_region", "ocr_region", "font_evidence",
            "placement_evidence", "inspector_photo", "additional") else "inspector_photo",
        finding_id=related_finding or None,
        description=description,
        status="linked" if related_finding else "available",
        file_reference=rel,
        integrity_hash=digest,
        captured_by=user.username,
        sort_order=seq,
    )
    db.add(item)
    db.commit()
    record(db, actor_user=user, inspection_id=inspection.id, action="evidence_added",
           entity_type="evidence", entity_id=item.evidence_id, details={"finding": related_finding})
    return serializers.evidence_dict(item)
