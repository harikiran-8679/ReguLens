"""Report endpoints: preview the assembled report, generate PDF/DOCX files,
list report history and download generated files."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models, serializers
from ..config import settings
from ..database import get_db
from ..deps import get_current_user, get_inspection_or_404, require_owner_or_admin
from ..schemas import ReportGenerateRequest
from ..services.audit import record
from ..services.report_builder import generate_docx, generate_pdf, report_payload

router = APIRouter(tags=["reports"])


@router.get("/inspections/{inspection_id}/report/preview")
def report_preview(inspection_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    payload = report_payload(db, inspection)
    history = db.query(models.Report).filter(
        models.Report.inspection_id == inspection.id).order_by(models.Report.id).all()
    payload["history"] = [serializers.report_dict(r) for r in history]
    # Completeness check
    missing = []
    if not payload["inspection"]["inspection_id"]:
        missing.append("Inspection information")
    if not payload["product"]["product_name"]:
        missing.append("Product information")
    if not payload["rule_basis"]["rule_set_version"] or payload["rule_basis"]["rule_set_version"] == "—":
        missing.append("Applicable rule version")
    if not payload["assessment"]["final_compliance_status"]:
        missing.append("Final compliance assessment")
    if payload["assessment"]["automated_result"] is None:
        missing.append("Rule-engine analysis")
    payload["completeness"] = {"ready": len(missing) == 0, "missing": missing}
    return payload


def _next_version(db: Session, inspection: models.Inspection, report_type: str) -> str:
    existing = db.query(models.Report).filter(
        models.Report.inspection_id == inspection.id,
        models.Report.report_type == report_type).count()
    return f"1.{existing}" if existing else "1.0"


@router.post("/inspections/{inspection_id}/report/generate")
def generate_report(inspection_id: int, body: ReportGenerateRequest,
                    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    if inspection.status != "finalized":
        raise HTTPException(400, "Only finalised inspections can generate official reports. "
                                 "Complete the Inspector Review stage first.")
    if body.report_type not in ("pdf", "docx"):
        raise HTTPException(422, "report_type must be pdf | docx")

    version = _next_version(db, inspection, body.report_type)
    folder = settings.storage_dir / "reports" / inspection.inspection_id
    folder.mkdir(parents=True, exist_ok=True)
    rel = f"reports/{inspection.inspection_id}/v{version}.{body.report_type}"
    path = settings.storage_dir / rel

    report = models.Report(
        report_id=f"RPT-{inspection.inspection_id.split('-')[-1]}-{version.replace('.', '')}"
                  f"{'A' if body.report_type == 'docx' else ''}",
        inspection_id=inspection.id, report_version=version, report_type=body.report_type,
        template_id="standard_inspection_report", template_version="1.0",
        rule_set_version=(inspection.rule_set_snapshot or {}).get("rule_set_version", "current"),
        generated_by=user.username, generated_at=dt.datetime.now(dt.timezone.utc),
        file_reference=rel, generation_status="generating",
        included_sections=body.sections or ["all"],
    )
    db.add(report)
    db.commit()
    try:
        gen = generate_pdf if body.report_type == "pdf" else generate_docx
        digest = gen(db, inspection, path)
        report.generation_status = "generated"
        report.validation_status = "passed"
        report.file_hash = digest
    except Exception as exc:  # pragma: no cover
        report.generation_status = "failed"
        report.validation_status = "failed"
        db.commit()
        raise HTTPException(500, f"Report generation failed: {exc}") from exc
    db.commit()
    record(db, actor_user=user, inspection_id=inspection.id, action="report_generated",
           entity_type="report", entity_id=report.report_id,
           details={"type": body.report_type, "version": version})
    return serializers.report_dict(report)


@router.get("/inspections/{inspection_id}/reports")
def report_history(inspection_id: int, db: Session = Depends(get_db),
                   user: models.User = Depends(get_current_user)):
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    history = db.query(models.Report).filter(
        models.Report.inspection_id == inspection.id).order_by(models.Report.id.desc()).all()
    return {"items": [serializers.report_dict(r) for r in history]}


@router.get("/reports/{report_id}/download")
def download_report(report_id: int, db: Session = Depends(get_db),
                    user: models.User = Depends(get_current_user)):
    report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if report is None:
        raise HTTPException(404, "Report not found.")
    inspection = get_inspection_or_404(report.inspection_id, db)
    require_owner_or_admin(inspection, user)
    path = settings.storage_dir / report.file_reference
    if not path.exists():
        raise HTTPException(404, "Report file missing on disk.")
    media = "application/pdf" if report.report_type == "pdf" else (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return FileResponse(str(path), media_type=media,
                        filename=f"{inspection.inspection_id}_report_v{report.report_version}.{report.report_type}")
