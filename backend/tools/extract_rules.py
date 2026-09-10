#!/usr/bin/env python3
"""
Extract all 230 rule records from the Legal Metrology PDF and produce
a JSON file ready for seed.py to load.

Run from the project root:
  python backend/tools/extract_rules.py

Output: backend/data/rules_230.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PDF_PATH = ROOT / "Legal_Metrology_Packaged_Commodities_Rules_2011_to_2026_CORRECTED_FINAL.pdf"
OUT_PATH = ROOT / "backend" / "data" / "rules_230.json"


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------
def extract_text(pdf_path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            return "\n\f\n".join((p.extract_text() or "") for p in pdf.pages)
    except ImportError:
        sys.exit("pdfplumber not installed. Run: pip install pdfplumber")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _s(v: str) -> str:
    """Strip whitespace and surrounding quotes."""
    return v.strip().strip("'\"")


def _parse_date(v: str) -> str | None:
    v = _s(v)
    if re.match(r"\d{4}-\d{2}-\d{2}", v):
        return v
    return None


# ---------------------------------------------------------------------------
# Scope / engine type / validation kind mapping
# ---------------------------------------------------------------------------
# PDF rule-level `type` → engine `scope`
_SCOPE_MAP: dict[str, str] = {
    "compliance": "image_checkable",
    "presence": "image_checkable",
    "format": "image_checkable",
    "unit": "image_checkable",
    "calculation": "image_checkable",
    "cross_field": "image_checkable",
    "cross_source": "image_checkable",
    "prohibition": "image_checkable",
    "conditional": "image_checkable",
    "font_size": "image_checkable",
    "legibility": "manual_review",
    "manual_review": "manual_review",
    "procedure": "reference",
    "definition": "reference",
    "exemption": "reference",
    "not_applicable": "reference",
}

# PDF rule-level `type` → engine model `type`
_ENGINE_TYPE_MAP: dict[str, str] = {
    "compliance": "content",
    "presence": "content",
    "format": "format",
    "unit": "content",
    "calculation": "content",
    "cross_field": "cross",
    "cross_source": "cross",
    "prohibition": "content",
    "conditional": "content",
    "font_size": "font",
    "legibility": "font",
    "manual_review": "content",
    "procedure": "reference",
    "definition": "reference",
    "exemption": "reference",
    "not_applicable": "reference",
}

# PDF validation.type → engine validation.kind
def _map_validation_kind(
    rule_type: str,
    val_type: str,
    params: dict,
    rule_id: str,
) -> dict:
    """Return a validation dict with a `kind` the engine understands."""
    vt = val_type.strip().lower()

    # Scope=reference → no evaluation
    if _SCOPE_MAP.get(rule_type, "reference") == "reference":
        return {"kind": "reference"}

    # always_manual bucket (manual_review / legibility)
    if rule_type in ("manual_review", "legibility"):
        return {"kind": "always_manual"}

    # prohibition (rule type)
    if rule_type == "prohibition":
        return {
            "kind": "prohibition",
            "trigger": params.get("trigger", ""),
            "prohibition": params.get("prohibition", ""),
            "fields": [],  # no bindable fields without further detail
        }

    # font_size → font_rel_height with Table-I band data
    if rule_type == "font_size" or vt == "font_size":
        # Extract the mm band data from parameters
        normal_bands = []
        blown_bands = []
        for raw in (params.get("normal_min_mm", "") or "").split(";"):
            v = raw.strip()
            if v:
                try:
                    normal_bands.append(float(v))
                except ValueError:
                    pass
        for raw in (params.get("blown_formed_molded_min_mm", "") or "").split(";"):
            v = raw.strip()
            if v:
                try:
                    blown_bands.append(float(v))
                except ValueError:
                    pass
        return {
            "kind": "font_rel_height",
            "min_ratio": 0.020,  # default ratio; physical mm comparison requires calibration
            "fields": ["product_name", "net_quantity", "mrp_value", "manufacturer_name", "consumer_care_number"],
            "table_I_normal_mm": normal_bands or [1.0, 1.5, 2.5, 4.0, 6.0],
            "table_I_blown_mm": blown_bands or [2.0, 3.0, 4.0, 6.0, 6.0],
            "OCR_note": "cannot_establish_physical_mm — relative estimate only, no calibration reference",
        }

    # cross_field
    if rule_type == "cross_field" or "cross_field" in vt:
        return {"kind": "cross_consistency"}

    # cross_source with external law reference
    if rule_type == "cross_source" or "cross_source" in vt:
        ext = params.get("external_reference_current", "") or params.get("external_reference", "")
        if ext:
            return {
                "kind": "cross_source",
                "subtype": "external_regulation_reference",
                "external_source": ext,
            }
        return {"kind": "cross_source"}

    # conditional — map underlying check; keep condition in rule.conditions
    if rule_type == "conditional" or vt == "conditional":
        # Try to infer what the check is once the condition is satisfied
        inner = params.get("check_if_applicable", "") or params.get("underlying_check", "")
        if "MRP" in inner or "mrp" in inner or "retail" in inner.lower():
            return {"kind": "present", "field": "mrp_value"}
        if "best_before" in inner or "use_by" in inner or "expiry" in inner.lower():
            return {"kind": "present", "field": "best_before"}
        if "net_quantity" in inner or "quantity" in inner.lower():
            return {"kind": "present", "field": "net_quantity"}
        if "date" in inner.lower():
            return {"kind": "date_month_year", "field": "date_of_packing"}
        if "QR" in inner or "qr_code" in inner.lower():
            return {"kind": "always_manual"}
        # Generic presence check for unresolved conditionals
        return {"kind": "present", "field": ""}

    # format/unit with MRP wording patterns
    if "format" in vt and ("mrp" in vt or "unit" in vt or "pattern" in vt):
        patterns = params.get("allowed_illustration_patterns", "") or ""
        # Rule 6(1)(e) MRP tax-inclusive wording
        if "inclusive_of_all_taxes" in patterns.lower() or "inclusive" in patterns.lower():
            return {
                "kind": "text_contains",
                "pattern": "inclusive of all taxes",
                "field": "inclusive_taxes_phrase",
            }
        return {"kind": "format_mrp"}

    # presence
    if vt == "presence":
        # Try to infer the field from text_targets
        targets = params.get("text_targets", "") or params.get("field_targets", "") or ""
        field = _infer_field(targets)
        if params.get("alternatives") or "," in targets:
            fields = _infer_fields(targets)
            return {"kind": "any_present", "fields": fields or [field]} if fields else {"kind": "present", "field": field}
        return {"kind": "present", "field": field}

    # unit
    if vt == "unit":
        return {"kind": "unit_known"}

    # calculation with numeric bounds
    if vt == "calculation":
        min_v = params.get("min") or params.get("lower_bound") or params.get("threshold_min")
        max_v = params.get("max") or params.get("upper_bound") or params.get("threshold_max")
        field = params.get("field") or params.get("measured_field") or "net_quantity"
        if min_v is not None or max_v is not None:
            result = {"kind": "range", "field": _infer_field(field)}
            try:
                if min_v is not None:
                    result["min"] = float(str(min_v).replace(",", ""))
            except ValueError:
                result["needs_review"] = f"threshold min not numeric: {min_v}"
            try:
                if max_v is not None:
                    result["max"] = float(str(max_v).replace(",", ""))
            except ValueError:
                result["needs_review"] = f"threshold max not numeric: {max_v}"
            return result
        return {"kind": "needs_review", "reason": "calculation rule with no extractable numeric bounds"}

    # legibility (font readability, no calibration)
    if vt == "legibility":
        return {"kind": "always_manual"}

    # fallback: presence check on inferred field
    targets = params.get("text_targets", "") or params.get("field_targets", "") or ""
    field = _infer_field(targets)
    return {"kind": "present", "field": field}


_FIELD_KEYWORDS: list[tuple[str, str]] = [
    ("mrp", "mrp_value"),
    ("retail_price", "mrp_value"),
    ("retail price", "mrp_value"),
    ("maximum retail", "mrp_value"),
    ("net_quantity", "net_quantity"),
    ("net quantity", "net_quantity"),
    ("net_weight", "net_quantity"),
    ("manufacturer", "manufacturer_name"),
    ("packer", "packer_name"),
    ("importer", "importer_name"),
    ("address", "manufacturer_address"),
    ("country_of_origin", "country_of_origin"),
    ("country of origin", "country_of_origin"),
    ("date_of_packing", "date_of_packing"),
    ("month.*year", "date_of_packing"),
    ("packing.*date", "date_of_packing"),
    ("manufacture.*date", "date_of_packing"),
    ("best_before", "best_before"),
    ("best before", "best_before"),
    ("use_by", "best_before"),
    ("consumer_care", "consumer_care_number"),
    ("consumer care", "consumer_care_number"),
    ("product_name", "product_name"),
    ("name.*commodity", "product_name"),
    ("commodity.*name", "product_name"),
    ("inclusive.*tax", "inclusive_taxes_phrase"),
    ("qr", "qr_code"),
    ("barcode", "barcode"),
    ("batch", "batch_number"),
    ("lot", "batch_number"),
]


def _infer_field(text: str) -> str:
    t = text.lower()
    for kw, field in _FIELD_KEYWORDS:
        if re.search(kw, t):
            return field
    return ""


def _infer_fields(text: str) -> list[str]:
    t = text.lower()
    seen: list[str] = []
    for kw, field in _FIELD_KEYWORDS:
        if re.search(kw, t) and field not in seen:
            seen.append(field)
    return seen


# ---------------------------------------------------------------------------
# Condition mapping
# ---------------------------------------------------------------------------
def _map_conditions(params: dict, description: str, sub_rule: str) -> dict | None:
    conds: dict = {}
    desc_lower = (description + " " + sub_rule).lower()

    if params.get("applies_to_imported") == "true" or "imported" in desc_lower and "domestic" not in desc_lower:
        conds["imported"] = True
    if "domestic" in desc_lower and "only" in desc_lower and "imported" not in desc_lower:
        conds["domestic_only"] = True

    # Shelf-life condition
    shelf_m = re.search(r"shelf.life.*?(\d+)\s*months?", desc_lower)
    if shelf_m:
        conds["shelf_life_months_le"] = int(shelf_m.group(1))

    # Min weight/quantity condition
    if "50\u00a0kg" in description or "50 kg" in description or "above 50 kg" in description.lower():
        conds["min_grams"] = 50000  # 50 kg
    elif "10 g" in description.lower() or "10g" in description.lower():
        conds["min_grams"] = 10

    # QR / electronic product
    if "electronic" in desc_lower and ("qr" in desc_lower or "serial" in desc_lower):
        conds["electronic_product"] = True

    # Medical device
    if "medical device" in desc_lower:
        conds["medical_device"] = True

    # Alcoholic / state excise
    if "alcohol" in desc_lower or "state excise" in desc_lower:
        conds["alcoholic_beverage"] = True

    return conds if conds else None


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------
def _map_severity(raw: str) -> str:
    r = raw.strip().upper()
    if r in ("HIGH", "CRITICAL"):
        return "critical"
    if r in ("MEDIUM",):
        return "major"
    if r in ("LOW", "INFO"):
        return "minor"
    return "major"


# ---------------------------------------------------------------------------
# Parser: split text into individual rule blocks
# ---------------------------------------------------------------------------
def parse_records(text: str) -> list[dict]:
    """Split the PDF text into one dict per record.

    Strategy: split on ``rule_id: LMPC-`` which appears exactly once per record
    and is unaffected by PDF page-breaks.  For each chunk, look backward for the
    numbered-header line to capture the title, and look forward to the next
    ``rule_id:`` to determine the chunk boundary.
    """
    # Find every occurrence of the rule_id line
    id_starts = [m.start() for m in re.finditer(r"\nrule_id:\s+LMPC-", text)]
    records: list[dict] = []
    for i, start in enumerate(id_starts):
        end = id_starts[i + 1] if i + 1 < len(id_starts) else len(text)
        # Grab some context before the rule_id line to capture the numbered header
        ctx_start = max(0, start - 600)
        block = text[ctx_start:end]
        rec = _parse_block(block.strip())
        if rec:
            records.append(rec)
    return records


def _extract_field(block: str, key: str) -> str:
    """Extract a single-line field value from a block."""
    m = re.search(rf"^{re.escape(key)}:\s*(.+)$", block, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _extract_multiline(block: str, key: str, stop_keys: list[str]) -> str:
    """Extract a potentially multi-line field value."""
    stop = "|".join(re.escape(k) for k in stop_keys)
    m = re.search(
        rf"^{re.escape(key)}:\s*(.*?)(?=\n(?:{stop}):|\Z)",
        block, re.DOTALL | re.MULTILINE,
    )
    if not m:
        return ""
    return " ".join(m.group(1).split()).strip()


def _extract_params(block: str) -> dict:
    """Extract the parameters block from a record's validation section."""
    params: dict = {}
    # Find the parameters: section
    m = re.search(r"parameters:\n(.*?)(?=\n(?:severity|evidence_required|effective_from|status|source):\s|\Z)",
                  block, re.DOTALL)
    if not m:
        return params
    param_text = m.group(1)
    for line in param_text.splitlines():
        line = line.strip()
        if ": " in line:
            k, _, v = line.partition(": ")
            params[k.strip()] = v.strip()
        elif line and not line.startswith("#"):
            # continuation of a multi-value param — append to last key
            if params:
                last_key = list(params)[-1]
                params[last_key] = params[last_key] + " " + line
    return params


def _parse_block(block: str) -> dict | None:
    rule_id = _s(_extract_field(block, "rule_id"))
    if not rule_id:
        return None

    rule_number = _s(_extract_field(block, "rule_number"))
    sub_rule = _s(_extract_field(block, "sub_rule"))
    title_raw = _s(_extract_field(block, "title"))
    if not title_raw:
        # Try to grab from the header line: "N. sub - Title"
        m = re.match(r"\d+\.\s+[\d()A-Za-z/.\-]+\s+-\s+(.+)", block.split("\n")[0])
        title_raw = m.group(1).strip() if m else ""
    title = title_raw

    rule_type = _s(_extract_field(block, "type"))
    category = _s(_extract_field(block, "category"))
    description = _extract_multiline(block, "description",
        ["applicability", "conditions", "validation", "severity", "evidence_required"])
    requirement = _extract_multiline(block, "requirement",
        ["description", "applicability", "conditions", "validation", "severity"])

    # validation block
    val_type_raw = ""
    val_subtype = ""
    vm = re.search(r"validation:\ntype: (.+?)$", block, re.MULTILINE)
    if vm:
        val_type_raw = vm.group(1).strip()
    vsm = re.search(r"validation_subtype: (.+?)$", block, re.MULTILINE)
    if vsm:
        val_subtype = vsm.group(1).strip()

    params = _extract_params(block)

    severity_raw = _s(_extract_field(block, "severity"))
    evidence_str = _s(_extract_field(block, "evidence_required"))
    evidence_required = evidence_str.lower() not in ("false", "no", "0")

    effective_from = _parse_date(_s(_extract_field(block, "effective_from"))) or "2011-04-01"
    effective_to_raw = _s(_extract_field(block, "effective_to"))
    effective_to = _parse_date(effective_to_raw)

    version_raw = _s(_extract_field(block, "version"))
    version_str = re.search(r"[\d]+", version_raw)
    version = int(version_str.group()) if version_str else 1

    status_raw = _s(_extract_field(block, "status"))
    status_map = {
        "active": "active", "historical": "historical", "superseded": "historical",
        "future": "future", "draft": "draft", "omitted": "omitted",
    }
    status = status_map.get(status_raw.lower(), "active")

    # Source
    doc = _s(_extract_field(block, "document"))
    prov = _s(_extract_field(block, "provision"))
    amendment = _s(_extract_field(block, "amendment"))
    source_parts = []
    if doc:
        source_parts.append(doc)
    if prov:
        source_parts.append(f"r.{prov}")
    if amendment:
        source_parts.append(amendment)
    source = ", ".join(source_parts) or rule_id

    # Scope + validation kind mapping
    scope = _SCOPE_MAP.get(rule_type, "reference")
    engine_type = _ENGINE_TYPE_MAP.get(rule_type, "reference")
    validation = _map_validation_kind(rule_type, val_type_raw, params, rule_id)
    if val_subtype:
        validation["validation_subtype"] = val_subtype

    # Conditions
    conditions = _map_conditions(params, description or requirement, sub_rule)

    # Applicability — default to all
    applicability = ["*"]
    comm_type = params.get("commodity_type", "") or ""
    if "medical_device" in comm_type.lower():
        applicability = ["medical_device"]
    elif "electronic" in comm_type.lower():
        applicability = ["electronic"]

    return {
        "rule_id": rule_id,
        "rule_number": rule_number,
        "sub_rule": sub_rule,
        "title": title,
        "type": engine_type,
        "scope": scope,
        "category": category or "mandatory_declaration",
        "requirement": requirement or description[:300] if description else "",
        "description": description or "",
        "field": validation.get("field") or None,
        "required": True,
        "applicability": applicability,
        "conditions": conditions,
        "validation": validation,
        "severity": _map_severity(severity_raw),
        "evidence_required": evidence_required,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "version": version,
        "source": source,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print(f"Reading PDF: {PDF_PATH}")
    text = extract_text(PDF_PATH)
    print(f"Extracted {len(text):,} characters from PDF")

    records = parse_records(text)
    print(f"Parsed {len(records)} records")

    # Validate rule_id uniqueness
    ids = [r["rule_id"] for r in records]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        print(f"WARNING: duplicate rule_ids: {dupes}")

    # Count by scope
    from collections import Counter
    scope_counts = Counter(r["scope"] for r in records)
    kind_counts = Counter(r["validation"].get("kind", "?") for r in records)
    print(f"Scope counts: {dict(scope_counts)}")
    print(f"Validation kind counts: {dict(kind_counts)}")

    # Show 3 example records as requested
    examples = {"compliance": None, "font_size": None, "prohibition": None}
    for r in records:
        orig_type = None
        # Find original type — use scope + engine type as proxy
        if r["type"] == "font" and examples["font_size"] is None:
            examples["font_size"] = r
        elif r["type"] == "content" and r["validation"].get("kind") == "prohibition" and examples["prohibition"] is None:
            examples["prohibition"] = r
        elif r["type"] == "content" and r["validation"].get("kind") in ("present", "any_present", "text_contains") and examples["compliance"] is None:
            examples["compliance"] = r

    print("\n=== EXAMPLE RECORDS ===")
    for label, ex in examples.items():
        if ex:
            print(f"\n--- {label} ---")
            print(json.dumps(ex, indent=2, default=str))

    if len(records) != 230:
        print(f"\n⚠ WARNING: expected 230 records, got {len(records)}. Check parsing.")
    else:
        print(f"\n✅ Confirmed: exactly 230 records extracted.")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(records, f, indent=2, default=str)
    print(f"\nSaved to: {OUT_PATH}")


if __name__ == "__main__":
    main()
