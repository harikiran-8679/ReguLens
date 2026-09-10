#!/usr/bin/env python3
"""
Step A2 v3 — Remove remaining category-specific always_manual noise + improve
coverage-insufficient behaviour in the engine.

Remaining always_manual rules in image_checkable scope that should be reference
because they either:
  a) Only apply to specific package types/sizes but have no condition, OR
  b) Are catch-all/optional provisions that generate no actionable finding
"""
from __future__ import annotations

import json
from pathlib import Path

JSON_PATH = Path(__file__).parent.parent / "data" / "rules_230.json"


# Rules that should move to reference — they generate MANUAL_REVIEW noise
# because they apply only to specific package types but have no condition set.
TO_REFERENCE: dict[str, str] = {
    # 6(1)(f) Dimensions — only required for textiles/containers/sheets (R14-R17).
    # For general food/consumer goods, not required. No engine-bindable field.
    "LMPC-R6-007": "Dimension declarations required only for specific commodity types (textiles, containers); not a universal food/FMCG label check.",

    # 6(4) Other sticker declarations — supplementary sticker content rule.
    # The LMPC rules only require a sticker if the manufacturer elects to use one.
    # Not universally applicable; generates noise for all non-sticker packages.
    "LMPC-R6-017": "Optional sticker content — only applies when manufacturer places a supplementary sticker; not a universal mandatory check.",

    # 6(4A) Optional barcode / QR / e-code — explicitly 'may also' in the rule;
    # not a mandatory declaration. Cannot generate NON_COMPLIANT; generating
    # MANUAL_REVIEW is misleading.
    "LMPC-R6-018": "Optional barcode/QR provision ('may also state') — not a mandatory declaration check.",

    # 6(5) Packages containing multiple components — only applies to multi-SKU
    # combination packs. Not applicable to standard single-commodity packages.
    "LMPC-R6-019": "Multi-component package provision — not applicable to standard single-commodity packages.",

    # 6(7) Other prescribed declaration provision — catch-all for commodity-specific
    # declarations mandated by other competent authorities (FSSAI, BIS, etc.).
    # The engine cannot know what other authority has prescribed for each product.
    "LMPC-R6-021": "Catch-all for commodity-specific declarations by other competent authorities; cannot be generalised across all product categories.",

    # 6(8) Specified consumer-product declarations — applies only to products under
    # BIS/FSSAI regulation. Needs product-category condition not currently wired.
    "LMPC-R6-022": "Applies to BIS/FSSAI regulated consumer products only; product-category condition not yet mapped; reference for now.",

    # 6(9) Additional declaration provision — another catch-all provision.
    # Catch-all provisions cannot produce actionable machine verdicts.
    "LMPC-R6-023": "Additional declaration catch-all provision; cannot produce an actionable machine verdict.",

    # 7(1) Small-capacity package display panel — only for packages ≤ 10 g / 10 ml.
    # No condition for package size; applying universally creates noise.
    "LMPC-R7-001": "Only applies to small-capacity packages (≤10 g/ml); package-size condition not mapped; reference for now.",

    # 7(4) PDP area determination sub-rules — require physical measurement in mm².
    # OCR cannot determine panel area without a calibration reference.
    "LMPC-R7-008": "Physical panel-area measurement required (mm²) — OCR cannot determine without calibration reference.",
    "LMPC-R7-009": "Rectangular package PDP area rule — calibration required; always_manual generates noise without actionable guidance.",
    "LMPC-R7-010": "Cylindrical package PDP area rule — calibration required.",
    "LMPC-R7-011": "Other-shaped package PDP area rule — calibration required.",

    # 8(2) Returnable beverage bottles — only applies to beverage bottles with
    # a returnable/deposit scheme. Not applicable to general packaged commodities.
    "LMPC-R8-002": "Returnable beverage bottle provision — only applicable to refillable deposit-scheme beverage containers.",

    # 18(2) No sale above MRP — dealer behavior check requiring a test purchase.
    # The label declares MRP; whether the dealer sells at or above it is not
    # determinable from the label alone. Already moved to always_manual in v1;
    # moving to reference avoids a spurious MANUAL_REVIEW prompt every inspection.
    "LMPC-R18-002": "Dealer-behavior rule (sale price vs MRP) — requires test purchase, not verifiable from label image.",
}


def _to_reference(rule: dict, note: str) -> None:
    rule["scope"] = "reference"
    rule["type"] = "reference"
    rule["validation"] = {"kind": "reference"}
    rule["_a2v3_note"] = note


def main() -> None:
    with open(JSON_PATH) as f:
        rules = json.load(f)

    idx = {r["rule_id"]: r for r in rules}

    before_ic = sum(1 for r in rules if r.get("scope") == "image_checkable")
    before_ref = sum(1 for r in rules if r.get("scope") == "reference")

    fixed = 0
    no_match = []
    for rid, note in TO_REFERENCE.items():
        r = idx.get(rid)
        if r:
            _to_reference(r, note)
            fixed += 1
        else:
            no_match.append(rid)

    after_ic = sum(1 for r in rules if r.get("scope") == "image_checkable")
    after_ref = sum(1 for r in rules if r.get("scope") == "reference")
    after_mr_scope = sum(1 for r in rules if r.get("scope") == "manual_review")

    print(f"Before: image_checkable={before_ic}, reference={before_ref}")
    print(f"After:  image_checkable={after_ic}, manual_review_scope={after_mr_scope}, reference={after_ref}")
    print(f"Fixed: {fixed}  |  No match: {no_match}")

    from collections import Counter
    active_ic = [r for r in rules if r.get("scope") == "image_checkable" and r.get("status") == "active"]
    kinds = Counter(r["validation"].get("kind", "?") for r in active_ic)
    always_m = sum(1 for r in active_ic if r["validation"].get("kind") == "always_manual")
    print(f"\nActive image_checkable rules: {len(active_ic)}")
    print(f"Validation kinds: {dict(kinds)}")
    print(f"\nEstimated MANUAL_REVIEW in a REAL inspection (well-covered, good OCR):")
    print(f"  always_manual: {always_m} (inspector must verify these — language, font, tampering, MRP colour)")
    print(f"  cross_source ext_regulation: {kinds.get('cross_source',0)} (citation/citation-flag)")
    print(f"  Uncertain OCR hits: 0–3 (runtime-dependent)")
    print(f"  Font relative estimates: 0–2 (per detected declaration)")
    print(f"  TOTAL estimate: {always_m + kinds.get('cross_source',0)} + OCR uncertainty (0–5)")

    if no_match:
        print(f"\n⚠ No match for: {no_match}")

    with open(JSON_PATH, "w") as f:
        json.dump(rules, f, indent=2, default=str)
    print(f"\nSaved {len(rules)} rules → {JSON_PATH.name}")


if __name__ == "__main__":
    main()
