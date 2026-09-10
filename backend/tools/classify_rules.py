"""A1/A2 — Classify and map the 230-record register onto the engine schema.

Reads backend/data/register_records.json (A0 output) and produces:

  * backend/data/register_classified.json — every record with:
      bucket        : image_checkable | legal_reference | manual_review
      bucket_reason : why that bucket
      kind          : the engine validation.kind it maps to (bucket 1)
      kind_reason   : rationale for the mapping
      needs_review  : reasons when register data is ambiguous/incomplete

  * backend/data/register_classification_report.txt — human-readable summary.

Bucket semantics (register-faithful — rule `type` is the statutory *character*
of the provision; `validation.type` is the *engine check* character):

  image_checkable  — provisions that produce a per-inspection pass/fail against
                     package photo / OCR / cross-comparison data.
                     rule.type ∈ {compliance, conditional, prohibition,
                     calculation} with a concrete validation.type, or an
                     exemption/definition that itself demands a package check.
  legal_reference  — definition / procedure / exemption rows and rows whose
                     validation is `not_applicable`: stored for citation and the
                     Rules & Standards page; NOT fed to select_rules.
  manual_review    — validation.type = manual_review (or procedure_record
                     parameters): by design always evaluates to MANUAL_REVIEW
                     when applicable; never auto-passed.

Kind mapping (register validation.type -> engine validation.kind):
  presence                   -> any_present   (fields from text_targets)
  unit                       -> unit_known    (net-quantity standard unit)
  format / unit, format      -> date_month_year when the target is a date;
                                format_mrp / text_contains when MRP wording;
                                else needs_review (no machine pattern given)
  calculation                -> range (numeric) or needs_review (prose/table)
  font_size                  -> rule.type=font (Table-I mm bands preserved)
  cross_field                -> rule.type=cross  kind=cross_consistency
  cross_source               -> rule.type=cross  kind=cross_source
  cross_source / cross_field -> rule.type=cross  kind=cross_consistency
  prohibition                -> kind=prohibition (register trigger kept)
  conditional                -> resolved to the underlying presence check
                                using the record's own text_targets/fields;
                                the trigger stays in rule.conditions
  manual_review              -> kind=always_manual (bucket 3)
  not_applicable             -> legal-reference (never evaluated)

The tool never invents a threshold/pattern: where a record's parameter block
has no directly usable numeric bound / pattern / field token, the record is
flagged needs_review with the specific gap (import excludes those rows from
the evaluation loop until resolved).

Usage:  python tools/classify_rules.py
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "register_records.json"
OUT_JSON = ROOT / "data" / "register_classified.json"
OUT_TXT = ROOT / "data" / "register_classification_report.txt"

# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------
_FIELD_HINTS = {
    "manufacturer_or_importer_or_packer_identity": "manufacturer_name",
    "identity_address_country_origin_if_imported": "manufacturer_name",
    "manufacturer_name": "manufacturer_name",
    "manufacturer_address": "manufacturer_address",
    "packer_name": "packer_name",
    "packer_address_if_applicable": "manufacturer_address",
    "importer_name": "importer_name",
    "importer_address_if_imported": "manufacturer_address",
    "commodity_identity": "product_name",
    "common_or_generic_name_of_commodity": "product_name",
    "readable_product_name": "product_name",
    "product_specific_required_matter": "product_name",
    "net_quantity_value_and_unit": "net_quantity",
    "quantity_declaration": "net_quantity",
    "count_or_wholesale_net_quantity": "net_quantity",
    "month_and_year": "date_of_packing",
    "month_year_information": "date_of_packing",
    "mandatory_Rule_6(1)_declarations_except_month_year_where_rule_excludes_it": "date_of_packing",
    "best_before_or_use_by_date_month_year": "best_before",
    "MRP_amount": "mrp_value",
    "retail_sale_price": "mrp_value",
    "MRP_inclusive_all_taxes": "mrp_value",
    "exact_MRP_declaration_on_label": "mrp_value",
    "inclusive_of_all_taxes_statement": "inclusive_taxes_phrase",
    "country_of_origin": "country_of_origin",
    "country_of_origin_or_manufacture_or_assembly": "country_of_origin",
    "country_statement": "country_of_origin",
    "consumer_care_block": "consumer_care_number",
    "consumer_care_email_phone": "consumer_email",
    "consumer_care_number": "consumer_care_number",
    "contact_person_or_office_name": "consumer_care_number",
    "address_related_information": "manufacturer_address",
    "dimensions_when_relevant": "dimensions",
    "dimension_declaration": "dimensions",
    "dimensions": "dimensions",
    "component_count": "items_count",
    "on_pack_or_QR_information": "product_name",
    "visible_label_text": "product_name",
    "package_photo": "product_name",
}


def _split(s) -> list[str]:
    if s is None:
        return []
    return [t.strip() for t in re.split(r"[;,]", str(s)) if t.strip()]


def _tokens(params: dict) -> list[str]:
    out: list[str] = []
    for k in ("text_targets", "required", "text_target", "fields", "field", "inputs"):
        if params.get(k):
            out += _split(params[k])
    return out


def _hint_fields(params: dict) -> list[str]:
    seen: list[str] = []
    for tok in _tokens(params):
        hit = _FIELD_HINTS.get(tok)
        if hit and hit not in seen:
            seen.append(hit)
    return seen


def _tail(v) -> str:
    return "" if v is None else str(v)


# Register validation.type values that carry an explicit package check.
CHECK_VTYPES = {"presence", "format", "format / unit", "unit", "calculation",
                "font_size", "legibility", "cross_field", "cross_source",
                "cross_source / cross_field", "prohibition"}
# Register rule.type values that are by-nature evaluable obligations.
EVAL_RULE_TYPES = {"compliance", "conditional", "prohibition", "calculation"}


def classify(rec: dict) -> dict:
    rid = rec["rule_id"]
    rtype = rec.get("type") or ""
    v = rec.get("validation") or {}
    vtype = v.get("type") or ""
    params = v.get("parameters") or {}
    review: list[str] = []

    # ---------- Bucket 2: legal-reference-only ----------
    if vtype == "not_applicable":
        return {"bucket": "legal_reference",
                "bucket_reason": "register validation.type=not_applicable — "
                                 "definitional/administrative; never a pass/fail.",
                "kind": None, "kind_reason": "not evaluated per-inspection",
                "needs_review": review}
    if rtype in ("definition", "procedure"):
        return {"bucket": "legal_reference",
                "bucket_reason": f"rule.type={rtype} — citation/audit record "
                                 "for the Rules & Standards reference page.",
                "kind": None, "kind_reason": "not evaluated per-inspection",
                "needs_review": review}
    # Registration / licensing administration (Rules 27-30): the duty runs on
    # the *registration process*, not on a retail package being inspected.
    if rec.get("category") == "registration" or rec.get("rule_number") in ("27", "28", "29", "30"):
        return {"bucket": "legal_reference",
                "bucket_reason": f"registration administration (Rule "
                                 f"{rec.get('rule_number')}) — applies to the "
                                 "registration process/records, not to a package "
                                 "under inspection.",
                "kind": None, "kind_reason": "not evaluated per-inspection",
                "needs_review": review}

    # ---------- Bucket 3: manual review by design ----------
    if vtype == "manual_review" or (params or {}).get("procedure_record"):
        return {"bucket": "manual_review",
                "bucket_reason": "register validation.type=manual_review — "
                                 "by design always MANUAL_REVIEW when applicable.",
                "kind": "always_manual", "kind_reason": "by-design manual review",
                "needs_review": review}

    # ---------- Exemptions: applicability-scope records ----------
    if rtype == "exemption":
        if vtype in ("conditional", "cross_source", "format", "unit", "presence"):
            return {"bucket": "legal_reference",
                    "bucket_reason": f"rule.type=exemption ({vtype}) — the "
                                     "provision removes/gates the duty; stored "
                                     "as applicability reference.",
                    "kind": None,
                    "kind_reason": "consumed by applicable()/conditions, not a "
                                   "standalone pass/fail",
                    "needs_review": review}
        return {"bucket": "legal_reference",
                "bucket_reason": f"rule.type=exemption ({vtype})",
                "kind": None, "kind_reason": "exemption reference",
                "needs_review": review}

    # ---------- Bucket 1: image-checkable obligations ----------
    if rtype in EVAL_RULE_TYPES:
        return {"bucket": "image_checkable",
                "bucket_reason": f"rule.type={rtype} — package-verifiable "
                                 "obligation (validation.type="
                                 f"{vtype}).", "kind": None,
                "kind_reason": "mapped below", "needs_review": review}

    return {"bucket": "needs_review",
            "bucket_reason": f"unclassified rule.type={rtype} / "
                             f"validation.type={vtype}",
            "kind": None, "kind_reason": "",
            "needs_review": [f"unclassified: {rtype}/{vtype}"]}


# ---------------------------------------------------------------------------
# A2 kind mapping
# ---------------------------------------------------------------------------
def _resolve_conditional(rec: dict, fields: list[str]) -> tuple[str, list[str]]:
    """Resolve a conditional validation to its underlying presence/date check.

    Conditional provisions make an *additional/alternative* declaration
    obligatory once their trigger is true (e.g. 'best before/use by when the
    package claims a shelf life').  The underlying check is the presence of the
    record's own declared target; the trigger is preserved for rule.conditions.
    """
    params = (rec.get("validation") or {}).get("parameters") or {}
    tt = " ".join(_split(params.get("text_targets"))).lower().replace("_", " ")
    if any(t in tt for t in ("month", "year", "best before", "use by", "date")):
        return "date_month_year", []
    return "any_present", []


def map_kind(rec: dict) -> dict | None:
    """Return {kind, ...} plus needs_review[], or None for non-image records."""
    if classify(rec)["bucket"] != "image_checkable":
        return None
    v = rec.get("validation") or {}
    vtype = v.get("type") or ""
    vsub = v.get("validation_subtype") or ""
    params = v.get("parameters") or {}
    review: list[str] = []
    fields = _hint_fields(params)
    # requirement.field is an authoritative fallback when text_targets carry
    # no known engine token.
    req_field = (rec.get("requirement") or {}).get("field")
    if req_field and req_field not in fields and req_field in set(_FIELD_HINTS.values()):
        fields.append(req_field)
    text_toks = _split(params.get("text_targets"))
    tt_lower = " ".join(text_toks).lower().replace("_", " ")

    # --- prohibition ------------------------------------------------------
    if rec.get("type") == "prohibition" or vtype == "prohibition":
        return {"kind": "prohibition",
                "trigger": _tail(params.get("trigger")),
                "prohibition": _tail(params.get("prohibition")),
                "fields": fields, "needs_review": review}

    # --- presence ---------------------------------------------------------
    if vtype == "presence":
        if not fields:
            review.append("presence targets carry no engine field token ("
                          + _tail(params.get("image_targets"))
                          + ") — cannot bind to an extracted field.")
        return {"kind": "any_present", "fields": fields or [],
                "needs_review": review}

    # --- unit -------------------------------------------------------------
    if vtype == "unit":
        return {"kind": "unit_known", "fields": fields, "needs_review": review}

    # --- date -------------------------------------------------------------
    if vtype in ("format / unit", "format", "legibility") and any(
            t in tt_lower for t in ("month", "year", "date", "best before")):
        return {"kind": "date_month_year",
                "field": fields[0] if fields else "date_of_packing",
                "needs_review": review}

    # --- MRP wording / pattern -------------------------------------------
    if vtype in ("format / unit", "format"):
        if any("mrp" in t.lower() or "retail sale price" in t.lower()
               for t in text_toks):
            pat = params.get("allowed_illustration_patterns")
            pat_flat = " ".join(_split(pat)).lower().replace("_", " ")
            if pat and "inclusive of all taxes" in pat_flat:
                return {"kind": "text_contains", "pattern": "inclusive of all taxes",
                        "field": fields[0] if fields else "mrp_value",
                        "needs_review": review}
            review.append("MRP wording rule's illustration text has no explicit "
                          "machine-checkable pattern.")
            return {"kind": "format_mrp", "needs_review": review}
        if params.get("language_requirement"):
            return {"kind": "text_contains", "pattern": "",
                    "field": fields[0] if fields else "product_name",
                    "needs_review": ["language-format rule needs an explicit pattern."]}
        if rec.get("rule_number") in ("17",) and params.get("container_type"):
            return {"kind": "any_present", "fields": fields or ["product_name"],
                    "needs_review": ["container-format rule needs an explicit "
                                     "geometric check."]}
        review.append("format rule (text_targets=" + _tail(params.get(
            "text_targets")) + ") has no explicit pattern/accepted-forms enum "
            "usable by the engine.")
        return {"kind": "text_contains", "pattern": "", "needs_review": review}

    # --- legibility / prominence -------------------------------------------
    if vtype == "legibility":
        review.append("legibility/prominence is an image-quality judgement; the "
                      "register provides no numeric threshold.")
        return {"kind": "always_manual", "needs_review": review}

    # --- calculation --------------------------------------------------------
    if vtype == "calculation":
        review.append("calculation rule is a derived-quantity / table-threshold "
                      "computation needing measured or sample inputs, not a "
                      "single-field range check.")
        return {"kind": "range", "min": None, "max": None, "needs_review": review}

    # --- font_size ----------------------------------------------------------
    if vtype == "font_size":
        return {"kind": "font", "type": "font",
                "table_i": {
                    "row_selection": _tail(params.get("row_selection")),
                    "normal_min_mm": _tail(params.get("normal_min_mm")),
                    "blown_formed_molded_min_mm": _tail(
                        params.get("blown_formed_molded_min_mm")),
                    "measurement_unit": _tail(params.get("measurement_unit")),
                    "area_unit": _tail(params.get("area_unit")),
                    "corrigendum": _tail(params.get("corrigendum")),
                    "ocr_only": _tail(params.get("OCR_only"))},
                "fields": fields or ["mrp_value", "net_quantity", "product_name"],
                "needs_review": review}

    # --- cross-field / cross-source -----------------------------------------
    if vtype in ("cross_field", "cross_source / cross_field", "cross_source"):
        if vtype == "cross_source" and params.get("external_source"):
            return {"kind": "cross_source", "type": "cross",
                    "subtype": "external_regulation_reference",
                    "external_source": _tail(params.get("external_source")),
                    "needs_review": review}
        if "cross_field" in vtype or vtype == "cross_source / cross_field":
            return {"kind": "cross_consistency", "type": "cross",
                    "needs_review": review}
        return {"kind": "cross_source", "type": "cross", "needs_review": review}

    # --- conditional (bucket-1 rows) ----------------------------------------
    if vtype == "conditional":
        kind, extra = _resolve_conditional(rec, fields)
        if kind == "date_month_year":
            return {"kind": "date_month_year",
                    "field": fields[0] if fields else "date_of_packing",
                    "trigger": _tail(params.get("trigger")),
                    "needs_review": review}
        if fields:
            return {"kind": "any_present", "fields": fields,
                    "trigger": _tail(params.get("trigger")),
                    "needs_review": review}
        review.append("conditional rule has no resolvable underlying check / "
                      "field token (trigger=" + _tail(params.get("trigger")) + ").")
        return {"kind": "needs_review", "needs_review": review}

    review.append(f"no mapping rule for validation.type={vtype!r}")
    return {"kind": "needs_review", "needs_review": review}


def main() -> None:
    recs = json.loads(SRC.read_text())
    out = []
    for rec in recs:
        entry = classify(rec)
        mapped = map_kind(rec)
        entry["seq"] = rec["_seq"]
        entry["rule_id"] = rec["rule_id"]
        entry["sub_rule"] = rec.get("sub_rule")
        entry["title"] = rec.get("title")
        entry["rule_type"] = rec.get("type")
        entry["validation_type"] = (rec.get("validation") or {}).get("type")
        entry["validation_subtype"] = (rec.get("validation") or {}).get("validation_subtype")
        if mapped:
            entry["kind"] = mapped.pop("kind")
            entry["kind_reason"] = "see mapping config"
            if mapped.get("needs_review"):
                entry["needs_review"] = mapped["needs_review"]
                mapped.pop("needs_review")
            entry["mapping"] = mapped
        out.append(entry)
    OUT_JSON.write_text(json.dumps(out, indent=1, ensure_ascii=False))

    lines: list[str] = []
    bucket_c = Counter(e["bucket"] for e in out)
    kind_c = Counter(e.get("kind") or "—" for e in out if e["bucket"] == "image_checkable")
    nr = [(e["seq"], e["rule_id"], (e.get("needs_review") or []))
          for e in out if e.get("needs_review")]
    lines.append("REGISTER CLASSIFICATION (230 records, A0 extraction)")
    lines.append("=" * 78)
    lines.append("Buckets (A1):")
    for b in ("image_checkable", "legal_reference", "manual_review", "needs_review"):
        lines.append(f"  {b:18s} {bucket_c.get(b, 0):3d}")
    lines.append("")
    lines.append("Mapped engine kinds (A2, image-checkable records):")
    for k, c in kind_c.most_common():
        lines.append(f"  {k:28s} {c}")
    lines.append("")
    lines.append(f"Records flagged needs_review: {len(nr)}")
    for seq, rid, reasons in nr:
        for r_ in reasons:
            lines.append(f"  [{seq}] {rid}: {r_}")
    OUT_TXT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
