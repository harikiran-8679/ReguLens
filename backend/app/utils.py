"""Shared helpers: status constants, public ID generation, date formatting."""
from __future__ import annotations

import datetime as dt
import re

# ---------------------------------------------------------------------------
# Enum-like string constants (kept as plain strings for Postgres + SQLite compat)
# ---------------------------------------------------------------------------

# users
ROLE_INSPECTOR = "inspector"
ROLE_ADMIN = "admin"
USER_STATUS_ACTIVE = "active"
USER_STATUS_PENDING = "pending"
USER_STATUS_INACTIVE = "inactive"

# inspections (workflow states — distinct from the compliance status vocabulary)
INSP_STATUS_DRAFT = "draft"
INSP_STATUS_UNDER_ANALYSIS = "under_analysis"
INSP_STATUS_ANALYSIS_COMPLETE = "analysis_complete"
INSP_STATUS_PENDING_REVIEW = "pending_review"
INSP_STATUS_FINALIZED = "finalized"

# ---------------------------------------------------------------------------
# THE compliance status vocabulary — exactly four states, used everywhere a
# compliance verdict is stored or displayed (rule_results.result, compliance
# result API, frontend pages, PDF report). No PASS/FAIL/VIOLATION variants.
# ---------------------------------------------------------------------------
COMPLIANT = "COMPLIANT"                       # rule requirement satisfied
NON_COMPLIANT = "NON_COMPLIANT"               # single rule failed w/ sufficient confidence + coverage
MANUAL_REVIEW = "MANUAL_REVIEW"               # low confidence / poor quality / borderline — never silently decided
POTENTIAL_NON_COMPLIANCE = "POTENTIAL_NON_COMPLIANCE"  # reserved for cross-field / cross-source mismatches

# Inspection-level automated result uses the same four states; it is left NULL
# when no applicable rule could be evaluated (no verdict produced).
AUTO_COMPLIANT = COMPLIANT
AUTO_NON_COMPLIANT = NON_COMPLIANT
AUTO_REVIEW_REQUIRED = MANUAL_REVIEW
AUTO_INCONCLUSIVE = None          # no verdict when nothing evaluable

# Final inspector assessment uses the same four states.
FINAL_COMPLIANT = COMPLIANT
FINAL_NON_COMPLIANT = NON_COMPLIANT
FINAL_INCONCLUSIVE = MANUAL_REVIEW

# images
IMG_SIDES = ["front", "back", "side", "top", "bottom", "declaration", "additional"]
IMG_STATUS_PENDING = "pending"
IMG_STATUS_DONE = "done"

# extracted fields status — DETECTED / NOT_DETECTED / UNCERTAIN only
# (a field corrected by the inspector keeps status DETECTED; the correction is
# preserved via source="inspector" + original_value + correction_reason).
FIELD_DETECTED = "DETECTED"
FIELD_UNCERTAIN = "UNCERTAIN"
FIELD_NOT_FOUND = "NOT_DETECTED"
FIELD_CORRECTED = FIELD_DETECTED

# rule results — exactly the four compliance states (NOT_APPLICABLE is used only
# internally for reporting and is never persisted as a rule result row).
RES_PASS = COMPLIANT
RES_FAIL = NON_COMPLIANT
RES_NON_COMPLIANT = NON_COMPLIANT
RES_MANUAL_REVIEW = MANUAL_REVIEW
RES_POTENTIAL_NON_COMPLIANCE = POTENTIAL_NON_COMPLIANCE
RES_NOT_APPLICABLE = "NOT_APPLICABLE"
RES_NOT_EVALUATED = "NOT_EVALUATED"

SEVERITY_CRITICAL = "critical"
SEVERITY_MAJOR = "major"
SEVERITY_MINOR = "minor"

# findings
ENGINE_FAIL = "fail"
ENGINE_REVIEW = "review"
INSP_STATUSES = ("pending", "confirmed", "rejected", "modified", "inconclusive")

# evidence
EVIDENCE_STATUSES = ("available", "linked", "review", "not_used", "insufficient")

# steps (1..7) used by the frontend stepper
STEP_DETAILS = 1
STEP_CAPTURE = 2
STEP_OCR = 3
STEP_RULES = 4
STEP_RESULT = 5
STEP_FINDINGS = 6
STEP_REVIEW = 7


def next_sequence(db, model, column) -> int:
    """Smallest free per-entity numeric sequence (safe under concurrency for a demo)."""
    from sqlalchemy import func, select

    max_val = db.execute(select(func.max(column)).select_from(model)).scalar()
    return (max_val or 0) + 1


def pad(n: int, width: int = 5) -> str:
    return str(n).zfill(width)


def human_date(d: dt.date | dt.datetime | None) -> str:
    if d is None:
        return "—"
    if isinstance(d, dt.datetime):
        d = d.date()
    return d.strftime("%d %b %Y")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


_MONTHS = [
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
]


def parse_month_year(text: str) -> dt.date | None:
    """Parse 'AUG 2026' / 'Aug-2026' / '08/2026' style month-year strings."""
    t = text.strip().upper()
    m = re.search(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[.\-/\s]*(\d{4})", t)
    if m:
        return dt.date(int(m.group(2)), _MONTHS.index(m.group(1)) + 1, 1)
    m = re.search(r"(\d{1,2})[./\-](\d{4})", t)
    if m:
        mon = int(m.group(1))
        if 1 <= mon <= 12:
            return dt.date(int(m.group(2)), mon, 1)
    return None


def parse_amount(text: str) -> float | None:
    """Extract a number from rupee/price text like 'MRP ₹450', 'Rs. 49.50'."""
    cleaned = text.replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    return float(m.group(1)) if m else None


def quantity_to_grams(value: str) -> float | None:
    """Normalise a quantity string to grams for comparisons. Returns None when unparseable."""
    cleaned = value.strip().lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(g|kg|ml|l|mg|cl|cc|gm|kgs|kilo|litre|liter)", cleaned)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2)
    if unit in ("g", "gm"):
        return num
    if unit == "kg":
        return num * 1000
    if unit in ("ml", "cc"):
        return num  # treat ml ≈ g for threshold purposes
    if unit == "l":
        return num * 1000
    if unit == "cl":
        return num * 10
    if unit == "mg":
        return num / 1000
    return None
