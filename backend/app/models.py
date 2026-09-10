"""SQLAlchemy ORM models for the Legal Metrology Inspection Platform.

The schema mirrors the required entities:
users, inspections, images, ocr_results, extracted_fields, rules, rule_results,
findings (violations), font_analyses, placement_analyses, evidence, reports,
audit_logs.

Design notes:
- The automated (rule engine) result is NEVER overwritten by the inspector's
  assessment — the two are stored separately (engine_result vs inspector_result)
  so the audit chain rule -> automated finding -> human verification -> final
  assessment stays intact.
- JSON columns hold structured data (bounding boxes, quality metrics, rule
  conditions/applicability) and are PostgreSQL `jsonb`-compatible; plain JSON is
  used automatically when the prototype runs on SQLite.
"""
from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)

from .utils import COMPLIANT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

JSONType = JSON


def _json_default():
    return dict


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.now(dt.timezone.utc))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=dt.datetime.now(dt.timezone.utc), onupdate=dt.datetime.now(dt.timezone.utc)
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # e.g. ADM-001, LM-INS-00125
    full_name: Mapped[str] = mapped_column(String(160), default="")
    role: Mapped[str] = mapped_column(String(20), default="inspector")  # inspector | admin
    department: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | pending | inactive
    password_hash: Mapped[str] = mapped_column(String(256))
    last_active_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    inspections: Mapped[list["Inspection"]] = relationship(back_populates="inspector")


class ProductCategory(Base):
    """Small lookup so categories are reusable across inspections and rules."""
    __tablename__ = "product_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    imported_only: Mapped[bool] = mapped_column(Boolean, default=False)


class Inspection(Base, TimestampMixin):
    __tablename__ = "inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # LM-2026-00129
    inspector_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Context entered at step 1
    product_name: Mapped[str] = mapped_column(String(240), default="")
    brand: Mapped[str] = mapped_column(String(120), default="")
    product_description: Mapped[str] = mapped_column(String(240), default="")
    product_category: Mapped[str] = mapped_column(String(60), default="")  # ProductCategory.code
    package_type: Mapped[str] = mapped_column(String(60), default="")      # rigid | flexible | curved | carton ...
    retailer_store: Mapped[str] = mapped_column(String(160), default="")
    location: Mapped[str] = mapped_column(String(240), default="")
    premises_type: Mapped[str] = mapped_column(String(120), default="")
    inspection_date: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.now(dt.timezone.utc))
    country_of_origin_claimed: Mapped[str] = mapped_column(String(60), default="")
    # Workflow state
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    current_step: Mapped[int] = mapped_column(Integer, default=1)
    automated_result: Mapped[str | None] = mapped_column(String(32), nullable=True)  # compliant | non_compliant | review_required | inconclusive
    final_compliance_status: Mapped[str | None] = mapped_column(String(32), nullable=True)  # compliant | non_compliant | inconclusive
    final_remarks: Mapped[str] = mapped_column(Text, default="")
    inspector_observation: Mapped[str] = mapped_column(Text, default="")
    rule_set_snapshot: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(64), default="")
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Cross-source comparison: a manually entered online-listing value for one
    # field (e.g. net_quantity) — compared against the package value by the
    # cross-source check, which produces POTENTIAL_NON_COMPLIANCE on mismatch.
    # Shape: {"field": "net_quantity", "value": "4 kg", "source": "<listing URL/name>"}
    online_listing: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    # Numbering for children public ids
    seq: Mapped[int] = mapped_column(Integer, default=0)

    inspector: Mapped["User"] = relationship(back_populates="inspections")
    images: Mapped[list["InspectionImage"]] = relationship(
        back_populates="inspection", cascade="all, delete-orphan", order_by="InspectionImage.id"
    )
    fields: Mapped[list["ExtractedField"]] = relationship(back_populates="inspection", cascade="all, delete-orphan")
    ocr_results: Mapped[list["OcrResult"]] = relationship(
        back_populates="inspection", cascade="all, delete-orphan", order_by="OcrResult.id"
    )
    rule_results: Mapped[list["RuleResult"]] = relationship(back_populates="inspection", cascade="all, delete-orphan")
    findings: Mapped[list["Finding"]] = relationship(back_populates="inspection", cascade="all, delete-orphan")
    reports: Mapped[list["Report"]] = relationship(back_populates="inspection", cascade="all, delete-orphan")


class InspectionImage(Base, TimestampMixin):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    image_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # IMG-00129-01
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id"), index=True)
    side: Mapped[str] = mapped_column(String(24), default="front")  # front|back|side|top|bottom|declaration|additional
    source: Mapped[str] = mapped_column(String(24), default="upload")  # camera | upload | demo
    storage_path: Mapped[str] = mapped_column(String(500), default="")
    enhanced_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_hash: Mapped[str] = mapped_column(String(128), default="")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    format: Mapped[str] = mapped_column(String(12), default="JPEG")
    quality: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # blur/glare/lighting/framing scores + checks
    ocr_suitability: Mapped[str] = mapped_column(String(24), default="pending")  # good | acceptable | poor | pending
    processing_status: Mapped[str] = mapped_column(String(24), default="pending")  # pending|done|failed
    # OCR engine that actually produced this image's regions (paddle|tesseract|demo)
    # and whether the primary engine was replaced (fallback). Persisted per image so
    # the inspector and the report can see which engine read each capture.
    ocr_engine: Mapped[str] = mapped_column(String(24), default="")
    ocr_fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_evidence_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    captured_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Demo ground truth: list of {text, x, y, w, h, conf} used by the demo OCR
    # engine to replay realistic OCR on the generated sample labels.
    ground_truth: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    inspection: Mapped["Inspection"] = relationship(back_populates="images")
    ocr_results: Mapped[list["OcrResult"]] = relationship(
        back_populates="image", cascade="all, delete-orphan", order_by="OcrResult.id"
    )


class OcrResult(Base, TimestampMixin):
    __tablename__ = "ocr_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id"), index=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id"), index=True)
    region_id: Mapped[str] = mapped_column(String(32), default="")  # REGION-07
    text: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    bbox: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # normalized {x,y,width,height} 0..1

    image: Mapped["InspectionImage"] = relationship(back_populates="ocr_results")
    inspection: Mapped["Inspection"] = relationship(back_populates="ocr_results")


class ExtractedField(Base, TimestampMixin):
    __tablename__ = "extracted_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id"), index=True)
    image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id"), nullable=True)
    field_name: Mapped[str] = mapped_column(String(80), index=True)   # canonical field name
    category: Mapped[str] = mapped_column(String(60), default="product")  # product|quantity|price|manufacturer|dates|consumer|origin|other
    value: Mapped[str] = mapped_column(Text, default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(24), default="NOT_DETECTED")  # DETECTED|UNCERTAIN|NOT_DETECTED
    reason: Mapped[str] = mapped_column(Text, default="")  # populated when status is UNCERTAIN or NOT_DETECTED
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[str] = mapped_column(String(64), default="")
    source: Mapped[str] = mapped_column(String(24), default="ocr")  # ocr | inspector | demo
    original_value: Mapped[str] = mapped_column(Text, default="")   # preserved when corrected
    correction_reason: Mapped[str] = mapped_column(String(120), default="")
    bbox: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    region_id: Mapped[str] = mapped_column(String(32), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)

    inspection: Mapped["Inspection"] = relationship(back_populates="fields")


class Rule(Base, TimestampMixin):
    """One row per rule version — effective_from/effective_to drive date-aware selection."""
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(48), unique=True, index=True)  # PC-7-1
    rule_number: Mapped[str] = mapped_column(String(24), default="")   # e.g. "Rule 6"
    sub_rule: Mapped[str] = mapped_column(String(24), default="")      # e.g. "6(1)(c)"
    title: Mapped[str] = mapped_column(String(200), default="")
    type: Mapped[str] = mapped_column(String(24), default="content")   # content|font|placement|spacing|format
    category: Mapped[str] = mapped_column(String(40), default="mandatory_declaration")
    requirement: Mapped[str] = mapped_column(Text, default="")         # human-readable requirement text
    description: Mapped[str] = mapped_column(Text, default="")
    field: Mapped[str | None] = mapped_column(String(80), nullable=True)  # extracted field this validates (if any)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    applicability: Mapped[list | None] = mapped_column(JSONType, nullable=True)  # product categories
    conditions: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    validation: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # deterministic check config
    severity: Mapped[str] = mapped_column(String(20), default="major")  # critical|major|minor
    evidence_required: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_from: Mapped[dt.date] = mapped_column(Date, index=True)
    effective_to: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active")  # register lifecycle: active|historical|future|omitted (+ legacy draft|superseded)
    # Evaluation scope assigned by the register import (Part A classification):
    #   image_checkable -> evaluated by the engine per inspection
    #   manual_review   -> always produces MANUAL_REVIEW (never auto-pass/skip)
    #   reference       -> legal/administrative record, stored for citation only
    #   deferred        -> image-checkable but needs human mapping review (excluded until resolved)
    scope: Mapped[str] = mapped_column(String(20), default="image_checkable", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class RuleResult(Base, TimestampMixin):
    """One row per evaluated rule. `result` holds exactly one of the four
    compliance states (enforced by CHECK constraint):
    COMPLIANT | NON_COMPLIANT | MANUAL_REVIEW | POTENTIAL_NON_COMPLIANCE.
    The structured observed/expected/evidence/reason columns carry the exact
    compliance_result shape consumed by the result page and the PDF report.
    """
    __tablename__ = "rule_results"
    __table_args__ = (
        # Database-level constraint: only the four compliance states may be stored.
        CheckConstraint(
            "result IN ('COMPLIANT', 'NON_COMPLIANT', 'MANUAL_REVIEW', 'POTENTIAL_NON_COMPLIANCE')",
            name="ck_rule_results_result_four_states",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id"), index=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id"), index=True)
    rule_number: Mapped[str] = mapped_column(String(24), default="")
    sub_rule: Mapped[str] = mapped_column(String(24), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str] = mapped_column(String(40), default="")
    type: Mapped[str] = mapped_column(String(24), default="content")
    requirement: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(String(24), default=COMPLIANT)
    # structured compliance_result shape (Section 5 of the build spec)
    observed: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    expected: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    input_value: Mapped[str] = mapped_column(Text, default="")
    expected_value: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    severity: Mapped[str] = mapped_column(String(20), default="major")
    field: Mapped[str | None] = mapped_column(String(80), nullable=True)
    evidence_required: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    inspection: Mapped["Inspection"] = relationship(back_populates="rule_results")
    rule: Mapped["Rule"] = relationship()


class Finding(Base, TimestampMixin):
    """Automated finding for a failed / review-required rule. Inspector status kept separate."""
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[str] = mapped_column(String(32), index=True)  # F-001 (unique within inspection)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id"), index=True)
    rule_result_id: Mapped[int | None] = mapped_column(ForeignKey("rule_results.id"), nullable=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id"), nullable=True)
    finding_type: Mapped[str] = mapped_column(String(40), default="mandatory_declaration")
    requirement: Mapped[str] = mapped_column(Text, default="")
    detected_condition: Mapped[str] = mapped_column(Text, default="")
    expected_condition: Mapped[str] = mapped_column(Text, default="")
    engine_result: Mapped[str] = mapped_column(String(20), default="review")  # fail | review
    severity: Mapped[str] = mapped_column(String(20), default="major")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_image_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ocr_region_id: Mapped[str] = mapped_column(String(32), default="")
    source_field: Mapped[str] = mapped_column(String(80), default="")
    rule_number: Mapped[str] = mapped_column(String(24), default="")
    sub_rule: Mapped[str] = mapped_column(String(24), default="")
    # Inspector review state (never touches engine_result above)
    inspector_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|confirmed|rejected|modified|inconclusive
    inspector_result: Mapped[str | None] = mapped_column(String(24), nullable=True)  # satisfied|not_satisfied|inconclusive
    inspector_note: Mapped[str] = mapped_column(Text, default="")
    decision_reason: Mapped[str] = mapped_column(String(120), default="")
    reviewed_by: Mapped[str] = mapped_column(String(64), default="")
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    inspection: Mapped["Inspection"] = relationship(back_populates="findings")
    rule_result: Mapped["RuleResult"] = relationship()


class FontAnalysis(Base, TimestampMixin):
    __tablename__ = "font_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id"), index=True)
    finding_id: Mapped[int | None] = mapped_column(ForeignKey("findings.id"), nullable=True)
    image_id: Mapped[str] = mapped_column(String(32), default="")
    region_id: Mapped[str] = mapped_column(String(32), default="")
    field: Mapped[str] = mapped_column(String(80), default="")
    detected_text: Mapped[str] = mapped_column(Text, default="")
    readability_score: Mapped[float] = mapped_column(Float, default=0.0)
    readability: Mapped[str] = mapped_column(String(20), default="good")  # good|review|poor
    factors: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    # Relative font estimate (explicitly not claimed as mm precision without calibration)
    font_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)  # height/PDP-height ratio
    measurement_unit: Mapped[str] = mapped_column(String(20), default="ratio")
    measurement_method: Mapped[str] = mapped_column(Text, default="image-based relative estimate")
    calibration_available: Mapped[bool] = mapped_column(Boolean, default=False)
    measurement_confidence: Mapped[str] = mapped_column(String(20), default="medium")  # high|medium|low
    applicable_rule: Mapped[str] = mapped_column(String(48), default="")
    required_condition: Mapped[str] = mapped_column(Text, default="")
    automated_result: Mapped[str] = mapped_column(String(20), default="review")  # pass|review|potential_fail
    manual_review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    inspector_result: Mapped[str | None] = mapped_column(String(24), nullable=True)  # satisfied|not_satisfied|inconclusive
    inspector_note: Mapped[str] = mapped_column(Text, default="")


class PlacementAnalysis(Base, TimestampMixin):
    __tablename__ = "placement_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id"), index=True)
    finding_id: Mapped[int | None] = mapped_column(ForeignKey("findings.id"), nullable=True)
    image_id: Mapped[str] = mapped_column(String(32), default="")
    region_id: Mapped[str] = mapped_column(String(32), default="")
    field: Mapped[str] = mapped_column(String(80), default="")
    detected_location: Mapped[str] = mapped_column(String(40), default="")  # front|back|side panel
    detected_panel: Mapped[str] = mapped_column(String(40), default="")
    position_confidence: Mapped[str] = mapped_column(String(20), default="medium")  # high|medium|low
    format_observation: Mapped[str] = mapped_column(Text, default="")
    format_confidence: Mapped[str] = mapped_column(String(20), default="medium")
    applicable_rule: Mapped[str] = mapped_column(String(48), default="")
    requirement: Mapped[str] = mapped_column(Text, default="")
    expected_condition: Mapped[str] = mapped_column(Text, default="")
    detected_condition: Mapped[str] = mapped_column(Text, default="")
    automated_result: Mapped[str] = mapped_column(String(20), default="review")  # pass|potential_issue|review
    evidence_sufficient: Mapped[bool] = mapped_column(Boolean, default=True)
    manual_review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    inspector_result: Mapped[str | None] = mapped_column(String(24), nullable=True)
    inspector_note: Mapped[str] = mapped_column(Text, default="")


class Evidence(Base, TimestampMixin):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(32), index=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(32), default="source_image")  # source_image|evidence_region|ocr_region|font_evidence|placement_evidence|inspector_photo|additional
    source_image_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    derived_from_evidence_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    region_id: Mapped[str] = mapped_column(String(32), default="")
    finding_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rule_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    field_name: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="available")  # available|linked|review|not_used|insufficient
    relevance: Mapped[str] = mapped_column(String(20), default="relevant")  # relevant|not_relevant|inconclusive
    observation: Mapped[str] = mapped_column(Text, default="")
    file_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    integrity_hash: Mapped[str] = mapped_column(String(128), default="")
    captured_by: Mapped[str] = mapped_column(String(64), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # RPT-00129-01
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id"), index=True)
    report_version: Mapped[str] = mapped_column(String(12), default="1.0")
    report_type: Mapped[str] = mapped_column(String(12), default="pdf")  # pdf | docx
    template_id: Mapped[str] = mapped_column(String(48), default="standard_inspection_report")
    template_version: Mapped[str] = mapped_column(String(12), default="1.0")
    rule_set_version: Mapped[str] = mapped_column(String(64), default="")
    generated_by: Mapped[str] = mapped_column(String(64), default="")
    generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    file_reference: Mapped[str] = mapped_column(String(500), default="")
    file_hash: Mapped[str] = mapped_column(String(128), default="")
    generation_status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|generating|generated|failed
    validation_status: Mapped[str] = mapped_column(String(20), default="pending")  # passed|failed
    included_sections: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    evidence_selection: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    inspection: Mapped["Inspection"] = relationship(back_populates="reports")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int | None] = mapped_column(ForeignKey("inspections.id"), nullable=True, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(64), default="")  # username snapshot
    actor_role: Mapped[str] = mapped_column(String(20), default="")
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.now(dt.timezone.utc), index=True)
