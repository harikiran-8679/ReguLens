#!/usr/bin/env python3
"""
Step A2 v2 — Eliminate spurious MANUAL_REVIEW noise from rules_230.json.

Root causes found from live inspection analysis:
  1. R12/R13 granular unit sub-rules (19 rules, all check the same net_quantity
     field with unit_known → all produce the same result — pure noise).
  2. Enforcement / complaint / advertisement rules sitting in image_checkable
     scope (R20-003, R21-001, R22-001, R23-xxx, R24-xxx, R28-003, R31-xxx).
  3. Prohibition rules with no bindable field (always MANUAL_REVIEW — unusable).
  4. R9-005/R9-006 (transparent container / outer wrapper) applied universally.
  5. 5 manual_review scope enforcement-procedure rows that should be reference.

Principle: a rule that cannot produce an actionable PASS or NON_COMPLIANT from
package image / OCR data for the general packaged-commodity case must be
reference scope. MANUAL_REVIEW is reserved for rules where inspector action
CAN actually change the outcome.
"""
from __future__ import annotations

import json
from pathlib import Path

JSON_PATH = Path(__file__).parent.parent / "data" / "rules_230.json"


# ---------------------------------------------------------------------------
# Batch 1: R12 unit sub-rules — keep only R12-001 (umbrella rule).
# R12-002 to R12-006 are commodity-type-specific (solid/liquid/length/area/number).
# They all evaluate to the same result as R12-001 using unit_known on net_quantity.
# Moving them to reference eliminates 5 redundant MANUAL_REVIEW items.
# ---------------------------------------------------------------------------
R12_TO_REFERENCE = {
    "LMPC-R12-002",  # mass — covered by R12-001
    "LMPC-R12-003",  # length — textile/wire specific
    "LMPC-R12-004",  # area — fabric/sheet specific
    "LMPC-R12-005",  # volume — liquid specific
    "LMPC-R12-006",  # number — count-sold specific
    "LMPC-R12-009",  # additional info on same panel — supplementary
    "LMPC-R12-010",  # no misleading quantity — overlaps R13 prohibition checks
}

# R13 unit range sub-rules — keep R13-001 (general unit) and R13-015 (SI units).
# R13-002 to R13-014 specify which unit to use at each quantity range boundary —
# these cannot be verified by unit_known (which only checks if unit is known, not
# whether the correct range unit was chosen). Moving them to reference.
R13_TO_REFERENCE = {
    "LMPC-R13-002",  # < 1 kg use grams
    "LMPC-R13-003",  # < 1 m use cm/mm
    "LMPC-R13-004",  # < 1 m² use cm²
    "LMPC-R13-005",  # < 1 m³ use dm³/litre
    "LMPC-R13-006",  # < 1 dm³ use cm³/ml
    "LMPC-R13-007",  # < 1 litre use ml
    "LMPC-R13-008",  # ≥ 1 kg use kg
    "LMPC-R13-009",  # ≥ 1 m use m
    "LMPC-R13-010",  # ≥ 1 m² use m²
    "LMPC-R13-011",  # ≥ 1 m³ use m³
    "LMPC-R13-012",  # ≥ 1 litre use litres
    "LMPC-R13-014",  # no dozen/score/gross notation — prohibition, no bindable field
    "LMPC-R13-016",  # number symbols — format rule, overlaps unit_known
}

# ---------------------------------------------------------------------------
# Batch 2: Enforcement / complaint / advertisement rules in wrong scope.
# These are about legal proceedings, market investigation, or advertisements —
# none of these can be evaluated from a package label image.
# ---------------------------------------------------------------------------
ENFORCEMENT_TO_REFERENCE = {
    # R20 — post-seizure enforcement procedure
    "LMPC-R20-003",  # seizure of sample packages
    "LMPC-R20-004",  # action for violations
    "LMPC-R20-006",  # disposal of seized packages
    # R21 — complaint-based dealer inspection (requires market visit)
    "LMPC-R21-001",
    # R22 — First Schedule MPE (look-up table; requires weighing equipment)
    "LMPC-R22-001",
    # R23 — deceptive packaging (requires market investigation + test purchase)
    "LMPC-R23-001",
    "LMPC-R23-002",
    "LMPC-R23-003",
    # R24 — wholesale package rules (only apply to wholesale, not retail packages)
    "LMPC-R24-001",
    "LMPC-R24-002",
    "LMPC-R24-003",
    "LMPC-R24-004",
    # R28-003 — registered shorter address (only applies if R28 registration obtained)
    "LMPC-R28-003",
    # R31 — advertisement rules (not a label declaration check)
    "LMPC-R31-001",
    "LMPC-R31-002",
}

# ---------------------------------------------------------------------------
# Batch 3: Prohibition rules with NO bindable field.
# Without a bindable field _check_prohibition() always returns MANUAL_REVIEW.
# For rules about dealer behavior / market-level checks → reference.
# For rules about label content that CAN be physically verified → always_manual.
# ---------------------------------------------------------------------------
PROHIBITION_NO_FIELD_FIXES: dict[str, tuple[str, str | None]] = {
    # Tax-revision price controls — administrative rule about price recalculation
    # procedure, not a label-content check.
    "LMPC-R18-003": ("reference", None),

    # No alteration of printed wrapper — dealer behavior; requires physical
    # inspection of the wrapper for tampering signs, but not a standard label check.
    # Keep as always_manual so the inspector is prompted to look for tampering.
    "LMPC-R18-006": ("always_manual", None),

    # No different MRP on identical pre-packaged commodity — requires comparing
    # this package against others of the same SKU in the market.
    # Cannot be determined from a single package image → always_manual.
    "LMPC-R18-009": ("always_manual", None),
}

# ---------------------------------------------------------------------------
# Batch 4: Context-specific always_manual rules applied universally.
# R9-005 (no reading through liquid) — transparent container only.
# R9-006 (outer wrapper declarations) — secondary packaging only.
# These should only be evaluated when the package type matches.
# Since we can't determine packaging type from OCR reliably, move to reference.
# ---------------------------------------------------------------------------
CONTEXT_SPECIFIC_TO_REFERENCE = {
    "LMPC-R9-005",  # no reading through liquid — transparent containers only
    "LMPC-R9-006",  # outer wrapper / container declarations — secondary packaging only
}

# R9-001 (legible and prominent) — subjective visual check, keep as always_manual
# R9-007 (permitted languages) — universal, keep as always_manual
# R18-002 (no sale above MRP) — dealer behavior, keep as always_manual (prompts inspector)


def _to_reference(rule: dict, note: str) -> None:
    rule["scope"] = "reference"
    rule["type"] = "reference"
    rule["validation"] = {"kind": "reference"}
    rule["_a2v2_note"] = note


def patch(rules: list[dict]) -> dict:
    idx = {r["rule_id"]: r for r in rules}
    stats = {
        "r12_to_reference": 0,
        "r13_to_reference": 0,
        "enforcement_to_reference": 0,
        "prohibition_fixed": 0,
        "context_specific_to_reference": 0,
        "no_match": [],
    }

    for rid in R12_TO_REFERENCE:
        r = idx.get(rid)
        if r:
            _to_reference(r, "Redundant unit sub-rule: covered by R12-001 umbrella; unit_known validates the general case.")
            stats["r12_to_reference"] += 1
        else:
            stats["no_match"].append(f"R12:{rid}")

    for rid in R13_TO_REFERENCE:
        r = idx.get(rid)
        if r:
            _to_reference(r, "Range-specific unit rule: unit_known cannot verify correct range unit; general check in R13-001 covers the requirement.")
            stats["r13_to_reference"] += 1
        else:
            stats["no_match"].append(f"R13:{rid}")

    for rid in ENFORCEMENT_TO_REFERENCE:
        r = idx.get(rid)
        if r:
            _to_reference(r, "Enforcement/market/advertisement rule: not evaluable from package label image.")
            stats["enforcement_to_reference"] += 1
        else:
            stats["no_match"].append(f"ENF:{rid}")

    for rid, (fix_kind, new_scope) in PROHIBITION_NO_FIELD_FIXES.items():
        r = idx.get(rid)
        if r:
            if fix_kind == "reference":
                _to_reference(r, "Prohibition without bindable field: administrative/dealer-behavior rule, not a label check.")
            else:
                # always_manual — keeps rule in evaluation but produces MANUAL_REVIEW
                # so inspector is still prompted (but only once, not as multiple items)
                r["validation"] = {"kind": "always_manual"}
            stats["prohibition_fixed"] += 1
        else:
            stats["no_match"].append(f"PROH:{rid}")

    for rid in CONTEXT_SPECIFIC_TO_REFERENCE:
        r = idx.get(rid)
        if r:
            _to_reference(r, "Context-specific rule (packaging type): cannot be universally applied from label image.")
            stats["context_specific_to_reference"] += 1
        else:
            stats["no_match"].append(f"CTX:{rid}")

    return stats


def main() -> None:
    with open(JSON_PATH) as f:
        rules = json.load(f)

    before_ic = sum(1 for r in rules if r.get("scope") == "image_checkable")
    before_mr = sum(1 for r in rules if r.get("scope") == "manual_review")
    before_ref = sum(1 for r in rules if r.get("scope") == "reference")
    print(f"Loaded {len(rules)} rules")
    print(f"Before: image_checkable={before_ic}, manual_review={before_mr}, reference={before_ref}")

    stats = patch(rules)

    after_ic = sum(1 for r in rules if r.get("scope") == "image_checkable")
    after_mr = sum(1 for r in rules if r.get("scope") == "manual_review")
    after_ref = sum(1 for r in rules if r.get("scope") == "reference")
    print(f"\nAfter:  image_checkable={after_ic}, manual_review={after_mr}, reference={after_ref}")

    print(f"\nPatch stats:")
    for k, v in stats.items():
        if k != "no_match":
            print(f"  {k}: {v}")
    if stats["no_match"]:
        print(f"  WARNING — no_match: {stats['no_match']}")

    # Show final validation kinds for image_checkable active rules
    from collections import Counter
    active_ic = [r for r in rules if r.get("scope") == "image_checkable" and r.get("status") == "active"]
    kinds = Counter(r["validation"].get("kind", "?") for r in active_ic)
    print(f"\nValidation kinds (active image_checkable, {len(active_ic)} rules): {dict(kinds)}")

    # Estimate expected MANUAL_REVIEW per typical inspection
    always_m = sum(1 for r in active_ic if r["validation"].get("kind") == "always_manual")
    no_field_prohibition = sum(1 for r in active_ic
                                if r["validation"].get("kind") == "prohibition"
                                and not r["validation"].get("fields"))
    cross_src = sum(1 for r in active_ic if r["validation"].get("kind") == "cross_source")
    mr_scope = sum(1 for r in rules if r.get("scope") == "manual_review" and r.get("status") == "active")
    print(f"\nEstimated guaranteed MANUAL_REVIEW per inspection (upper bound):")
    print(f"  always_manual (image_checkable): {always_m}")
    print(f"  prohibition without fields: {no_field_prohibition}")
    print(f"  cross_source external reference: {cross_src}")
    print(f"  manual_review scope: {mr_scope}")
    print(f"  TOTAL (before OCR uncertainty): {always_m + no_field_prohibition + cross_src + mr_scope}")

    with open(JSON_PATH, "w") as f:
        json.dump(rules, f, indent=2, default=str)
    print(f"\nSaved {len(rules)} patched rules → {JSON_PATH.name}")


if __name__ == "__main__":
    main()
