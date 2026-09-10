"""Pydantic request/response schemas for API bodies."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    user: dict


class InspectionCreate(BaseModel):
    product_name: str = ""
    brand: str = ""
    product_description: str = ""
    product_category: str = ""
    package_type: str = ""
    retailer_store: str = ""
    location: str = ""
    premises_type: str = ""
    country_of_origin_claimed: str = ""
    inspection_date: Optional[str] = None


class InspectionUpdate(BaseModel):
    product_name: Optional[str] = None
    brand: Optional[str] = None
    product_description: Optional[str] = None
    product_category: Optional[str] = None
    package_type: Optional[str] = None
    retailer_store: Optional[str] = None
    location: Optional[str] = None
    premises_type: Optional[str] = None
    country_of_origin_claimed: Optional[str] = None


class NavigateRequest(BaseModel):
    step: int = Field(ge=1, le=7)


class FieldCorrection(BaseModel):
    value: str
    reason: str = ""


class FieldVerifyRequest(BaseModel):
    field_ids: Optional[list[int]] = None  # None = verify all non-missing fields


class FindingDecision(BaseModel):
    inspector_result: str  # satisfied | not_satisfied | inconclusive
    decision_reason: str = ""
    note: str = ""


class ObservationRequest(BaseModel):
    text: str = ""


class FinalizeRequest(BaseModel):
    final_compliance_status: str  # compliant | non_compliant | inconclusive
    final_remarks: str = ""
    allow_unresolved: bool = False
    unresolved_reason: str = ""


class EvidenceUpdate(BaseModel):
    observation: Optional[str] = None
    relevance: Optional[str] = None
    status: Optional[str] = None
    finding_id: Optional[str] = None


class ReportGenerateRequest(BaseModel):
    report_type: str = "pdf"  # pdf | docx
    sections: Optional[list[str]] = None


class RuleUpsert(BaseModel):
    rule_number: str = ""
    sub_rule: str = ""
    title: str = ""
    type: str = "content"
    category: str = "mandatory_declaration"
    requirement: str = ""
    description: str = ""
    field: Optional[str] = None
    required: bool = True
    applicability: list[str] = ["*"]
    conditions: dict = {}
    validation: dict = {}
    severity: str = "major"
    evidence_required: bool = True
    effective_from: str = "2011-05-30"
    effective_to: Optional[str] = None
    version: int = 1
    source: str = ""
    status: str = "active"


class InspectorCreate(BaseModel):
    username: str
    full_name: str = ""
    department: str = ""
    password: str = "inspector123"
    status: str = "active"


class InspectorUpdate(BaseModel):
    status: Optional[str] = None
    full_name: Optional[str] = None
    department: Optional[str] = None
    role: Optional[str] = None
