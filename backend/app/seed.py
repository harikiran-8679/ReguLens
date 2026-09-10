"""Bootstrap seed data.

Seeds are rich on purpose so every screen has real data at first boot:
  * default Admin + Inspectors (controlled accounts — no public sign-up),
  * product categories,
  * 229 versioned rules from the authoritative Legal Metrology (Packaged
    Commodities) Rules 2011-2026 register (extracted from the PDF and mapped
    to the engine's four-state evaluation schema — see backend/data/rules_230.json
    and backend/tools/extract_rules.py for the extraction pipeline),
  * five demo inspections whose sample labels are *generated*, then pushed
    through the actual pipeline: image quality -> OCR (demo engine w/ recorded
    ground truth) -> deterministic field matching -> rule engine -> findings /
    evidence, with PDF/DOCX reports generated for finalised records.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session  

from . import models
from .config import settings
from .security import hash_password
from .utils import (
    FIELD_NOT_FOUND,
    FINAL_COMPLIANT,
    FINAL_NON_COMPLIANT,
    INSP_STATUS_FINALIZED,
    INSP_STATUS_PENDING_REVIEW,
    ROLE_ADMIN,
    ROLE_INSPECTOR,
    USER_STATUS_ACTIVE,
    USER_STATUS_INACTIVE,
    USER_STATUS_PENDING,
)
from .services import quality as quality_service
from .services.labelgen import LabelItem, LabelSpec, build_label
from .services.pipeline import run_field_matching, run_ocr
from .services.report_builder import generate_docx, generate_pdf
from .services.rule_engine import run_rule_analysis


def _seed_users(db: Session) -> None:
    # Fixed, memorable demo accounts. Always ensured (upsert) so they survive any
    # restart / partial reseed — never random-generated, never lost.
    demo_accounts = [
        dict(username="admin@demo.com", full_name="Demo Administrator", role=ROLE_ADMIN,
             department="Legal Metrology Administration", status=USER_STATUS_ACTIVE,
             password="Admin@123"),
        dict(username="inspector@demo.com", full_name="Demo Inspector", role=ROLE_INSPECTOR,
             department="Legal Metrology Enforcement", status=USER_STATUS_ACTIVE,
             password="Inspector@123"),
    ]
    for u in demo_accounts:
        existing = db.query(models.User).filter(models.User.username == u["username"]).first()
        if existing:
            continue
        pwd = u.pop("password")
        db.add(models.User(**u, password_hash=hash_password(pwd)))
    db.commit()

    # The remaining controlled accounts are seeded only once (marker = LM-INS-00125).
    if db.query(models.User).filter(models.User.username == "LM-INS-00125").first():
        return
    users = [
        dict(username="ADM-001", full_name="System Administrator", role=ROLE_ADMIN,
             department="Legal Metrology Administration", status=USER_STATUS_ACTIVE),
        dict(username="LM-INS-00125", full_name="Inspector A. Sharma", role=ROLE_INSPECTOR,
             department="Legal Metrology Enforcement", status=USER_STATUS_ACTIVE),
        dict(username="LM-INS-00131", full_name="Inspector R. Verma", role=ROLE_INSPECTOR,
             department="Legal Metrology Enforcement", status=USER_STATUS_ACTIVE),
        dict(username="LM-INS-00150", full_name="Inspector (Pending)", role=ROLE_INSPECTOR,
             department="Legal Metrology Enforcement", status=USER_STATUS_PENDING),
        dict(username="LM-INS-00160", full_name="Inspector (Deactivated)", role=ROLE_INSPECTOR,
             department="Legal Metrology Enforcement", status=USER_STATUS_INACTIVE),
    ]
    for u in users:
        pwd = u.pop("password", None) or ("admin123" if u["role"] == ROLE_ADMIN else "inspector123")
        db.add(models.User(**u, password_hash=hash_password(pwd)))
    db.commit()


def _seed_categories(db: Session) -> None:
    if db.query(models.ProductCategory).count() > 0:
        return
    cats = [
        ("food_grain", "Food Grains, Pulses & Staples", False),
        ("edible_oil", "Edible Oils & Ghee", False),
        ("beverages", "Beverages (Packaged)", False),
        ("snacks", "Snacks & Confectionery", False),
        ("dairy", "Dairy & Frozen Products", False),
        ("personal_care", "Personal & Home Care", False),
        ("household", "Household Products", False),
        ("imported_food", "Imported Packaged Food", True),
        ("other", "Other Pre-Packaged Commodity", False),
    ]
    for code, label, imp in cats:
        db.add(models.ProductCategory(code=code, label=label, imported_only=imp))
    db.commit()


# ---------------------------------------------------------------------------
# Rules — loaded from the authoritative 229-record PDF extract
# ---------------------------------------------------------------------------
_RULES_JSON = Path(__file__).parent.parent / "data" / "rules_230.json"


def _load_rules_from_json() -> list[dict]:
    """Load the 229-rule set extracted from the Legal Metrology PDF.

    Falls back to an empty list with a warning if the JSON file is missing
    (e.g. a fresh clone before running extract_rules.py).  The file is
    committed to the repo so this should never happen in practice.
    """
    if not _RULES_JSON.exists():
        import logging
        logging.getLogger(__name__).warning(
            "rules_230.json not found at %s — no rules will be seeded. "
            "Run: python backend/tools/extract_rules.py", _RULES_JSON
        )
        return []
    with open(_RULES_JSON) as f:
        return json.load(f)


def _seed_rules(db: Session) -> None:
    """Seed the authoritative 229-rule set from the PDF extract.

    Idempotent: if LMPC-prefixed rules already exist the function returns
    immediately.  On first run (or after a DB reset) it:
      1. Removes any old PC-prefixed seed rows (the previous 23-rule set)
         that would otherwise create duplicates in the Rules & Standards view.
      2. Inserts all 229 LMPC-prefixed rules with correct scope, type,
         validation.kind and effective date metadata.
    """
    # Already seeded with the new set — nothing to do
    if db.query(models.Rule).filter(models.Rule.rule_id.like("LMPC-%")).count() > 0:
        return

    # Remove legacy PC-prefixed rules (old 23-rule hand-crafted set)
    legacy = db.query(models.Rule).filter(models.Rule.rule_id.like("PC-%")).all()
    for row in legacy:
        db.delete(row)
    db.flush()

    records = _load_rules_from_json()
    for r in records:
        eff_from_raw = r.get("effective_from") or "2011-04-01"
        eff_to_raw = r.get("effective_to")
        try:
            eff_from = dt.date.fromisoformat(str(eff_from_raw)[:10])
        except (ValueError, TypeError):
            eff_from = dt.date(2011, 4, 1)
        eff_to: dt.date | None = None
        if eff_to_raw:
            try:
                eff_to = dt.date.fromisoformat(str(eff_to_raw)[:10])
            except (ValueError, TypeError):
                eff_to = None
        db.add(models.Rule(
            rule_id=r["rule_id"],
            rule_number=str(r.get("rule_number") or ""),
            sub_rule=str(r.get("sub_rule") or ""),
            title=str(r.get("title") or ""),
            type=str(r.get("type") or "content"),
            scope=str(r.get("scope") or "image_checkable"),
            category=str(r.get("category") or "mandatory_declaration"),
            requirement=str(r.get("requirement") or ""),
            description=str(r.get("description") or ""),
            field=r.get("field") or None,
            required=bool(r.get("required", True)),
            applicability=r.get("applicability") or ["*"],
            conditions=r.get("conditions") or None,
            validation=r.get("validation") or {"kind": "present", "field": ""},
            severity=str(r.get("severity") or "major"),
            evidence_required=bool(r.get("evidence_required", True)),
            effective_from=eff_from,
            effective_to=eff_to,
            version=int(r.get("version") or 1),
            source=str(r.get("source") or ""),
            status=str(r.get("status") or "active"),
            sort_order=int(r.get("sort_order") or 0),
        ))
    db.commit()


# ---------------------------------------------------------------------------
# Demo label builders (explicit geometry so font/spacing checks behave)
# ---------------------------------------------------------------------------
def _item(text: str, box: tuple, conf: float = 0.97, bold: bool = False, size: int | None = None) -> LabelItem:
    return LabelItem(text=text, box=box, conf=conf, bold=bold, size_pt=size)


def front_compliant() -> LabelSpec:
    return LabelSpec(items=[
        _item("ABC PREMIUM RICE", (0.06, 0.06, 0.94, 0.16), conf=0.98, bold=True, size=100),
        _item("NET QTY: 5 kg", (0.06, 0.21, 0.94, 0.31), conf=0.97, bold=True, size=84),
        _item("M.R.P. Rs.450 (Inclusive of all taxes)", (0.06, 0.42, 0.94, 0.50), conf=0.94, bold=True, size=60),
        _item("Best Before: 6 Months from Packing", (0.08, 0.55, 0.92, 0.585), conf=0.96, size=30),
        _item("Manufactured & Packed by: ABC Foods Pvt. Ltd.", (0.05, 0.68, 0.95, 0.73), conf=0.97, size=40),
        _item("Plot 42, Industrial Estate, Hyderabad, Telangana - 500 001", (0.05, 0.75, 0.95, 0.80), conf=0.96, size=33),
        _item("Packed: AUG 2026", (0.05, 0.86, 0.95, 0.905), conf=0.98, size=34),
    ])


def front_failing() -> LabelSpec:
    return LabelSpec(items=[
        _item("ABC PREMIUM RICE", (0.06, 0.05, 0.94, 0.15), conf=0.98, bold=True, size=100),
        _item("NET QTY: 5 kg", (0.06, 0.20, 0.94, 0.30), conf=0.97, bold=True, size=84),
        # tight under the quantity declaration -> spacing check stays in review
        _item("Best Before: 6 Months from Packing", (0.08, 0.315, 0.92, 0.345), conf=0.96, size=30),
        # small MRP without the tax-inclusive wording -> font + wording findings
        _item("M.R.P. Rs.450", (0.06, 0.44, 0.94, 0.48), conf=0.94, bold=True, size=20),
        _item("Manufactured & Packed by: ABC Foods Pvt. Ltd.", (0.05, 0.60, 0.95, 0.65), conf=0.97, size=40),
        _item("Hyderabad, Telangana - 500 001", (0.05, 0.66, 0.95, 0.705), conf=0.94, size=33),
        _item("Packed: AUG 2026", (0.05, 0.86, 0.95, 0.905), conf=0.54, size=34),
    ])


def front_biscuits() -> LabelSpec:
    return LabelSpec(items=[
        _item("CRUNCHY BISCUITS", (0.06, 0.06, 0.94, 0.16), conf=0.98, bold=True, size=100),
        _item("NET QTY: 250 g", (0.06, 0.21, 0.94, 0.31), conf=0.97, bold=True, size=84),
        _item("M.R.P. Rs.40", (0.06, 0.42, 0.94, 0.50), conf=0.94, bold=True, size=56),
        _item("Best Before: 8 Months from Manufacture", (0.08, 0.56, 0.92, 0.59), conf=0.96, size=28),
        _item("Manufactured by: Sunrise Bakery Pvt. Ltd.", (0.05, 0.70, 0.95, 0.75), conf=0.97, size=40),
        _item("B-7, MIDC Industrial Area, Pune, Maharashtra - 411 019", (0.05, 0.77, 0.95, 0.82), conf=0.95, size=33),
    ])


def front_oil() -> LabelSpec:
    return LabelSpec(items=[
        _item("SUNPURE REFINED SUNFLOWER OIL", (0.06, 0.06, 0.94, 0.16), conf=0.98, bold=True, size=92),
        _item("NET QTY: 1 L", (0.06, 0.21, 0.94, 0.31), conf=0.97, bold=True, size=84),
        _item("M.R.P. Rs.245 (Inclusive of all taxes)", (0.06, 0.42, 0.94, 0.50), conf=0.94, bold=True, size=58),
        _item("Best Before: 9 Months from Packing", (0.08, 0.56, 0.92, 0.59), conf=0.96, size=28),
        _item("Packed by: Sunpure Foods Ltd.", (0.05, 0.70, 0.95, 0.75), conf=0.97, size=40),
        _item("12-A, Nariman Point, Mumbai, Maharashtra - 400 021", (0.05, 0.77, 0.95, 0.82), conf=0.95, size=33),
        _item("Packed: JUN 2026", (0.05, 0.86, 0.95, 0.905), conf=0.98, size=34),
    ])


def back_standard(with_consumer: bool) -> LabelSpec:
    items = [
        _item("Storage: Store in a cool and dry place", (0.08, 0.12, 0.92, 0.16), conf=0.93, size=30),
        _item("Packed & Marketed for retail sale in India", (0.08, 0.22, 0.92, 0.26), conf=0.9, size=26),
    ]
    if with_consumer:
        items.extend([
            _item("Consumer Care: 1800-123-4567 (Toll Free)", (0.08, 0.50, 0.92, 0.55), conf=0.97, size=40),
            _item("Email: care@abcfoods.in", (0.08, 0.60, 0.92, 0.635), conf=0.95, size=30),
        ])
    return LabelSpec(items=items)


def front_qty_conflict() -> LabelSpec:
    """Front panel declaring 500 g — the back panel declares a conflicting 250 g
    so the cross-field consistency check fires POTENTIAL_NON_COMPLIANCE."""
    return LabelSpec(items=[
        _item("ABC PREMIUM RICE", (0.06, 0.06, 0.94, 0.16), conf=0.98, bold=True, size=100),
        _item("NET QTY: 500 g", (0.06, 0.21, 0.94, 0.31), conf=0.97, bold=True, size=84),
        _item("M.R.P. Rs.450 (Inclusive of all taxes)", (0.06, 0.42, 0.94, 0.50), conf=0.94, bold=True, size=60),
        _item("Best Before: 6 Months from Packing", (0.08, 0.55, 0.92, 0.585), conf=0.96, size=30),
        _item("Manufactured & Packed by: ABC Foods Pvt. Ltd.", (0.05, 0.68, 0.95, 0.73), conf=0.97, size=40),
        _item("Plot 42, Industrial Estate, Hyderabad, Telangana - 500 001", (0.05, 0.75, 0.95, 0.80), conf=0.96, size=33),
        _item("Packed: AUG 2026", (0.05, 0.86, 0.95, 0.905), conf=0.98, size=34),
    ])


def back_qty_conflict() -> LabelSpec:
    """Back panel with a *different* net quantity (250 g) — the cross-field mismatch."""
    return LabelSpec(items=[
        _item("Storage: Store in a cool and dry place", (0.08, 0.10, 0.92, 0.14), conf=0.93, size=30),
        _item("NET QTY: 250 g", (0.08, 0.26, 0.92, 0.36), conf=0.97, bold=True, size=84),
        _item("Consumer Care: 1800-123-4567 (Toll Free)", (0.08, 0.52, 0.92, 0.57), conf=0.97, size=40),
        _item("Email: care@abcfoods.in", (0.08, 0.62, 0.92, 0.655), conf=0.95, size=30),
    ])


# ---------------------------------------------------------------------------
# Demo inspection scenarios (run through the real pipeline)
# ---------------------------------------------------------------------------
def _save_image(db: Session, inspection: models.Inspection, side: str, pil_image: Image.Image,
                ground_truth: list[dict]) -> models.InspectionImage:
    folder = settings.storage_dir / "samples" / inspection.inspection_id
    folder.mkdir(parents=True, exist_ok=True)
    rel = f"samples/{inspection.inspection_id}/{side}.jpg"
    path = settings.storage_dir / rel
    pil_image.save(path, "JPEG", quality=92)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    num = (
        db.query(models.InspectionImage)
        .filter(models.InspectionImage.inspection_id == inspection.id)
        .count()
        + 1
    )
    img = models.InspectionImage(
        inspection_id=inspection.id,
        image_id=f"IMG-{inspection.inspection_id.split('-')[-1]}-{num:02d}",
        side=side, source="demo", storage_path=rel, file_hash=digest,
        width=pil_image.width, height=pil_image.height, format="JPEG",
        ocr_suitability="good", processing_status="pending",
        captured_at=inspection.inspection_date,
        ground_truth=ground_truth,
        meta={"demo": True},
    )
    q = quality_service.analyse(path)
    img.quality = q.as_dict()
    img.ocr_suitability = q.ocr_suitability
    db.add(img)
    db.commit()
    return img


def _new_inspection(db: Session, *, code_num: int, inspector_username: str, product_name: str,
                    category: str, status: str, step: int, **kwargs) -> models.Inspection:
    inspector = db.query(models.User).filter(models.User.username == inspector_username).first()
    insp = models.Inspection(
        inspection_id=f"LM-2026-{code_num:05d}",
        inspector_id=inspector.id if inspector else 1,
        product_name=product_name,
        product_category=category,
        status=status,
        current_step=step,
        inspection_date=dt.datetime(2026, 9, 4, 10, 15, tzinfo=dt.timezone.utc),
        **kwargs,
    )
    insp.seq = code_num
    db.add(insp)
    db.commit()
    return insp


def _run_scenario(db: Session, insp: models.Inspection, front: LabelSpec, with_consumer: bool) -> None:
    image, regions = build_label(front)
    _save_image(db, insp, "front", image, regions)
    image, regions = build_label(back_standard(with_consumer))
    _save_image(db, insp, "back", image, regions)
    run_ocr(db, insp)
    run_field_matching(db, insp)


def _verify_all(db: Session, insp: models.Inspection, verify_set: set[str] | None = None) -> None:
    fields = db.query(models.ExtractedField).filter(models.ExtractedField.inspection_id == insp.id).all()
    for f in fields:
        if f.status == FIELD_NOT_FOUND:
            continue
        if verify_set is None or f.field_name in verify_set:
            f.verified = True
    db.commit()


def _finalise(db: Session, insp: models.Inspection, username: str, final: str) -> None:
    insp.status = INSP_STATUS_FINALIZED
    insp.final_compliance_status = final or insp.automated_result
    insp.reviewed_by = username
    insp.reviewed_at = insp.inspection_date
    db.commit()
    _make_reports(db, insp)


def _make_reports(db: Session, insp: models.Inspection) -> None:
    folder = settings.storage_dir / "reports" / insp.inspection_id
    folder.mkdir(parents=True, exist_ok=True)
    for idx, (rtype, gen) in enumerate([("pdf", generate_pdf), ("docx", generate_docx)], start=1):
        rel = f"reports/{insp.inspection_id}/v1.0.{rtype}"
        path = settings.storage_dir / rel
        try:
            digest = gen(db, insp, path)
            status, val = "generated", "passed"
        except Exception:  # pragma: no cover
            digest, status, val = "", "failed", "failed"
        db.add(models.Report(
            report_id=f"RPT-{insp.inspection_id.split('-')[-1]}-0{idx}",
            inspection_id=insp.id, report_version="1.0", report_type=rtype,
            template_id="standard_inspection_report", template_version="1.0",
            rule_set_version="current",
            generated_by=insp.inspector.username,
            generated_at=dt.datetime.now(dt.timezone.utc),
            file_reference=rel, file_hash=digest,
            generation_status=status, validation_status=val,
            included_sections=["all"],
        ))
    db.commit()


def _seed_inspections(db: Session) -> None:
    if db.query(models.Inspection).count() > 0:
        return
    ins1 = "LM-INS-00125"
    ins2 = "LM-INS-00131"

    # 125 — draft, nothing beyond details yet
    _new_inspection(db, code_num=125, inspector_username=ins1,
                    product_name="Tata Salt Iodised 1 kg", category="food_grain",
                    status="draft", step=2, retailer_store="FreshMart Supermarket",
                    location="MG Road, Hyderabad", package_type="flexible")

    # 126 — finalised, non-compliant (1 finding) — owned by inspector 2
    i126 = _new_inspection(db, code_num=126, inspector_username=ins2,
                           product_name="Sunpure Refined Sunflower Oil 1 L", category="edible_oil",
                           status=INSP_STATUS_FINALIZED, step=7,
                           retailer_store="Reliance Smart, Banjara Hills", location="Hyderabad",
                           package_type="rigid")
    _run_scenario(db, i126, front_oil(), with_consumer=False)
    run_rule_analysis(db, i126)
    _verify_all(db, i126)
    run_rule_analysis(db, i126)
    _finalise(db, i126, ins2, final=FINAL_NON_COMPLIANT)

    # 127 — pending review, non-compliant (3 findings)
    i127 = _new_inspection(db, code_num=127, inspector_username=ins1,
                           product_name="Crunchy Biscuits 250 g", category="snacks",
                           status=INSP_STATUS_PENDING_REVIEW, step=6,
                           retailer_store="FreshMart Supermarket", location="MG Road, Hyderabad",
                           package_type="flexible")
    _run_scenario(db, i127, front_biscuits(), with_consumer=False)
    run_rule_analysis(db, i127)
    _verify_all(db, i127)
    run_rule_analysis(db, i127)

    # 128 — finalised compliant
    i128 = _new_inspection(db, code_num=128, inspector_username=ins1,
                           product_name="ABC Premium Rice 5 kg", category="food_grain",
                           status=INSP_STATUS_FINALIZED, step=7,
                           retailer_store="More Megastore, Kukatpally", location="Hyderabad",
                           package_type="rigid")
    _run_scenario(db, i128, front_compliant(), with_consumer=True)
    run_rule_analysis(db, i128)
    _verify_all(db, i128)
    run_rule_analysis(db, i128)
    _finalise(db, i128, ins1, final=FINAL_COMPLIANT)

    # 129 — the guided walkthrough inspection (non-compliant, pending review).
    # Carries an online-listing value (4 kg) that conflicts with the package
    # declaration (5 kg) so the cross-source check shows POTENTIAL_NON_COMPLIANCE.
    i129 = _new_inspection(db, code_num=129, inspector_username=ins1,
                           product_name="ABC Premium Rice 5 kg", category="food_grain",
                           status=INSP_STATUS_PENDING_REVIEW, step=6,
                           retailer_store="FreshMart Supermarket", location="MG Road, Hyderabad",
                           package_type="rigid",
                           online_listing={"field": "net_quantity", "value": "4 kg",
                                           "source": "ExampleMart online listing (product page)"})
    _run_scenario(db, i129, front_failing(), with_consumer=False)
    run_rule_analysis(db, i129)
    _verify_all(db, i129, verify_set={"product_name", "net_quantity", "mrp_value",
                                      "manufacturer_name", "manufacturer_address"})
    run_rule_analysis(db, i129)

    # 130 — cross-field conflict demo: front says 500 g, back says 250 g.
    # The cross-field consistency check must flag POTENTIAL_NON_COMPLIANCE.
    i130 = _new_inspection(db, code_num=130, inspector_username=ins1,
                           product_name="ABC Premium Rice (qty conflict demo)", category="food_grain",
                           status=INSP_STATUS_PENDING_REVIEW, step=5,
                           retailer_store="FreshMart Supermarket", location="MG Road, Hyderabad",
                           package_type="flexible")
    image, regions = build_label(front_qty_conflict())
    _save_image(db, i130, "front", image, regions)
    image, regions = build_label(back_qty_conflict())
    _save_image(db, i130, "back", image, regions)
    run_ocr(db, i130)
    run_field_matching(db, i130)
    run_rule_analysis(db, i130)
    _verify_all(db, i130, verify_set={"product_name", "net_quantity", "mrp_value",
                                      "manufacturer_name", "manufacturer_address",
                                      "consumer_care_number"})
    run_rule_analysis(db, i130)


def seed_all(db: Session) -> None:
    _seed_users(db)
    _seed_categories(db)
    _seed_rules(db)
    if settings.SEED_DEMO_DATA:
        _seed_inspections(db)
