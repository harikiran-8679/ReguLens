"""Deterministic, versioned, date-aware rule engine.

The engine is the ONLY place where compliance decisions are made — the LLM field
matcher never reaches this module, and the engine only ever receives already
normalized product facts (ExtractedField rows), never raw OCR text.

It:

1. selects rules whose effective window contains the inspection date,
2. filters by product category / applicability / conditions,
3. evaluates each rule against the inspector-verified structured data,
4. expands font / placement / spacing rules into per-declaration analyses,
5. runs the cross-field / cross-source consistency checks,
6. persists rule_results (exactly one of the four compliance states —
   COMPLIANT / NON_COMPLIANT / MANUAL_REVIEW / POTENTIAL_NON_COMPLIANCE —
   enforced by a DB CHECK constraint) + findings + evidence references, and
7. aggregates the four-state compliance outcome.

The four states are never collapsed:
  * detected with high confidence          -> COMPLIANT when the rule is met
  * uncertain / low OCR confidence         -> MANUAL_REVIEW (never a silent verdict)
  * not detected after adequate coverage   -> NON_COMPLIANT (potential missing)
  * cross-field / cross-source mismatch    -> POTENTIAL_NON_COMPLIANCE
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field as dc_field

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from ..utils import (
    AUTO_COMPLIANT,
    AUTO_INCONCLUSIVE,
    AUTO_NON_COMPLIANT,
    AUTO_REVIEW_REQUIRED,
    COMPLIANT,
    FIELD_NOT_FOUND,
    FIELD_UNCERTAIN,
    INSP_STATUS_ANALYSIS_COMPLETE,
    INSP_STATUS_DRAFT,
    INSP_STATUS_UNDER_ANALYSIS,
    MANUAL_REVIEW,
    NON_COMPLIANT,
    POTENTIAL_NON_COMPLIANCE,
    RES_MANUAL_REVIEW,
    RES_NON_COMPLIANT,
    RES_NOT_APPLICABLE,
    RES_PASS,
    RES_POTENTIAL_NON_COMPLIANCE,
    parse_month_year,
    quantity_to_grams,
)
from .normalizer import normalize_amount, normalize_quantity
from .matcher import HIGH_CONF

RULE_BASE_TEXT = "Legal Metrology (Packaged Commodities) Rules, 2011"
ENGINE_VERSION = "RE-2.0"
AMENDMENT_MAP = [
    {"name": "Legal Metrology (Packaged Commodities) (Amendment) Rules, 2017", "effective_from": dt.date(2018, 1, 1)},
    {"name": "Legal Metrology (Packaged Commodities) (Amendment) Rules, 2022", "effective_from": dt.date(2022, 1, 1)},
]

# Fields whose declared value may be compared across panels / against a listing.
_CROSS_FIELDS = ("net_quantity", "mrp_value")


@dataclass
class EvalContext:
    inspection: models.Inspection
    field_map: dict[str, list[models.ExtractedField]]
    sides: list[str]
    coverage_adequate: bool
    coverage_note: str
    imported: bool
    quality_ok: bool


@dataclass
class ResultRow:
    rule_id: int
    rule_number: str
    sub_rule: str
    title: str
    category: str
    type: str
    requirement: str
    result: str
    input_value: str
    expected_value: str
    note: str
    confidence: float
    severity: str
    field: str | None = None
    evidence_required: bool = True
    sort: int = 0
    analyses: list[dict] = dc_field(default_factory=list)
    reason_code: str = ""
    observed: dict | None = None
    expected: dict | None = None
    evidence: dict | None = None
    reason: str = ""


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------
def _best_row(ctx: EvalContext, name: str) -> models.ExtractedField | None:
    rows = ctx.field_map.get(name) or []
    return max(rows, key=lambda r: r.confidence) if rows else None


def _state(row: models.ExtractedField | None) -> tuple[str, float]:
    """Return (present | uncertain | absent, confidence) from a product fact."""
    if row is None or row.status == FIELD_NOT_FOUND:
        return "absent", 0.0
    if row.status in ("DETECTED", "CORRECTED"):
        if row.verified or row.confidence >= HIGH_CONF or row.source == "inspector":
            return "present", row.confidence
        return "uncertain", row.confidence
    if row.status == FIELD_UNCERTAIN:
        if row.verified:
            return "present", row.confidence
        return "uncertain", row.confidence
    return "present", row.confidence


def _image_for(ctx: EvalContext, row: models.ExtractedField | None) -> models.InspectionImage | None:
    if row is None or row.image_id is None:
        return None
    for i in ctx.inspection.images:
        if i.id == row.image_id:
            return i
    return None


def _evidence_for_row(ctx: EvalContext, row: models.ExtractedField | None) -> dict:
    """Evidence shape: {image_id, bbox} — bbox in pixel space [x0, y0, x1, y1]."""
    if row is None:
        return {"image_id": None, "bbox": None}
    img = _image_for(ctx, row)
    bbox = row.bbox or {}
    px = None
    if img is not None and bbox:
        x = float(bbox.get("x", 0))
        y = float(bbox.get("y", 0))
        w = float(bbox.get("width", 0))
        h = float(bbox.get("height", 0))
        px = [round(x * img.width), round(y * img.height),
              round((x + w) * img.width), round((y + h) * img.height)]
    return {"image_id": img.image_id if img else None, "bbox": px}


def _observed_value(row: models.ExtractedField | None) -> dict:
    """Structured `observed` for single-value results (numeric value + unit/currency
    where the field carries one)."""
    if row is None or not row.value:
        return {"status": "NOT_DETECTED"}
    if row.field_name == "net_quantity":
        hit = normalize_quantity(row.value) or normalize_quantity(row.raw_text or "")
        if hit:
            return {"value": hit["value"], "unit": hit["unit"]}
    if row.field_name == "mrp_value":
        hit = normalize_amount(row.value) or normalize_amount(row.raw_text or "")
        if hit:
            return {"value": hit["value"], "currency": hit["currency"]}
    if row.field_name == "date_of_packing":
        return {"value": row.value}
    return {"value": row.value}


def build_context(db: Session, inspection: models.Inspection) -> EvalContext:
    fields = db.query(models.ExtractedField).filter(
        models.ExtractedField.inspection_id == inspection.id).all()
    fmap: dict[str, list[models.ExtractedField]] = {}
    for f in fields:
        fmap.setdefault(f.field_name, []).append(f)

    sides = [i.side for i in inspection.images]
    has_front = "front" in sides
    has_back_or_side = bool({"back", "side", "declaration"} & set(sides))
    coverage_adequate = bool(inspection.images) and has_front and has_back_or_side
    coverage_note = (
        "Front and rear/side panels captured — adequate for presence assessment."
        if coverage_adequate
        else "Coverage insufficient: missing rear/side panels. Missing declarations stay flagged for review."
    )
    quality_ok = any(
        (i.quality or {}).get("ocr_suitability", "good") in ("good", "acceptable") for i in inspection.images
    )

    claimed = (inspection.country_of_origin_claimed or "").strip().lower()
    origin_row = _best_row(EvalContext(inspection, fmap, sides, coverage_adequate, coverage_note,
                                       claimed not in ("", "india"), quality_ok), "country_of_origin")
    origin_value = (origin_row.value or "").strip().lower() if origin_row else ""
    imported = claimed not in ("", "india") and origin_value not in ("", "india")

    return EvalContext(inspection, fmap, sides, coverage_adequate, coverage_note,
                       imported, quality_ok)


def _claimed_shelf_life_months(ctx: EvalContext) -> int | None:
    row = _best_row(ctx, "best_before")
    if not row or not row.value:
        return None
    m = re.search(r"(\d+)\s*(?:months?|mon)", row.value.lower())
    if m:
        return int(m.group(1))
    if re.search(r"\d{1,2}[/.-]\d{4}", row.value):
        return None
    return None


# ---------------------------------------------------------------------------
# Measurement-basis helper (Bug 2: mutually-exclusive unit sub-rules)
# ---------------------------------------------------------------------------
_VOLUME_CATS = frozenset({
    "beverages", "beverage", "drinks", "liquid", "edible_oil", "oil", "fuel",
    "cleaning_liquid", "disinfectant", "liquid_soap", "dairy_liquid", "juice",
})
_MASS_CATS = frozenset({
    "food_grain", "grain", "rice", "wheat", "flour", "pulses", "spices", "salt",
    "sugar", "snacks", "biscuits", "confectionery", "processed_food", "dairy",
    "cheese", "butter", "margarine", "cosmetics", "pharma", "chemical",
    "detergent_powder", "powder", "fertilizer",
})
_LENGTH_CATS = frozenset({"textile", "fabric", "cloth", "rope", "wire", "cable", "thread"})
_AREA_CATS = frozenset({"carpet", "flooring", "tile", "sheet_material"})
_NUMBER_CATS = frozenset({"counted_goods", "pharmaceutical_unit", "tablets", "capsules",
                          "electronics_units", "batteries"})


def _measurement_basis(ctx: EvalContext) -> str | None:
    """Return 'volume', 'mass', 'length', 'area', or 'number' based on the
    product category, or None when the category is unknown/mixed.

    This is used to exclude mutually-exclusive unit sub-rules (Rule 12(2) and
    Rule 13(2/3)) that cannot apply to the product's actual measurement basis.
    """
    cat = (ctx.inspection.product_category or "").lower().strip()
    # Also check the extracted net_quantity field for unit hints
    q_row = _best_row(ctx, "net_quantity")
    q_unit: str | None = None
    if q_row and q_row.value:
        from .normalizer import normalize_quantity
        hit = normalize_quantity(q_row.value) or normalize_quantity(q_row.raw_text or "")
        if hit:
            q_unit = hit["unit"]
    # Unit-based detection takes precedence (most precise signal)
    if q_unit in ("ml", "l", "cl"):
        return "volume"
    if q_unit in ("g", "kg", "mg"):
        return "mass"
    if q_unit in ("m", "cm", "mm"):
        return "length"
    if q_unit in ("m2", "cm2", "mm2"):
        return "area"
    if q_unit in ("pcs", "no", "nos", "pieces", "number"):
        return "number"
    # Category-based detection
    for vol_cat in _VOLUME_CATS:
        if vol_cat in cat:
            return "volume"
    for mass_cat in _MASS_CATS:
        if mass_cat in cat:
            return "mass"
    for len_cat in _LENGTH_CATS:
        if len_cat in cat:
            return "length"
    for area_cat in _AREA_CATS:
        if area_cat in cat:
            return "area"
    for num_cat in _NUMBER_CATS:
        if num_cat in cat:
            return "number"
    return None  # unknown — allow all sub-rules through (conservative)


def applicable(ctx: EvalContext, rule: models.Rule) -> tuple[bool, str]:
    applicability = rule.applicability
    if applicability and "*" not in applicability:
        if ctx.inspection.product_category not in applicability:
            return False, "Product/package category does not satisfy the rule's applicability condition."
    cond = rule.conditions or {}
    if cond.get("imported") and not ctx.imported:
        return False, "Rule applies to imported commodities only — domestic product."
    if cond.get("domestic_only") and ctx.imported:
        return False, "Rule applies to domestic commodities only."
    if cond.get("min_grams"):
        q_row = _best_row(ctx, "net_quantity")
        if q_row and q_row.value:
            grams = quantity_to_grams(q_row.value)
            if grams is not None and grams < float(cond["min_grams"]):
                return False, f"Exempt: net quantity below the {cond['min_grams']} g exemption threshold."
    if cond.get("shelf_life_months_le"):
        months = _claimed_shelf_life_months(ctx)
        if months is None:
            return False, "Not applicable: no shelf-life claim to evaluate."
        if months > int(cond["shelf_life_months_le"]):
            return False, f"Shelf-life claim ({months} months) exceeds the {cond['shelf_life_months_le']}-month threshold."
    # Medical device packages — rule only applies when the product category indicates a
    # medical device.  If not, the rule is silently skipped; it never produces a false finding.
    if cond.get("medical_device"):
        cat = (ctx.inspection.product_category or "").lower()
        if "medical" not in cat and "device" not in cat:
            return False, "Rule applies to medical device packages only — category does not match."
    # Electronic product packages — rule only applies to electronic / electrical products.
    if cond.get("electronic_product"):
        cat = (ctx.inspection.product_category or "").lower()
        if "electronic" not in cat and "electrical" not in cat:
            return False, "Rule applies to electronic product packages only — category does not match."
    # Alcoholic beverage packages
    if cond.get("alcoholic_beverage"):
        cat = (ctx.inspection.product_category or "").lower()
        if "alcohol" not in cat and "beverage" not in cat and "liquor" not in cat:
            return False, "Rule applies to alcoholic beverage packages only — category does not match."
    # Bug 3 fix: e-commerce-only rules (6(10), 6(10A)) govern online marketplace listings,
    # not physical package inspections. No physical inspection will ever be an e-commerce channel.
    if cond.get("ecommerce_only"):
        return False, ("Rule 6(10)/6(10A) governs online marketplace listing requirements — "
                       "not applicable to physical package inspections.")
    # Bug 2 fix: mutually-exclusive measurement-basis sub-rules (12(2), 13(2), 13(3))
    # Only the sub-rule matching the product's actual measurement basis is applicable.
    required_basis = cond.get("measurement_basis")
    if required_basis:
        product_basis = _measurement_basis(ctx)
        if product_basis is not None and product_basis != required_basis:
            return False, (
                f"Rule applies to {required_basis}-measured products only; "
                f"this product appears to be {product_basis}-based "
                f"(category: {ctx.inspection.product_category or 'unset'})."
            )
    # Wholesale-only rules (Bug 5 fix: handled via scope=reference in DB)
    if cond.get("wholesale_only"):
        pkg = (ctx.inspection.package_type or "").lower()
        if "wholesale" not in pkg and pkg != "":
            return False, "Rule 24 applies to wholesale packages only — this inspection is retail or package type unspecified."
    return True, ""


# Scopes that enter the per-inspection evaluation loop. Reference records are
# stored for citation (Rules & Standards page) but never selected here; deferred
# records await human mapping review; omitted register entries are gone from law.
_EVAL_SCOPES = ("image_checkable", "manual_review")


def select_rules(db: Session, inspection: models.Inspection) -> list[models.Rule]:
    """Select rules whose effective window contains the inspection date AND that
    carry an evaluation scope (image_checkable / manual_review).

    Selection is purely date-driven: rows superseded in a *later* window must
    still apply to inspections performed while they were in force, so only
    'draft' rows (never yet in force) and register rows dated after the
    inspection (status 'future') are excluded by the effective window itself.
    Reference-only ('reference') and needs-human-review ('deferred') records are
    stored for the Rules & Standards citation page but excluded from the
    evaluation loop.
    """
    date = inspection.inspection_date.date() if isinstance(inspection.inspection_date, dt.datetime) else inspection.inspection_date
    return (
        db.query(models.Rule)
        .filter(
            models.Rule.status != "draft",
            models.Rule.status != "omitted",
            models.Rule.scope.in_(_EVAL_SCOPES),
            models.Rule.effective_from <= date,
            or_(models.Rule.effective_to.is_(None), models.Rule.effective_to > date),
        )
        .order_by(models.Rule.sort_order, models.Rule.id)
        .all()
    )


def count_eval_scopes(db: Session, inspection: models.Inspection) -> dict:
    """Partition every rule row for an inspection by what the engine will do with
    it, so the UI can show *why* a rule produced no result.

    Returns {"selected": n, "not_applicable": n, "reference": n, "deferred": n,
    "out_of_window": n} for the inspection date / product category."""
    date = inspection.inspection_date.date() if isinstance(inspection.inspection_date, dt.datetime) else inspection.inspection_date
    all_rules = db.query(models.Rule).order_by(models.Rule.sort_order, models.Rule.id).all()
    out = {"reference": 0, "deferred": 0, "out_of_window": 0, "not_applicable": 0}
    for r in all_rules:
        if r.scope == "reference":
            out["reference"] += 1
            continue
        if r.scope == "deferred":
            out["deferred"] += 1
            continue
        if r.status == "omitted" or not (r.effective_from <= date and (r.effective_to is None or r.effective_to > date)):
            out["out_of_window"] += 1
            continue
        applicability = r.applicability or []
        if applicability and "*" not in applicability and "all" not in applicability \
                and inspection.product_category not in applicability:
            out["not_applicable"] += 1
    return out


# ---------------------------------------------------------------------------
# Validators (single-row results, four-state)
# ---------------------------------------------------------------------------
def _mk(rule: models.Rule, result: str, input_value: str, expected: str, note: str,
        conf: float, field: str | None = None, analyses: list[dict] | None = None,
        sort: int = 0, observed: dict | None = None, expected_obj: dict | None = None,
        evidence: dict | None = None, reason: str = "") -> ResultRow:
    return ResultRow(
        rule_id=rule.id, rule_number=rule.rule_number, sub_rule=rule.sub_rule,
        title=rule.title, category=rule.category, type=rule.type,
        requirement=rule.requirement, result=result, input_value=input_value,
        expected_value=expected, note=note, confidence=round(conf, 4),
        severity=rule.severity, field=field, evidence_required=rule.evidence_required,
        sort=sort, analyses=analyses or [], observed=observed, expected=expected_obj,
        evidence=evidence, reason=reason,
    )


def _check_present(ctx: EvalContext, rule: models.Rule, field_name: str) -> ResultRow:
    row = _best_row(ctx, field_name)
    state, conf = _state(row)
    expected = {"required": True}
    if state == "present":
        suffix = " (inspector-verified)" if row and row.verified else ""
        return _mk(rule, RES_PASS, row.value if row and row.value else "Detected",
                   rule.requirement, f"Declaration extracted{suffix}.", conf, field=field_name,
                   observed=_observed_value(row), expected_obj=expected,
                   evidence=_evidence_for_row(ctx, row))
    if state == "uncertain":
        row_val = (row.value if row else None) or "Possibly present"
        row_reason = (row.reason if row else None) or "verify against the image."
        return _mk(rule, RES_MANUAL_REVIEW, row_val, rule.requirement,
                   f"Possible match with low OCR confidence ({conf:.0%}) — inspector verification required "
                   "before a pass/fail decision.", conf, field=field_name,
                   observed=_observed_value(row), expected_obj=expected,
                   evidence=_evidence_for_row(ctx, row),
                   reason=f"Low OCR confidence ({conf:.0%}); {row_reason}")
    if not ctx.coverage_adequate:
        return _mk(rule, RES_MANUAL_REVIEW, "Not detected", rule.requirement,
                   "Not identified yet, but panel coverage is insufficient. Capture the missing side(s) "
                   "before treating it as absent.", 0.0, field=field_name,
                   observed={"status": "NOT_DETECTED"}, expected_obj=expected,
                   reason="Panel coverage insufficient — the declaration may exist on an uncaptured panel.")
    return _mk(rule, NON_COMPLIANT, "Not detected", rule.requirement,
               "Not identified in the available verified package images after adequate coverage.",
               0.0, field=field_name,
               observed={"status": "NOT_DETECTED"}, expected_obj=expected,
               evidence=_evidence_for_row(ctx, row),
               reason="Not identified across the captured panels after adequate coverage.")


def _check_any_present(ctx: EvalContext, rule: models.Rule, fields: list[str]) -> ResultRow:
    if not fields:
        # No fields bound — cannot evaluate; return MANUAL_REVIEW
        return _mk(rule, RES_MANUAL_REVIEW, "No field targets", rule.requirement,
                   "No extractable field tokens are bound for this rule — "
                   "inspector must verify from the physical package.", 0.0,
                   observed={"engine_action": "no_field_targets"},
                   expected_obj={"required": True},
                   reason="Rule has no engine-bindable field tokens; manual verification required.")
    found = uncertain_row = None
    for fname in fields:
        row = _best_row(ctx, fname)
        state, conf = _state(row)
        if state == "present" and row and (found is None or conf > found.confidence):
            found = row
        elif state == "uncertain" and row and (uncertain_row is None or conf > uncertain_row.confidence):
            uncertain_row = row
    expected = {"required": True}
    fallback_field = fields[0] if fields else (rule.field or "")
    if found:
        return _mk(rule, RES_PASS, found.value or "Detected", rule.requirement,
                   "Required declaration identified.", found.confidence, field=found.field_name,
                   observed=_observed_value(found), expected_obj=expected,
                   evidence=_evidence_for_row(ctx, found))
    if uncertain_row:
        return _mk(rule, RES_MANUAL_REVIEW, uncertain_row.value or "Possibly present", rule.requirement,
                   "Possible match with low confidence — inspector verification required.",
                   uncertain_row.confidence, field=uncertain_row.field_name,
                   observed=_observed_value(uncertain_row), expected_obj=expected,
                   evidence=_evidence_for_row(ctx, uncertain_row),
                   reason=f"Low OCR confidence ({uncertain_row.confidence:.0%}); verify against the image.")
    if not ctx.coverage_adequate:
        return _mk(rule, RES_MANUAL_REVIEW, "Not detected", rule.requirement,
                   "Coverage insufficient — add rear/side coverage before deciding.", 0.0, field=fallback_field,
                   observed={"status": "NOT_DETECTED"}, expected_obj=expected,
                   reason="Panel coverage insufficient — the declaration may exist on an uncaptured panel.")
    return _mk(rule, RES_NON_COMPLIANT, "Not detected", rule.requirement,
               "None of the required declarations were identified in the available images.", 0.0,
               field=fallback_field, observed={"status": "NOT_DETECTED"}, expected_obj=expected,
               reason="None of the required declarations identified across the captured panels.")


def _check_text_contains(ctx: EvalContext, rule: models.Rule, phrase: str) -> ResultRow:
    """Check an accompanying-wording requirement against the extracted field row
    (a normalized product fact), never against raw OCR text."""
    row = _best_row(ctx, "inclusive_taxes_phrase") or _best_row(ctx, rule.field or "")
    present = row is not None and row.status != FIELD_NOT_FOUND and bool(row.value)
    expected = {"required": True}
    if present:
        return _mk(rule, RES_PASS, f"“{phrase}” present", rule.requirement,
                   "Required accompanying wording detected on the label.", 0.98, field=rule.field or "inclusive_taxes_phrase",
                   observed={"value": "present"}, expected_obj=expected,
                   evidence=_evidence_for_row(ctx, row))
    if not ctx.coverage_adequate:
        return _mk(rule, RES_MANUAL_REVIEW, "Wording not detected", rule.requirement,
                   "Coverage insufficient — add images before deciding.", 0.0, field=rule.field,
                   observed={"status": "NOT_DETECTED"}, expected_obj=expected,
                   reason="Panel coverage insufficient — the wording may exist on an uncaptured panel.")
    return _mk(rule, NON_COMPLIANT, "Wording not detected", rule.requirement,
               "The required accompanying wording was not found on the inspected panels.", 0.0,
               field=rule.field, observed={"status": "NOT_DETECTED"}, expected_obj=expected,
               reason="The required accompanying wording was not extracted from the captured panels.")


def _check_unit_known(ctx: EvalContext, rule: models.Rule) -> ResultRow:
    """Bug 4 fix: read per-sub-rule allowed_units and value_threshold from validation JSON.

    validation.allowed_units: list of canonical unit strings the rule accepts (e.g. ["ml","l"]).
    validation.value_threshold: dict with optional keys gte_kg, lt_kg, gte_l, lt_l, gte_m, lt_m.

    Without allowed_units, any parsed SI unit is accepted (generic presence check).
    When the quantity cannot be parsed, MANUAL_REVIEW is returned with a descriptive (not
    title-echoing) input_value.
    """
    validation = rule.validation or {}
    allowed_units: list[str] = validation.get("allowed_units") or []
    threshold: dict = validation.get("value_threshold") or {}

    row = _best_row(ctx, "net_quantity")
    state, conf = _state(row)
    if state != "present" or not row:
        return _check_present(ctx, rule, "net_quantity")

    raw_val = row.value or row.raw_text or ""
    hit = normalize_quantity(raw_val) or normalize_quantity(row.raw_text or "")

    if not hit:
        # Quantity label found but no parseable {value, unit} — genuine unparseable
        return _mk(rule, RES_MANUAL_REVIEW,
                   "Quantity not parseable from OCR",   # Bug 4: never echo raw label text
                   rule.requirement,
                   "The net quantity text was detected but could not be parsed into a "
                   "numeric value and unit — verify the printed quantity on the package.",
                   conf, field="net_quantity",
                   observed={"raw": raw_val},
                   expected_obj={"standard_unit": True, "allowed_units": allowed_units or "any SI"},
                   evidence=_evidence_for_row(ctx, row),
                   reason="Quantity text could not be normalised to a standard unit.")

    parsed_value = hit["value"]
    parsed_unit = hit["unit"]   # canonical: g, kg, ml, l, cl, mg, m, cm, mm, pcs …
    observed = {"value": parsed_value, "unit": parsed_unit}
    expected_obj = {"standard_unit": True}
    if allowed_units:
        expected_obj["allowed_units"] = allowed_units

    # Check allowed_units constraint
    if allowed_units and parsed_unit not in allowed_units:
        # Wrong unit for this sub-rule — not necessarily NON_COMPLIANT for the whole package
        # (another sub-rule may govern this unit type); emit MANUAL_REVIEW with clear reason.
        return _mk(rule, RES_MANUAL_REVIEW,
                   f"{parsed_value} {parsed_unit}",
                   rule.requirement,
                   f"Unit '{parsed_unit}' is not in the set accepted by this sub-rule "
                   f"({', '.join(allowed_units)}). This sub-rule may not apply to this commodity type — "
                   "inspector verification required.",
                   conf, field="net_quantity",
                   observed=observed, expected_obj=expected_obj,
                   evidence=_evidence_for_row(ctx, row),
                   reason=f"Declared unit '{parsed_unit}' not in allowed set {allowed_units} for this sub-rule.")

    # Check value_threshold constraints (using normalised grams/litres)
    if threshold:
        grams = quantity_to_grams(f"{parsed_value} {parsed_unit}")
        def _in_litres(v, u):
            ml_map = {"ml": 0.001, "l": 1.0, "cl": 0.01, "g": 0.001, "kg": 1.0}
            return v * ml_map.get(u, 0)
        litres = _in_litres(parsed_value, parsed_unit)
        metres = parsed_value if parsed_unit in ("m", "cm", "mm") else None
        fails = []
        if "lt_kg" in threshold and grams is not None and grams >= threshold["lt_kg"] * 1000:
            fails.append(f"quantity {parsed_value}{parsed_unit} is ≥ {threshold['lt_kg']} kg (sub-rule requires < {threshold['lt_kg']} kg)")
        if "gte_kg" in threshold and grams is not None and grams < threshold["gte_kg"] * 1000:
            fails.append(f"quantity {parsed_value}{parsed_unit} is < {threshold['gte_kg']} kg (sub-rule requires ≥ {threshold['gte_kg']} kg)")
        if "lt_l" in threshold and litres >= threshold["lt_l"]:
            fails.append(f"quantity {parsed_value}{parsed_unit} is ≥ {threshold['lt_l']} L (sub-rule requires < {threshold['lt_l']} L)")
        if "gte_l" in threshold and litres < threshold["gte_l"]:
            fails.append(f"quantity {parsed_value}{parsed_unit} is < {threshold['gte_l']} L (sub-rule requires ≥ {threshold['gte_l']} L)")
        if "lt_m" in threshold and metres is not None and metres >= threshold["lt_m"]:
            fails.append(f"quantity {parsed_value}{parsed_unit} is ≥ {threshold['lt_m']} m (sub-rule requires < {threshold['lt_m']} m)")
        if "gte_m" in threshold and metres is not None and metres < threshold["gte_m"]:
            fails.append(f"quantity {parsed_value}{parsed_unit} is < {threshold['gte_m']} m (sub-rule requires ≥ {threshold['gte_m']} m)")
        if fails:
            # Threshold mismatch — this sub-rule does not apply to this quantity range,
            # meaning a different sub-rule governs it. Emit MANUAL_REVIEW (not NON_COMPLIANT).
            return _mk(rule, RES_MANUAL_REVIEW,
                       f"{parsed_value} {parsed_unit}",
                       rule.requirement,
                       f"Value/unit ({parsed_value} {parsed_unit}) does not satisfy this sub-rule's "
                       f"threshold: {'; '.join(fails)}. Verify which sub-rule applies and inspect accordingly.",
                       conf, field="net_quantity",
                       observed=observed, expected_obj=expected_obj,
                       evidence=_evidence_for_row(ctx, row),
                       reason=f"Quantity threshold mismatch: {'; '.join(fails)}")

    # Passed all checks — unit is known, SI, and satisfies any threshold
    return _mk(rule, RES_PASS,
               f"{parsed_value} {parsed_unit}",
               rule.requirement,
               f"Net quantity declared as {parsed_value} {parsed_unit} — "
               f"unit is valid for this sub-rule.",
               conf, field="net_quantity",
               observed=observed,
               expected_obj=expected_obj,
               evidence=_evidence_for_row(ctx, row))


def _check_date_month_year(ctx: EvalContext, rule: models.Rule) -> ResultRow:
    row = _best_row(ctx, "date_of_packing")
    state, conf = _state(row)
    expected = {"format": "month & year (e.g. AUG 2026)"}
    if state == "absent":
        if not ctx.coverage_adequate:
            return _mk(rule, RES_MANUAL_REVIEW, "Not detected", rule.requirement,
                       "Coverage insufficient — add images before deciding.", 0.0, field="date_of_packing",
                       observed={"status": "NOT_DETECTED"}, expected_obj=expected,
                       reason="Panel coverage insufficient — the date may exist on an uncaptured panel.")
        return _mk(rule, NON_COMPLIANT, "Not detected", rule.requirement,
                   "Month & year of packing/manufacture not identified on the inspected panels.", 0.0,
                   field="date_of_packing", observed={"status": "NOT_DETECTED"}, expected_obj=expected,
                   reason="Month & year declaration not identified across the captured panels.")
    assert row is not None
    if state == "uncertain":
        return _mk(rule, RES_MANUAL_REVIEW, row.value or "Possibly present", rule.requirement,
                   f"Date region confidence is low ({conf:.0%}) — verify the printed date on the package.",
                   conf, field="date_of_packing", observed={"value": row.value}, expected_obj=expected,
                   evidence=_evidence_for_row(ctx, row),
                   reason=f"Low OCR confidence ({conf:.0%}) on the date region.")
    parsed = parse_month_year(row.value)
    if parsed is None:
        return _mk(rule, RES_MANUAL_REVIEW, row.value, rule.requirement,
                   "Date text detected but the month/year format could not be parsed — verify the package.",
                   conf, field="date_of_packing", observed={"value": row.value}, expected_obj=expected,
                   evidence=_evidence_for_row(ctx, row),
                   reason="Date text could not be parsed as a month & year combination.")
    return _mk(rule, RES_PASS, row.value, rule.requirement,
               f"Month/year declaration parsed ({parsed.strftime('%b %Y')}).", conf, field="date_of_packing",
               observed={"value": row.value}, expected_obj=expected,
               evidence=_evidence_for_row(ctx, row))


def _check_range(ctx: EvalContext, rule: models.Rule) -> ResultRow:
    """Range validation: numeric field must fall within [min, max] bounds.
    net_quantity is compared in grams, mrp_value in currency units, other
    numeric fields as parsed floats. Outside the range -> NON_COMPLIANT;
    unparseable -> MANUAL_REVIEW; missing -> falls back to presence check."""
    validation = rule.validation or {}
    field_name = validation.get("field", rule.field or "")
    min_val = validation.get("min")
    max_val = validation.get("max")
    row = _best_row(ctx, field_name)
    state, conf = _state(row)
    if state != "present" or not row or not row.value:
        return _check_present(ctx, rule, field_name)
    num: float | None = None
    if field_name == "net_quantity":
        num = quantity_to_grams(row.value) or quantity_to_grams(row.raw_text or "")
    elif field_name == "mrp_value":
        hit = normalize_amount(row.value) or normalize_amount(row.raw_text or "")
        num = hit["value"] if hit else None
    else:
        try:
            num = float(row.value.replace(",", ""))
        except ValueError:
            num = None
    expected = {k: v for k, v in (("min", min_val), ("max", max_val)) if v is not None}
    if num is None:
        return _mk(rule, RES_MANUAL_REVIEW, row.value, rule.requirement,
                   "Value present but could not be parsed as a number for range comparison — verify manually.",
                   conf, field=field_name, observed=_observed_value(row), expected_obj=expected,
                   evidence=_evidence_for_row(ctx, row),
                   reason="Value could not be parsed numerically for range comparison.")
    if min_val is not None and num < float(min_val):
        return _mk(rule, NON_COMPLIANT, row.value, f"≥ {min_val}",
                   f"Value {row.value} is below the required minimum ({min_val}).",
                   conf, field=field_name, observed=_observed_value(row), expected_obj=expected,
                   evidence=_evidence_for_row(ctx, row),
                   reason=f"Declared value {row.value} is below the minimum threshold {min_val}.")
    if max_val is not None and num > float(max_val):
        return _mk(rule, NON_COMPLIANT, row.value, f"≤ {max_val}",
                   f"Value {row.value} exceeds the allowed maximum ({max_val}).",
                   conf, field=field_name, observed=_observed_value(row), expected_obj=expected,
                   evidence=_evidence_for_row(ctx, row),
                   reason=f"Declared value {row.value} exceeds the maximum threshold {max_val}.")
    return _mk(rule, RES_PASS, row.value, f"{min_val or '—'} ≤ value ≤ {max_val or '—'}",
               f"Value {row.value} is within the required range.", conf, field=field_name,
               observed=_observed_value(row), expected_obj=expected, evidence=_evidence_for_row(ctx, row))


def _check_mrp_format(ctx: EvalContext, rule: models.Rule) -> ResultRow:
    row = _best_row(ctx, "mrp_value")
    state, conf = _state(row)
    expected = {"format": "₹ / Rs. with digits"}
    if state != "present" or not row:
        return _check_present(ctx, rule, "mrp_value")
    if re.match(r"^(₹|rs\.?|inr)?\s*\d+(\.\d{1,2})?$", row.value, re.IGNORECASE):
        hit = normalize_amount(row.value) or normalize_amount(row.raw_text or "")
        observed = {"value": hit["value"], "currency": hit["currency"]} if hit else {"value": row.value}
        return _mk(rule, RES_PASS, row.value, rule.requirement,
                   "Retail sale price is declared in clear numeric form.", conf, field="mrp_value",
                   observed=observed, expected_obj=expected, evidence=_evidence_for_row(ctx, row))
    return _mk(rule, RES_MANUAL_REVIEW, row.value, rule.requirement,
               "MRP text detected but not in a clean numeric form — verify manually.", conf,
               field="mrp_value", observed={"value": row.value}, expected_obj=expected,
               evidence=_evidence_for_row(ctx, row),
               reason="MRP text could not be normalised to a clean numeric value.")


# ---------------------------------------------------------------------------
# Prohibition check — field that MUST NOT appear / condition that must not hold
# ---------------------------------------------------------------------------
def _check_prohibition(ctx: EvalContext, rule: models.Rule) -> ResultRow:
    """A prohibition rule checks that a forbidden condition is absent.

    The register supplies a `prohibition` description, optional `trigger` (regex
    pattern that indicates the prohibited condition is present), and `fields` that
    might carry the forbidden content.

    Logic:
    - If no fields are named: always MANUAL_REVIEW (inspector must verify).
    - If trigger pattern is provided:
        - Run the regex against the detected field values.
        - NON_COMPLIANT only when the trigger pattern actually matches a field value.
        - COMPLIANT when the trigger does NOT match any detected field value.
        - MANUAL_REVIEW when fields are uncertain/undetected (can't confirm absence).
    - If trigger pattern is empty/not provided:
        - MANUAL_REVIEW always (OCR presence alone cannot confirm absence of a
          prohibited *condition* — inspector must verify from the physical package).
    """
    import re as _re
    validation = rule.validation or {}
    fields = validation.get("fields") or []
    prohibition_desc = validation.get("prohibition") or rule.requirement or rule.description
    trigger_pattern = (validation.get("trigger") or "").strip()
    expected = {"prohibited_condition_absent": True}

    if not fields:
        return _mk(
            rule, RES_MANUAL_REVIEW,
            trigger_pattern or "Prohibited condition",
            rule.requirement,
            "Prohibition cannot be machine-verified without a bindable extracted field — "
            "inspector must verify the prohibited condition from the physical package.",
            0.0,
            observed={"prohibition": prohibition_desc, "trigger": trigger_pattern},
            expected_obj=expected,
            reason="No engine-bindable field for prohibition check; manual verification required.",
        )

    if not trigger_pattern:
        # No machine-checkable trigger pattern — OCR text presence alone cannot confirm
        # absence of a prohibited *condition* (e.g., 'different MRP', 'deceptive packaging')
        return _mk(
            rule, RES_MANUAL_REVIEW,
            "Prohibition trigger pattern not defined",
            rule.requirement,
            f"Prohibition ({prohibition_desc}): no machine-checkable trigger pattern defined — "
            "inspector must verify whether the prohibited condition exists on the physical package.",
            0.0,
            observed={"prohibition": prohibition_desc, "fields": fields},
            expected_obj=expected,
            reason="No engine-bindable trigger pattern; manual verification required.",
        )

    # We have both fields and a trigger pattern — check regex against field values
    detected_violations = []
    uncertain_fields = []
    best_conf = 0.0
    try:
        pattern = _re.compile(trigger_pattern, _re.IGNORECASE)
    except _re.error:
        return _mk(
            rule, RES_MANUAL_REVIEW,
            "Invalid trigger pattern",
            rule.requirement,
            f"Prohibition ({prohibition_desc}): trigger pattern is not a valid regex — "
            "inspector must verify manually.",
            0.0,
            observed={"prohibition": prohibition_desc, "trigger_error": trigger_pattern},
            expected_obj=expected,
            reason="Invalid trigger regex pattern; manual verification required.",
        )

    for fname in fields:
        row = _best_row(ctx, fname)
        state, conf = _state(row)
        best_conf = max(best_conf, conf)
        if state == "present":
            field_value = (row.value or "") if row else ""
            if pattern.search(field_value):
                detected_violations.append(fname)
            # field present but prohibited pattern NOT found in value — compliant for this field
        elif state == "uncertain":
            uncertain_fields.append(fname)
        # not_found: field absent, cannot verify prohibition — counted as uncertain

    if detected_violations:
        return _mk(
            rule, RES_NON_COMPLIANT,
            ", ".join(detected_violations),
            rule.requirement,
            f"Prohibited content detected in: {', '.join(detected_violations)}. "
            f"Prohibition: {prohibition_desc}.",
            best_conf,
            observed={"detected": detected_violations, "prohibition": prohibition_desc,
                      "trigger": trigger_pattern},
            expected_obj=expected,
            reason=f"Prohibited content detected: {prohibition_desc}.",
        )
    if uncertain_fields:
        return _mk(
            rule, RES_MANUAL_REVIEW,
            ", ".join(uncertain_fields),
            rule.requirement,
            f"Prohibition: {prohibition_desc}. Related fields are uncertain — "
            "manual verification required.",
            best_conf,
            observed={"uncertain": uncertain_fields, "prohibition": prohibition_desc},
            expected_obj=expected,
            reason="Related fields uncertain; cannot confirm prohibition is satisfied.",
        )
    # All detected fields: trigger pattern NOT found — prohibition satisfied
    return _mk(
        rule, RES_PASS,
        "No prohibited content detected",
        rule.requirement,
        f"Prohibition ({prohibition_desc}): trigger pattern not found in any detected field values.",
        best_conf,
        observed={"prohibition_satisfied": True, "trigger": trigger_pattern, "fields_checked": fields},
        expected_obj=expected,
    )


# ---------------------------------------------------------------------------
# Always-manual — bucket 3 rules that are never auto-evaluated
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Language check (Bug 3: Rule 9(4) — permitted languages)
# ---------------------------------------------------------------------------
def _check_language(ctx: EvalContext, rule: models.Rule) -> ResultRow:
    """Rule 9(4): declarations must be in a permitted language (English and/or Hindi).

    Check: at least one declaration field contains English text (ASCII letters).
    Hindi (Devanagari) is also acceptable but not required for all commodities.
    If OCR found no text in any declaration field → MANUAL_REVIEW.
    If only foreign-script text with no English/Hindi → NON_COMPLIANT.
    If English present → COMPLIANT.
    """
    import unicodedata as _ud
    validation = rule.validation or {}
    # All the key declaration fields to check for language
    decl_fields = validation.get("fields") or [
        "product_name", "manufacturer_name", "net_quantity", "mrp_value", "date_of_packing",
    ]
    has_english = False
    has_devanagari = False
    has_any_text = False
    sample_text = ""
    for fname in decl_fields:
        row = _best_row(ctx, fname)
        state, _ = _state(row)
        if state == "present" and row and row.value:
            has_any_text = True
            text = row.value
            if not sample_text:
                sample_text = text[:60]
            # English: ASCII a-z A-Z letters present
            if any(c.isascii() and c.isalpha() for c in text):
                has_english = True
            # Devanagari: Unicode block 0900–097F
            if any('ऀ' <= c <= 'ॿ' for c in text):
                has_devanagari = True
    expected = {"language": "English and/or Hindi (Devanagari)"}
    if not has_any_text:
        return _mk(rule, RES_MANUAL_REVIEW,
                   "No declaration text detected",
                   rule.requirement,
                   "No declaration text was extracted — coverage may be insufficient to verify language compliance.",
                   0.0, field="product_name",
                   observed={"detected_text": None}, expected_obj=expected,
                   reason="No OCR text extracted; language verification not possible.")
    if has_english:
        lang_note = "English" + (" + Hindi (Devanagari)" if has_devanagari else "")
        return _mk(rule, RES_PASS,
                   lang_note,
                   rule.requirement,
                   f"Declarations include permitted language ({lang_note}) — compliant with Rule 9(4).",
                   0.85, field="product_name",
                   observed={"language_detected": lang_note, "sample": sample_text},
                   expected_obj=expected)
    if has_devanagari:
        return _mk(rule, RES_PASS,
                   "Hindi (Devanagari)",
                   rule.requirement,
                   "Declarations in Hindi (Devanagari) — compliant with Rule 9(4).",
                   0.8, field="product_name",
                   observed={"language_detected": "Hindi (Devanagari)", "sample": sample_text},
                   expected_obj=expected)
    # Has text but neither English nor Devanagari — non-compliant
    return _mk(rule, RES_NON_COMPLIANT,
               sample_text or "Unknown script",
               rule.requirement,
               "Detected text does not appear to be in English or Hindi — verify the declaration language on the package.",
               0.6, field="product_name",
               observed={"sample": sample_text, "has_english": False, "has_devanagari": False},
               expected_obj=expected,
               reason="Declaration text not identified as English or Hindi (Devanagari).")


# ---------------------------------------------------------------------------
# Contrast check (Bug 3: Rule 9(1)(b) — contrasting colour for MRP/quantity)
# ---------------------------------------------------------------------------
def _check_contrast(ctx: EvalContext, rule: models.Rule) -> ResultRow:
    """Rule 9(1)(b): MRP and net quantity must be in contrasting colour.

    Attempt: use the OCR bounding box + PIL to sample foreground/background pixel
    luminance in the MRP and quantity regions. Compute WCAG 2.1 contrast ratio.
    Ratio ≥ 3.0 for large text (≥ 18pt) → COMPLIANT.
    If image not readable or bbox not available → MANUAL_REVIEW with specific reason.
    """
    try:
        from PIL import Image as _PILImage
    except ImportError:
        return _mk(rule, RES_MANUAL_REVIEW,
                   "Image analysis library not available",
                   rule.requirement,
                   "PIL/Pillow not available — contrast ratio check cannot run. Inspector must verify contrasting colours on MRP and quantity declarations.",
                   0.0, observed={"engine_action": "contrast_check_unavailable"},
                   expected_obj={"contrast_ratio_min": 3.0},
                   reason="PIL/Pillow library not installed; contrast check skipped.")

    import os, math

    def _relative_luminance(rgb: tuple) -> float:
        """WCAG 2.1 relative luminance from sRGB."""
        def _chan(c: float) -> float:
            c = c / 255.0
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = rgb[0], rgb[1], rgb[2]
        return 0.2126 * _chan(r) + 0.7152 * _chan(g) + 0.0722 * _chan(b)

    def _contrast_ratio(l1: float, l2: float) -> float:
        lighter = max(l1, l2) + 0.05
        darker = min(l1, l2) + 0.05
        return lighter / darker

    check_fields = ["mrp_value", "net_quantity"]
    results = []
    CONTRAST_MIN = 3.0
    expected = {"contrast_ratio_min": CONTRAST_MIN, "fields": check_fields}

    for fname in check_fields:
        row = _best_row(ctx, fname)
        if not row or row.status == FIELD_NOT_FOUND:
            continue
        img_model = _image_for(ctx, row)
        if img_model is None:
            continue
        # Try to load from storage path (model field is storage_path)
        img_path = None
        if img_model.storage_path:
            img_path = img_model.storage_path
        # Also try enhanced path (may have better quality)
        if img_model.enhanced_path and os.path.exists(img_model.enhanced_path):
            img_path = img_model.enhanced_path
        if not img_path or not os.path.exists(img_path):
            continue
        try:
            pil_img = _PILImage.open(img_path).convert("RGB")
        except Exception:
            continue
        bbox = row.bbox or {}
        if not bbox:
            continue
        x0 = int(float(bbox.get("x", 0)) * pil_img.width)
        y0 = int(float(bbox.get("y", 0)) * pil_img.height)
        x1 = int((float(bbox.get("x", 0)) + float(bbox.get("width", 0.1))) * pil_img.width)
        y1 = int((float(bbox.get("y", 0)) + float(bbox.get("height", 0.05))) * pil_img.height)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(pil_img.width, x1), min(pil_img.height, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        region = pil_img.crop((x0, y0, x1, y1))
        pixels = list(region.getdata())
        if not pixels:
            continue
        # Estimate foreground (darkest 20%) and background (lightest 20%) luminance
        lums = sorted([_relative_luminance(p) for p in pixels])
        n = len(lums)
        fg_lum = sum(lums[:max(1, n // 5)]) / max(1, n // 5)
        bg_lum = sum(lums[-(n // 5):]) / max(1, n // 5)
        ratio = _contrast_ratio(fg_lum, bg_lum)
        results.append({"field": fname, "contrast_ratio": round(ratio, 2),
                         "fg_luminance": round(fg_lum, 4), "bg_luminance": round(bg_lum, 4)})

    if not results:
        return _mk(rule, RES_MANUAL_REVIEW,
                   "Image/bbox data not available",
                   rule.requirement,
                   "Contrast ratio cannot be computed — no readable image with bounding box data is available. Inspector must verify contrasting colours for MRP and quantity declarations.",
                   0.0, observed={"reason": "no_image_bbox"},
                   expected_obj=expected,
                   reason="No image or bounding-box data available for contrast ratio computation.")

    min_ratio = min(r["contrast_ratio"] for r in results)
    observed = {"contrast_results": results, "min_contrast_ratio": min_ratio}

    if min_ratio >= CONTRAST_MIN:
        return _mk(rule, RES_PASS,
                   f"Min contrast ratio {min_ratio:.1f}:1",
                   rule.requirement,
                   f"MRP/quantity colour contrast ratio {min_ratio:.1f}:1 meets the minimum threshold of {CONTRAST_MIN}:1.",
                   0.85, observed=observed, expected_obj=expected)
    return _mk(rule, RES_NON_COMPLIANT,
               f"Contrast ratio {min_ratio:.1f}:1",
               rule.requirement,
               f"Detected colour contrast ratio {min_ratio:.1f}:1 is below the required {CONTRAST_MIN}:1 — MRP/quantity may not stand out sufficiently from the background.",
               0.75, observed=observed, expected_obj=expected,
               reason=f"Contrast ratio {min_ratio:.1f}:1 below minimum {CONTRAST_MIN}:1 for large text.")


def _check_always_manual(ctx: EvalContext, rule: models.Rule) -> ResultRow:
    """Rules that require physical or subjective inspector verification.

    These rules have validation.kind='always_manual' in the register, meaning
    the engine cannot produce a definitive pass/fail from OCR / image data alone.
    The engine always returns MANUAL_REVIEW so the inspector handles them.

    Bug 3 fix: use validation.reason for a rule-specific explanation rather than
    a shared generic string. Each always_manual rule should supply its own reason.
    """
    validation = rule.validation or {}
    # Rule-specific reason from register (Bug 3 fix: overrides generic fallback)
    specific_reason = (validation.get("reason") or "").strip()
    generic_note = (
        "This requirement cannot be determined from image or OCR data alone — "
        "inspector physical verification is required."
    )
    note = specific_reason if specific_reason else generic_note
    return _mk(
        rule, RES_MANUAL_REVIEW,
        "Manual inspector verification required",
        rule.requirement,
        note,
        0.0,
        observed={"engine_action": "always_manual"},
        expected_obj={"manual_inspection_required": True},
        reason=specific_reason if specific_reason else "Register marks this provision as requiring manual inspector verification.",
    )


# ---------------------------------------------------------------------------
# Needs-review / deferred — excluded rules that somehow get here
# ---------------------------------------------------------------------------
def _check_needs_review(ctx: EvalContext, rule: models.Rule) -> ResultRow:
    """Catch-all for rules that could not be fully mapped in A2 and are
    marked scope='deferred' or kind='needs_review'. Produce MANUAL_REVIEW
    rather than crashing or silently skipping the rule."""
    return _mk(
        rule, RES_MANUAL_REVIEW,
        "Manual inspector verification required",   # Bug 2 fix: never echo rule.title
        rule.requirement,
        "This rule requires human mapping review before it can be automatically "
        "evaluated — inspector must assess manually.",
        0.0,
        observed={"engine_action": "needs_review"},
        expected_obj={"mapping_required": True},
        reason="Rule validation.kind=needs_review: insufficient parameter data for automatic check.",
    )


# ---------------------------------------------------------------------------
# Font / placement / spacing — per-declaration expansion
# ---------------------------------------------------------------------------
_FONT_FIELDS = ["product_name", "net_quantity", "mrp_value", "manufacturer_name", "consumer_care_number"]
_PLACEMENT_FIELDS = ["net_quantity", "mrp_value"]


def _image_quality_ok(img: models.InspectionImage) -> bool:
    quality = (img.quality or {}).get("scores", {})
    return (
        float(quality.get("blur_score", 0)) < 0.55
        and float(quality.get("glare_pct", 0)) < 0.12
    )


def _font_rows(ctx: EvalContext, rule: models.Rule, sort: int) -> list[ResultRow]:
    min_ratio = float((rule.validation or {}).get("min_ratio", 0.020))
    fields = (rule.validation or {}).get("fields", _FONT_FIELDS)
    images = {i.id: i for i in ctx.inspection.images}
    out: list[ResultRow] = []
    made = 0
    for fname in fields:
        row = _best_row(ctx, fname)
        state, conf = _state(row)
        if state != "present" or not row or not row.image_id or not row.bbox:
            continue
        img = images.get(row.image_id)
        if img is None:
            continue
        bbox = row.bbox
        ratio = float(bbox.get("height", 0.0))
        quality_ok = _image_quality_ok(img)
        if row.confidence >= 0.93 and quality_ok:
            band = "high"
        elif row.confidence >= 0.8:
            band = "medium"
        else:
            band = "low"
        detected = f"{fname.replace('_', ' ').title()}: {row.value or 'detected'}"
        requirement = f"Minimum estimated text height ≥ {min_ratio:.3f} × captured-image height"
        analysis = {
            "kind": "font", "field": fname, "image_public_id": img.image_id,
            "region_id": row.region_id, "detected_text": row.raw_text or row.value,
            "ratio": round(ratio, 4), "min_ratio": min_ratio,
            "method": "Relative estimate: text-region height ÷ captured-image height. Not a "
                      "millimetre measurement — no calibration reference is available.",
            "calibration_available": False, "measurement_confidence": band,
            "readability": "good" if quality_ok else "review",
        }
        made += 1
        sort += 1
        ev = _evidence_for_row(ctx, row)
        obs = {"estimated_height_ratio": round(ratio, 4)}
        exp = {"minimum_ratio": min_ratio}
        if band == "low":
            analysis["automated_result"] = "review"
            out.append(_mk(rule, RES_MANUAL_REVIEW, detected, requirement,
                           "Font analysis auto-flagged for manual review (measurement confidence low; "
                           "no reliable physical scale). Relative estimate only.", conf,
                           field=fname, analyses=[analysis], sort=sort, observed=obs, expected_obj=exp,
                           evidence=ev,
                           reason="Physical scale could not be established reliably; relative estimate only."))
        elif ratio >= min_ratio and ratio >= min_ratio * 1.15:
            analysis["automated_result"] = "pass"
            out.append(_mk(rule, RES_PASS, detected, requirement,
                           f"Estimated relative text height {ratio:.3f} meets the configured minimum "
                           f"({min_ratio:.3f}). Relative estimate.", conf, field=fname,
                           analyses=[analysis], sort=sort, observed=obs, expected_obj=exp, evidence=ev))
        elif ratio < min_ratio:
            analysis["automated_result"] = "potential_fail"
            out.append(_mk(rule, RES_MANUAL_REVIEW, detected, requirement,
                           f"Potential font issue: estimated relative text height {ratio:.3f} is below "
                           f"the configured minimum ({min_ratio:.3f}). Inspector verification required — "
                           f"image-based estimate, not a calibrated measurement.", conf, field=fname,
                           analyses=[analysis], sort=sort, observed=obs, expected_obj=exp, evidence=ev,
                           reason="Estimated text height is below the configured minimum; image-based "
                                  "estimate only, not a calibrated measurement."))
        else:
            analysis["automated_result"] = "review"
            out.append(_mk(rule, RES_MANUAL_REVIEW, detected, requirement,
                           "Font measurement marginal — manual review requested before finalising.",
                           conf, field=fname, analyses=[analysis], sort=sort, observed=obs,
                           expected_obj=exp, evidence=ev,
                           reason="Font measurement is borderline (marginal relative height)."))
    if not made:
        # No declaration available to measure — emit one MANUAL_REVIEW row so the rule
        # is still counted in aggregate_counts (Bug 1 fix: every applicable rule must
        # produce at least one row, otherwise the applicable count and rules_checked diverge).
        return [_mk(rule, RES_MANUAL_REVIEW,
                    "No declaration region detected for font measurement",
                    f"Minimum estimated text height ≥ {min_ratio:.3f} × image height",
                    "Font size cannot be assessed — no sufficiently-clear declaration region was detected in the uploaded images. Inspector must verify text height meets requirements.",
                    0.0,
                    observed={"engine_action": "font_no_data"},
                    expected_obj={"minimum_ratio": min_ratio},
                    reason="No readable declaration region available; font measurement deferred to inspector.")]
    return out



def _placement_rows(ctx: EvalContext, rule: models.Rule, sort: int) -> list[ResultRow]:
    images = {i.id: i for i in ctx.inspection.images}
    out: list[ResultRow] = []
    made = 0
    for fname in _PLACEMENT_FIELDS:
        row = _best_row(ctx, fname)
        state, conf = _state(row)
        if state != "present" or not row or not row.image_id:
            continue
        img = images.get(row.image_id)
        if img is None:
            continue
        bbox = row.bbox or {}
        y = float(bbox.get("y", 0.5))
        central = 0.08 <= y <= 0.85
        on_primary = img.side == "front"
        analysis = {
            "kind": "placement", "field": fname, "image_public_id": img.image_id,
            "region_id": row.region_id, "detected_location": img.side,
            "position_confidence": "high" if (on_primary and central) else ("medium" if central else "low"),
            "automated_result": "pass" if (on_primary and central and conf >= 0.9) else "review",
        }
        made += 1
        sort += 1
        ev = _evidence_for_row(ctx, row)
        obs = {"panel": img.side, "position_confidence": analysis["position_confidence"]}
        exp = {"principal_display_panel": True}
        if on_primary and central and conf >= 0.9:
            out.append(_mk(rule, RES_PASS, f"{fname.replace('_', ' ')} on {img.side}", rule.requirement,
                           "Declaration located on the principal display panel in a clear region.",
                           conf, field=fname, analyses=[analysis], sort=sort, observed=obs,
                           expected_obj=exp, evidence=ev))
        else:
            note = ("Declaration not located on the principal display panel in the available images — "
                    "verify placement." if not on_primary else
                    "Position detected but placement confidence is limited — review the region.")
            out.append(_mk(rule, RES_MANUAL_REVIEW, f"{fname.replace('_', ' ')} on {img.side}", rule.requirement,
                           note, conf, field=fname, analyses=[analysis], sort=sort, observed=obs,
                           expected_obj=exp, evidence=ev,
                           reason="Declaration not confirmed on the principal display panel."))
    return out


def _spacing_row(ctx: EvalContext, rule: models.Rule, sort: int) -> ResultRow | None:
    row = _best_row(ctx, "net_quantity")
    state, conf = _state(row)
    if state != "present" or not row or not row.image_id:
        return None
    bbox = row.bbox or {}
    rx0, ry0, rw, rh = float(bbox.get("x", 0)), float(bbox.get("y", 0)), float(bbox.get("width", 0)), float(bbox.get("height", 0))
    rx1, ry1 = rx0 + rw, ry0 + rh
    regions = [r for r in ctx.inspection.ocr_results if r.image_id == row.image_id and r.id != row.id]
    top_gap = bottom_gap = side_gap = 9.9
    for r in regions:
        b = r.bbox or {}
        bx0, by0 = float(b.get("x", 0)), float(b.get("y", 0))
        bw, bh = float(b.get("width", 0)), float(b.get("height", 0))
        bx1, by1 = bx0 + bw, by0 + bh
        if bx1 < rx0 or bx0 > rx1:
            side_gap = min(side_gap, abs(bx1 - rx0) if bx1 < rx0 else abs(rx1 - bx0))
        elif by1 <= ry0:
            top_gap = min(top_gap, ry0 - by1)
        elif by0 >= ry1:
            bottom_gap = min(bottom_gap, by0 - ry1)
    analysis = {
        "kind": "spacing", "field": "net_quantity",
        "top_gap_ratio": round(top_gap, 4), "bottom_gap_ratio": round(bottom_gap, 4),
        "side_gap_ratio": round(side_gap, 4), "text_height_ratio": round(rh, 4),
        "expected": "Relative spacing ≈ numeral height above/below and ≈ 2× numeral height on each side.",
        "automated_result": "review",
    }
    ev = _evidence_for_row(ctx, row)
    obs = {"top_gap_ratio": round(top_gap, 4), "bottom_gap_ratio": round(bottom_gap, 4),
           "side_gap_ratio": round(side_gap, 4)}
    exp = {"spacing_adequate": True}
    if top_gap >= rh * 0.8 and bottom_gap >= rh * 0.8 and side_gap >= rh * 1.0 and conf >= 0.9:
        analysis["automated_result"] = "pass"
        return _mk(rule, RES_PASS, "Spacing adequate", rule.requirement,
                   f"Relative spacing around the quantity declaration is adequate (above {top_gap:.3f}, "
                   f"below {bottom_gap:.3f}, sides {side_gap:.3f} × height).", conf, field="net_quantity",
                   analyses=[analysis], sort=sort, observed=obs, expected_obj=exp, evidence=ev)
    analysis["automated_result"] = "review"
    return _mk(rule, RES_MANUAL_REVIEW, "Spacing tight / unverified", rule.requirement,
               "Relative spacing around the quantity declaration could not be confirmed (marginal "
               "geometry or confidence). Verify against the physical package.", conf,
               field="net_quantity", analyses=[analysis], sort=sort, observed=obs, expected_obj=exp,
               evidence=ev,
               reason="Relative spacing around the quantity declaration could not be confirmed.")


def evaluate_rule(ctx: EvalContext, rule: models.Rule, sort: int) -> list[ResultRow]:
    validation = rule.validation or {}
    kind = validation.get("kind", "present")
    if rule.type == "font":
        return _font_rows(ctx, rule, sort)
    if rule.type == "placement":
        return _placement_rows(ctx, rule, sort)
    if rule.type == "spacing":
        row = _spacing_row(ctx, rule, sort)
        return [row] if row else []
    if rule.type == "cross":
        return []  # handled separately (cross-field / cross-source checks)

    if kind == "any_present":
        return [_check_any_present(ctx, rule, validation.get("fields", []))]
    if kind == "text_contains":
        return [_check_text_contains(ctx, rule, validation.get("pattern", ""))]
    if kind == "unit_known":
        return [_check_unit_known(ctx, rule)]
    if kind == "date_month_year":
        return [_check_date_month_year(ctx, rule)]
    if kind == "format_mrp":
        return [_check_mrp_format(ctx, rule)]
    if kind == "range":
        return [_check_range(ctx, rule)]
    if kind == "prohibition":
        return [_check_prohibition(ctx, rule)]
    if kind == "language_check":
        return [_check_language(ctx, rule)]
    if kind == "contrast_check":
        return [_check_contrast(ctx, rule)]
    if kind == "always_manual":
        return [_check_always_manual(ctx, rule)]
    if kind in ("needs_review", "reference"):
        # needs_review = A2 deferred; reference = should never reach here (filtered by scope)
        return [_check_needs_review(ctx, rule)]
    return [_check_present(ctx, rule, validation.get("field", rule.field or ""))]


# ---------------------------------------------------------------------------
# Cross-field / cross-source consistency checks (POTENTIAL_NON_COMPLIANCE)
# ---------------------------------------------------------------------------
def _normalised_grams(row: models.ExtractedField) -> float | None:
    return quantity_to_grams(row.value or "") or quantity_to_grams(row.raw_text or "")


def _cross_consistency_row(ctx: EvalContext, rule: models.Rule, sort: int) -> ResultRow | None:
    """Two conflicting readings of one field across panels -> POTENTIAL_NON_COMPLIANCE
    with both values + both evidence images. Consistent multi-panel readings -> COMPLIANT.
    A single reading -> nothing to compare, row omitted."""
    rows = [r for r in ctx.field_map.get("net_quantity", []) if r.status != FIELD_NOT_FOUND]
    readings: list[tuple[float, models.ExtractedField]] = []
    for r in rows:
        grams = _normalised_grams(r)
        if grams is not None:
            readings.append((grams, r))
    if not readings:
        return None
    distinct: dict[float, models.ExtractedField] = {}
    for grams, r in readings:
        cur = distinct.get(grams)
        if cur is None or r.confidence > cur.confidence:
            distinct[grams] = r
    values = sorted(distinct.items(), key=lambda kv: kv[1].confidence, reverse=True)
    expected = {"consistent_across_package": True}
    if len(values) > 1:
        (g1, r1), (g2, r2) = values[0], values[1]
        img1 = _image_for(ctx, r1)
        img2 = _image_for(ctx, r2)
        observed = {
            "value_1": {"value": r1.value, "image_id": img1.image_id if img1 else None},
            "value_2": {"value": r2.value, "image_id": img2.image_id if img2 else None},
        }
        evidence = {"image_ids": [i.image_id for i in (img1, img2) if i is not None]}
        reason = ("Two conflicting net quantity declarations were detected on different panels of the "
                  "same package — cross-field mismatch flagged for inspection.")
        return _mk(rule, RES_POTENTIAL_NON_COMPLIANCE, f"{r1.value} vs {r2.value}",
                   "consistent across package", reason,
                   max(r1.confidence, r2.confidence), field="net_quantity", sort=sort,
                   observed=observed, expected_obj=expected, evidence=evidence, reason=reason)
    (grams, row) = values[0]
    ev = _evidence_for_row(ctx, row)
    hit = normalize_quantity(row.value) or normalize_quantity(row.raw_text or "")
    observed = {"value": hit["value"], "unit": hit["unit"]} if hit else {"value": row.value}
    return _mk(rule, RES_PASS, row.value, "consistent across package",
               "Net quantity declared consistently across the captured panels.",
               row.confidence, field="net_quantity", sort=sort,
               observed=observed, expected_obj=expected, evidence=ev)


def _cross_source_row(ctx: EvalContext, rule: models.Rule, sort: int) -> ResultRow | None:
    """Compare the extracted package value against a manually entered online
    listing value. Only runs when the inspector has supplied an online listing."""
    listing = ctx.inspection.online_listing or {}
    field = (listing.get("field") or "").strip()
    listing_value = (listing.get("value") or "").strip()
    source = (listing.get("source") or "online listing").strip()
    if not field or not listing_value:
        return None

    def _norm(text: str) -> float | None:
        if field == "net_quantity":
            return quantity_to_grams(text)
        if field == "mrp_value":
            hit = normalize_amount(text)
            return hit["value"] if hit else None
        return None

    package_row = _best_row(ctx, field)
    package_norm = _norm(package_row.value) if package_row and package_row.value else None
    listing_norm = _norm(listing_value)
    expected = {"matches_listing": True}
    if package_row is None or package_row.status == FIELD_NOT_FOUND or package_norm is None:
        return _mk(rule, RES_MANUAL_REVIEW, f"Listing: {listing_value} ({source})", rule.requirement,
                   "Online listing value could not be compared — the package value was not extracted "
                   "(or could not be normalised). Verify against the physical package.",
                   package_row.confidence if package_row else 0.0, field=field, sort=sort,
                   observed={"online_listing": {"value": listing_value, "source": source}},
                   expected_obj=expected,
                   reason="Online listing comparison inconclusive: package value missing or unreadable.")
    if listing_norm is None:
        return _mk(rule, RES_MANUAL_REVIEW, f"Listing: {listing_value} ({source})", rule.requirement,
                   "The online listing value could not be normalised for comparison — verify manually.",
                   package_row.confidence, field=field, sort=sort,
                   observed={"online_listing": {"value": listing_value, "source": source}},
                   expected_obj=expected,
                   reason="Online listing value could not be normalised to a comparable quantity.")
    img = _image_for(ctx, package_row)
    pkg_obs = {"value": package_row.value, "image_id": img.image_id if img else None}
    lst_obs = {"value": listing_value, "source": source}
    if abs(package_norm - listing_norm) > 1e-6:
        reason = (f"Cross-source mismatch: the package declares {package_row.value} while the online "
                  f"listing ({source}) states {listing_value}.")
        return _mk(rule, RES_POTENTIAL_NON_COMPLIANCE, f"Package: {package_row.value} vs Listing: {listing_value}",
                   rule.requirement, reason, package_row.confidence, field=field, sort=sort,
                   observed={"value_1": pkg_obs, "value_2": lst_obs},
                   expected_obj=expected,
                   evidence={"image_ids": [img.image_id] if img else []}, reason=reason)
    return _mk(rule, RES_PASS, f"Package: {package_row.value} = Listing: {listing_value}",
               rule.requirement,
               "The online listing value matches the value declared on the package.",
               package_row.confidence, field=field, sort=sort,
               observed={"value_1": pkg_obs, "value_2": lst_obs}, expected_obj=expected,
               evidence={"image_ids": [img.image_id] if img else []})


def _cross_rows(ctx: EvalContext, rule: models.Rule, sort: int) -> list[ResultRow]:
    kind = (rule.validation or {}).get("kind", "")
    subtype = (rule.validation or {}).get("subtype", "")
    if kind == "cross_consistency":
        row = _cross_consistency_row(ctx, rule, sort)
        return [row] if row else []
    if kind == "cross_source":
        if subtype == "external_regulation_reference":
            # This is a citation-only cross-reference to an external regulation
            # (e.g. Consumer Protection Act). The engine cannot verify compliance
            # with the external regulation from package images — always MANUAL_REVIEW.
            external_source = (rule.validation or {}).get("external_source", "")
            row = _mk(
                rule, RES_MANUAL_REVIEW,
                "External regulation reference — manual verification required",  # Bug 2 fix
                rule.requirement,
                f"This provision references an external regulation ({external_source or 'see rule'}) "
                "that cannot be verified from package images alone. Inspector verification required.",
                0.0,
                observed={"external_source": external_source},
                expected_obj={"external_regulation_compliance": True},
                reason="External regulation reference — cannot be auto-verified from OCR/image data.",
            )
            return [row]
        row = _cross_source_row(ctx, rule, sort)
        return [row] if row else []
    return []


# ---------------------------------------------------------------------------
# Findings + analysis-row materialisation
# ---------------------------------------------------------------------------
def _finding_type(rule_type: str) -> str:
    return {
        "content": "mandatory_declaration", "font": "font_readability",
        "placement": "placement_format", "spacing": "placement_format", "format": "format",
        "cross": "cross_field_check",
    }.get(rule_type, "other_rule")


def _materialise(db: Session, ctx: EvalContext, rows: list[ResultRow],
                 seed_image_evidence: bool = True) -> dict:
    inspection = ctx.inspection
    images = {i.id: i for i in inspection.images}

    # 1. Persist rule results (keep per-row analysis payloads by key)
    payload_by_key: dict[tuple, list[dict]] = {}
    for rr in rows:
        obj = models.RuleResult(
            inspection_id=inspection.id, rule_id=rr.rule_id, rule_number=rr.rule_number,
            sub_rule=rr.sub_rule, title=rr.title, category=rr.category, type=rr.type,
            requirement=rr.requirement, result=rr.result, input_value=rr.input_value,
            expected_value=rr.expected_value, note=rr.note, confidence=rr.confidence,
            severity=rr.severity, field=rr.field, evidence_required=rr.evidence_required,
            sort_order=rr.sort, observed=rr.observed, expected=rr.expected,
            evidence=rr.evidence, reason=rr.reason,
        )
        db.add(obj)
        if rr.analyses:
            payload_by_key[(rr.rule_id, rr.type, rr.field)] = rr.analyses
    db.flush()

    persisted = db.query(models.RuleResult).filter(
        models.RuleResult.inspection_id == inspection.id).order_by(models.RuleResult.sort_order).all()

    # 2. Findings (NON_COMPLIANT / MANUAL_REVIEW / POTENTIAL_NON_COMPLIANCE only)
    finding_by_key: dict[tuple, models.Finding] = {}
    seq = 0
    for p in persisted:
        if p.result not in (NON_COMPLIANT, MANUAL_REVIEW, POTENTIAL_NON_COMPLIANCE):
            continue
        seq += 1
        source = _pick_source_image(ctx, p.field, images)
        f = models.Finding(
            finding_id=f"F-{seq:03d}", inspection_id=inspection.id, rule_result_id=p.id,
            rule_id=p.rule_id, finding_type=_finding_type(p.type), requirement=p.requirement,
            detected_condition=p.input_value, expected_condition=p.expected_value,
            engine_result="fail" if p.result == NON_COMPLIANT else "review",
            severity=p.severity, confidence=p.confidence,
            source_image_id=source["image_id"], ocr_region_id=source["region_id"],
            source_field=p.field or "", rule_number=p.rule_number, sub_rule=p.sub_rule,
            inspector_status="pending", sort_order=p.sort_order,
        )
        db.add(f)
        finding_by_key[(p.rule_id, p.type, p.field)] = f
    db.flush()

    # 3. Font / placement / spacing analysis rows (even for passing declarations)
    for p in persisted:
        analyses = payload_by_key.get((p.rule_id, p.type, p.field), [])
        finding = finding_by_key.get((p.rule_id, p.type, p.field))
        for a in analyses:
            if a.get("kind") == "font":
                db.add(models.FontAnalysis(
                    inspection_id=inspection.id, finding_id=finding.id if finding else None,
                    image_id=a.get("image_public_id", ""), region_id=a.get("region_id", ""),
                    field=a.get("field", ""), detected_text=a.get("detected_text", ""),
                    readability_score=0.9 if a.get("readability") == "good" else 0.55,
                    readability=a.get("readability", "review"),
                    font_estimate=a.get("ratio"), measurement_unit="ratio",
                    measurement_method=a.get("method", "image-based relative estimate"),
                    calibration_available=bool(a.get("calibration_available", False)),
                    measurement_confidence=a.get("measurement_confidence", "medium"),
                    applicable_rule=p.sub_rule or p.rule_number,
                    required_condition=f"Minimum ratio {a.get('min_ratio', '—')}",
                    automated_result=a.get("automated_result", "review"),
                    manual_review_required=a.get("automated_result") != "pass",
                ))
            elif a.get("kind") in ("placement", "spacing"):
                db.add(models.PlacementAnalysis(
                    inspection_id=inspection.id, finding_id=finding.id if finding else None,
                    image_id=a.get("image_public_id", ""), region_id=a.get("region_id", ""),
                    field=a.get("field", ""), detected_location=a.get("detected_location", ""),
                    detected_panel=a.get("detected_location", ""),
                    position_confidence=a.get("position_confidence", "medium"),
                    format_observation=a.get("expected", ""), format_confidence="medium",
                    applicable_rule=p.sub_rule or p.rule_number, requirement=p.requirement,
                    expected_condition=a.get("expected", p.expected_value),
                    detected_condition=(
                        f"Above {a.get('top_gap_ratio', '—')} / below {a.get('bottom_gap_ratio', '—')} / "
                        f"sides {a.get('side_gap_ratio', '—')}"
                        if a.get("kind") == "spacing"
                        else a.get("detected_location", "")
                    ),
                    automated_result=a.get("automated_result", "review"),
                    evidence_sufficient=True,
                    manual_review_required=a.get("automated_result") != "pass",
                ))
    db.flush()

    # 4. Evidence rows (one per image + one linked per finding)
    #    seed_image_evidence=False is used by the incremental cross-check re-run,
    #    where the per-image source evidence already exists.
    seq_e = 0
    if seed_image_evidence:
        for img in inspection.images:
            seq_e += 1
            db.add(models.Evidence(
                evidence_id=f"EVD-{seq_e:03d}", inspection_id=inspection.id,
                evidence_type="source_image", source_image_id=img.image_id,
                description=f"{img.side.title()} package image", status="available",
                captured_by=inspection.inspector.username, sort_order=seq_e,
                integrity_hash=img.file_hash or "",
            ))
    for p in persisted:
        finding = finding_by_key.get((p.rule_id, p.type, p.field))
        if not finding:
            continue
        seq_e += 1
        db.add(models.Evidence(
            evidence_id=f"EVD-{seq_e:03d}", inspection_id=inspection.id,
            evidence_type="ocr_region" if finding.ocr_region_id else "source_image",
            source_image_id=finding.source_image_id, region_id=finding.ocr_region_id,
            finding_id=finding.finding_id,
            rule_id=f"{finding.rule_number} {finding.sub_rule}".strip(),
            field_name=finding.source_field,
            description=f"Supporting evidence for {finding.finding_id} — {finding.requirement[:90]}",
            status="linked", captured_by=inspection.inspector.username, sort_order=seq_e,
        ))
    db.commit()
    return {"findings": seq, "evidence": seq_e}


def _pick_source_image(ctx: EvalContext, field_name: str | None,
                       images: dict[int, models.InspectionImage]) -> dict:
    if field_name:
        row = _best_row(ctx, field_name)
        if row and row.image_id:
            img = images.get(row.image_id)
            if img:
                return {"image_id": img.image_id, "region_id": row.region_id or ""}
    ordered = sorted(ctx.inspection.images, key=lambda i: (0 if i.side == "back" else (1 if i.side == "front" else 2), i.id))
    if ordered:
        return {"image_id": ordered[0].image_id, "region_id": ""}
    return {"image_id": None, "region_id": ""}


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def _lock_inspection(db: Session, inspection: models.Inspection) -> None:
    """Serialize concurrent analysis runs for the same inspection.

    Two simultaneous POST /analysis/run requests must never interleave
    (delete-then-insert): both would pass the delete step before either
    inserts, doubling every rule_result/finding/evidence row. Taking a row
    lock on the inspection makes the second transaction wait until the first
    has committed, after which its own delete+insert produces a clean set.
    (FOR UPDATE is a no-op on SQLite, which serializes writes anyway.)
    """
    db.query(models.Inspection).filter(
        models.Inspection.id == inspection.id).with_for_update().first()


def _dedupe_rows(rows: list[ResultRow]) -> list[ResultRow]:
    """Defensive: never persist two identical result rows in one run."""
    seen: set[tuple] = set()
    out: list[ResultRow] = []
    for r in rows:
        key = (r.rule_id, r.type, r.field, r.result, r.sort, r.input_value)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def run_rule_analysis(db: Session, inspection: models.Inspection) -> dict:
    # Serialize concurrent runs (double-fire protection), then purge children
    # in FK-safe order: Evidence (references Finding) -> FontAnalysis/PlacementAnalysis
    # (reference Finding) -> Finding (references RuleResult) -> RuleResult (parent).
    _lock_inspection(db, inspection)
    db.query(models.Evidence).filter(models.Evidence.inspection_id == inspection.id).delete()
    db.query(models.FontAnalysis).filter(models.FontAnalysis.inspection_id == inspection.id).delete()
    db.query(models.PlacementAnalysis).filter(models.PlacementAnalysis.inspection_id == inspection.id).delete()
    db.query(models.Finding).filter(models.Finding.inspection_id == inspection.id).delete()
    db.query(models.RuleResult).filter(models.RuleResult.inspection_id == inspection.id).delete()
    db.flush()

    # Only draft inspections enter the analysis pipeline here; inspections that
    # have already progressed (pending_review / finalized) keep their status.
    if inspection.status == INSP_STATUS_DRAFT:
        inspection.status = INSP_STATUS_UNDER_ANALYSIS
    ctx = build_context(db, inspection)
    rules = select_rules(db, inspection)

    rows: list[ResultRow] = []
    sort = 0
    applicable_count = 0
    skipped = 0
    for rule in rules:
        if rule.type == "cross":
            continue  # handled below in the dedicated cross-check loop
        sort += 1
        ok, reason = applicable(ctx, rule)
        if not ok:
            skipped += 1
            continue  # not applicable rows are never persisted
        applicable_count += 1
        rows.extend(evaluate_rule(ctx, rule, sort))
    # cross-field / cross-source checks last (they consume the same product facts)
    for rule in rules:
        if rule.type == "cross":
            sort += 1
            ok, reason = applicable(ctx, rule)
            if not ok:
                skipped += 1
                continue
            applicable_count += 1
            cross_result_rows = _cross_rows(ctx, rule, sort)
            if cross_result_rows:
                rows.extend(cross_result_rows)
            else:
                # A4.6: Cross rules that produce no result (nothing to compare)
                # must still emit a row so Rules Selected == stat-card sum.
                rows.append(_mk(
                    rule, RES_MANUAL_REVIEW,
                    "No comparable data", rule.requirement,
                    "No cross-comparable data available for this inspection — "
                    "no online listing was entered, or only one panel was captured. "
                    "Inspector must verify this requirement from the physical package.",
                    0.0,
                    observed={"engine_action": "no_comparable_data"},
                    expected_obj={"cross_check_required": True},
                    reason="Cross-check skipped: no comparable data source available for this inspection.",
                    sort=sort,
                ))

    rows = _dedupe_rows(rows)
    _materialise(db, ctx, rows)

    inspection.rule_set_snapshot = {
        "base_regulation": RULE_BASE_TEXT,
        "rule_set_version": "Current consolidated rule set (seeded)",
        "effective_date": str(_inspection_date(inspection)),
        "applicable_amendments": [
            {"name": a["name"], "effective_from": str(a["effective_from"])}
            for a in AMENDMENT_MAP if a["effective_from"] <= _inspection_date(inspection)
        ],
        "engine_version": ENGINE_VERSION,
        "rules_selected": len(rules),
        "rules_skipped_not_applicable": skipped,
        "coverage_note": ctx.coverage_note,
    }

    persisted = db.query(models.RuleResult).filter(
        models.RuleResult.inspection_id == inspection.id).all()
    counts = aggregate_counts(persisted)
    if counts["non_compliant"] > 0:
        inspection.automated_result = AUTO_NON_COMPLIANT
    elif counts["potential_non_compliance"] > 0:
        inspection.automated_result = POTENTIAL_NON_COMPLIANCE
    elif counts["manual_review"] > 0:
        inspection.automated_result = AUTO_REVIEW_REQUIRED
    elif counts["compliant"] > 0:
        inspection.automated_result = AUTO_COMPLIANT
    else:
        inspection.automated_result = AUTO_INCONCLUSIVE  # None: no verdict produced
    # Advance the workflow status, but never regress an inspection that has
    # already moved into the review pipeline (pending_review / finalized) —
    # re-running the engine there must not kick it back to analysis_complete.
    if inspection.status in (INSP_STATUS_UNDER_ANALYSIS, INSP_STATUS_DRAFT):
        inspection.status = INSP_STATUS_ANALYSIS_COMPLETE
    db.commit()

    return {
        "status": "complete",
        "automated_result": inspection.automated_result,
        "inspection_status": inspection.status,
        "rules_selected": len(rules),
        "applicable_rules": applicable_count,
        "rules_skipped_not_applicable": skipped,
        "counts": counts,
        "coverage_adequate": ctx.coverage_adequate,
        "coverage_note": ctx.coverage_note,
        "findings_count": _materialise_findings_count(db, inspection),
    }


def run_cross_checks(db: Session, inspection: models.Inspection) -> dict:
    """Re-run only the cross-field / cross-source checks (used when the inspector
    enters or updates an online listing value). Other rule results are untouched."""
    _lock_inspection(db, inspection)
    ctx = build_context(db, inspection)
    rows: list[ResultRow] = []
    sort = 9990
    for rule in select_rules(db, inspection):
        if rule.type == "cross":
            rows.extend(_cross_rows(ctx, rule, sort))
            sort += 1
    # Replace existing cross rows for this inspection. Cross rows can have
    # findings + analysis rows + linked evidence referencing them, so those are
    # removed first (foreign-key safe) before the new cross rows are persisted.
    existing = db.query(models.RuleResult).filter(
        models.RuleResult.inspection_id == inspection.id,
        models.RuleResult.type == "cross").all()
    existing_ids = [e.id for e in existing]
    old_findings = db.query(models.Finding).filter(
        models.Finding.rule_result_id.in_(existing_ids)).all() if existing_ids else []
    old_finding_ids = [f.id for f in old_findings]
    old_finding_pub = [f.finding_id for f in old_findings]
    if old_finding_pub:
        db.query(models.Evidence).filter(
            models.Evidence.finding_id.in_(old_finding_pub)).delete(synchronize_session=False)
    if old_finding_ids:
        db.query(models.FontAnalysis).filter(
            models.FontAnalysis.finding_id.in_(old_finding_ids)).delete(synchronize_session=False)
        db.query(models.PlacementAnalysis).filter(
            models.PlacementAnalysis.finding_id.in_(old_finding_ids)).delete(synchronize_session=False)
    for f in old_findings:
        db.delete(f)
    for e in existing:
        db.delete(e)
    db.flush()
    _materialise(db, ctx, _dedupe_rows(rows), seed_image_evidence=False)
    persisted = db.query(models.RuleResult).filter(
        models.RuleResult.inspection_id == inspection.id).all()
    counts = aggregate_counts(persisted)
    if counts["non_compliant"] > 0:
        inspection.automated_result = AUTO_NON_COMPLIANT
    elif counts["potential_non_compliance"] > 0:
        inspection.automated_result = POTENTIAL_NON_COMPLIANCE
    elif counts["manual_review"] > 0:
        inspection.automated_result = AUTO_REVIEW_REQUIRED
    elif counts["compliant"] > 0:
        inspection.automated_result = AUTO_COMPLIANT
    db.commit()
    return {"counts": counts, "automated_result": inspection.automated_result}


def _materialise_findings_count(db: Session, inspection: models.Inspection) -> int:
    return db.query(models.Finding).filter(models.Finding.inspection_id == inspection.id).count()


def _inspection_date(inspection: models.Inspection) -> dt.date:
    return inspection.inspection_date.date() if isinstance(inspection.inspection_date, dt.datetime) else inspection.inspection_date


def aggregate_counts(persisted: list[models.RuleResult]) -> dict:
    """Bug 1 fix: count distinct rule_ids for rules_checked, not raw row count.
    Font rules expand to 3 rows each (one per field); we count unique rules, not rows.
    """
    evaluated = [p for p in persisted if p.result != RES_NOT_APPLICABLE]
    # Use distinct rule_id for the per-rule count (font rules produce multiple rows per rule)
    distinct_rule_ids = set(p.rule_id for p in evaluated)
    compliant = len(set(p.rule_id for p in evaluated if p.result == COMPLIANT))
    non_compliant = len(set(p.rule_id for p in evaluated if p.result == NON_COMPLIANT))
    # A rule is manual_review only if it has no COMPLIANT or NON_COMPLIANT row
    rule_worst: dict[int, str] = {}
    for p in evaluated:
        prev = rule_worst.get(p.rule_id)
        # Priority: NON_COMPLIANT > POTENTIAL_NON_COMPLIANCE > MANUAL_REVIEW > COMPLIANT
        _rank = {NON_COMPLIANT: 4, POTENTIAL_NON_COMPLIANCE: 3, MANUAL_REVIEW: 2, COMPLIANT: 1}
        if prev is None or _rank.get(p.result, 0) > _rank.get(prev, 0):
            rule_worst[p.rule_id] = p.result
    manual_review = sum(1 for v in rule_worst.values() if v == MANUAL_REVIEW)
    potential = sum(1 for v in rule_worst.values() if v == POTENTIAL_NON_COMPLIANCE)
    compliant = sum(1 for v in rule_worst.values() if v == COMPLIANT)
    non_compliant = sum(1 for v in rule_worst.values() if v == NON_COMPLIANT)
    n_rules = len(distinct_rule_ids)
    return {
        "rules_checked": n_rules,   # unique rules evaluated (matches header "Rules Applicable")
        "compliant": compliant,
        "non_compliant": non_compliant,
        "manual_review": manual_review,
        "potential_non_compliance": potential,
        # legacy aliases kept so older consumers degrade gracefully
        "evaluated": n_rules,
        "passed": compliant,
        "failed": non_compliant,
        "review": manual_review,
        "not_applicable": 0,
        "total": len(persisted),
    }


def inspection_counts(db: Session, inspection: models.Inspection) -> dict:
    persisted = db.query(models.RuleResult).filter(
        models.RuleResult.inspection_id == inspection.id).all()
    return aggregate_counts(persisted)


def aggregate_counts_with_overrides(
    db: Session, inspection_id: int, persisted: list[models.RuleResult]
) -> dict:
    """Inspector-aware compliance count.

    ``aggregate_counts`` counts the *automated* rule_results.result values.
    That function must stay unchanged because the rule engine calls it during
    analysis runs before any findings exist.

    This function layers inspector decisions on top:

    * For each RuleResult that has a linked Finding with a non-pending
      inspector decision, the *effective* status is recomputed:

        inspector_result == "satisfied"     → COMPLIANT
        inspector_result == "not_satisfied" → NON_COMPLIANT
        inspector_result == "inconclusive"  → leave result unchanged (still needs follow-up)

    * RuleResult rows without a finding, or whose finding is still "pending",
      are counted with their original automated result.

    The returned dict has exactly the same keys as aggregate_counts so all
    callers are drop-in replaceable.
    """
    # Build a lookup: rule_result_id -> inspector_result (only non-pending)
    findings: list[models.Finding] = (
        db.query(models.Finding)
        .filter(
            models.Finding.inspection_id == inspection_id,
            models.Finding.inspector_status != "pending",
        )
        .all()
    )
    override_by_rr: dict[int, str] = {}
    for f in findings:
        if f.rule_result_id is not None and f.inspector_result in (
            "satisfied", "not_satisfied", "inconclusive"
        ):
            override_by_rr[f.rule_result_id] = f.inspector_result

    _rank = {NON_COMPLIANT: 4, POTENTIAL_NON_COMPLIANCE: 3, MANUAL_REVIEW: 2, COMPLIANT: 1}

    evaluated = [p for p in persisted if p.result != RES_NOT_APPLICABLE]
    distinct_rule_ids = set(p.rule_id for p in evaluated)

    # Determine the *effective* worst result per rule_id, factoring in overrides.
    rule_worst_effective: dict[int, str] = {}
    for p in evaluated:
        # Compute effective status for this single RuleResult row
        inspector_result = override_by_rr.get(p.id)
        if inspector_result == "satisfied":
            effective = COMPLIANT
        elif inspector_result == "not_satisfied":
            effective = NON_COMPLIANT
        else:
            # "inconclusive" or no override → keep automated result
            effective = p.result

        prev = rule_worst_effective.get(p.rule_id)
        if prev is None or _rank.get(effective, 0) > _rank.get(prev, 0):
            rule_worst_effective[p.rule_id] = effective

    compliant = sum(1 for v in rule_worst_effective.values() if v == COMPLIANT)
    non_compliant = sum(1 for v in rule_worst_effective.values() if v == NON_COMPLIANT)
    manual_review = sum(1 for v in rule_worst_effective.values() if v == MANUAL_REVIEW)
    potential = sum(1 for v in rule_worst_effective.values() if v == POTENTIAL_NON_COMPLIANCE)
    n_rules = len(distinct_rule_ids)

    return {
        "rules_checked": n_rules,
        "compliant": compliant,
        "non_compliant": non_compliant,
        "manual_review": manual_review,
        "potential_non_compliance": potential,
        # legacy aliases
        "evaluated": n_rules,
        "passed": compliant,
        "failed": non_compliant,
        "review": manual_review,
        "not_applicable": 0,
        "total": len(persisted),
    }