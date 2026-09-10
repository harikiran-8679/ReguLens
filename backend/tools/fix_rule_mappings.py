#!/usr/bin/env python3
"""
Step A2 — Precision mapping fix for rules_230.json.

Applies targeted, evidence-based patches:
  A. Reclassify administrative/enforcement rules to reference scope
  B. Fix empty-field image_checkable presence rules
  C. Fix needs_review calculation rules
  D. Add missing cross_source subtypes
  E. Fix R18-002 (no-sale-above-MRP) to always_manual

Run from project root:
  python backend/tools/fix_rule_mappings.py
"""
from __future__ import annotations

import json
from pathlib import Path

JSON_PATH = Path(__file__).parent.parent / "data" / "rules_230.json"

# ---------------------------------------------------------------------------
# A. Administrative / enforcement rules that must be reference scope
#    These are not label-declaration checks. Marking them reference prevents
#    the engine from generating spurious NON_COMPLIANT findings.
# ---------------------------------------------------------------------------
ADMIN_TO_REFERENCE: set[str] = {
    # Rule 4 — general pre-packing provisions (procedure, not label check)
    "LMPC-R4-001", "LMPC-R4-003", "LMPC-R4-004",
    # Rule 9 — language provisions (complex; OCR language detection unreliable)
    "LMPC-R9-003", "LMPC-R9-004",
    # Rule 11 — environmental variation (requires weighing equipment)
    "LMPC-R11-001", "LMPC-R11-002", "LMPC-R11-003", "LMPC-R11-004",
    # Rule 12 — optional/supplementary quantity declarations
    "LMPC-R12-007", "LMPC-R12-008", "LMPC-R12-011",
    # Rule 13 — alternative quantity expression rules
    "LMPC-R13-013", "LMPC-R13-017",
    # Rule 14 — textile/dimension-specific commodity rules
    "LMPC-R14-001", "LMPC-R14-002", "LMPC-R14-003",
    # Rule 15 — dimension/weight linked to price
    "LMPC-R15-001",
    # Rule 16 — usable-sheets declarations
    "LMPC-R16-001",
    # Rule 17 — container-type specific declarations
    "LMPC-R17-001", "LMPC-R17-002", "LMPC-R17-003", "LMPC-R17-004",
    # Rule 18 — dealer / tax-revision provisions
    "LMPC-R18-001", "LMPC-R18-004", "LMPC-R18-007", "LMPC-R18-008",
    # Rule 19 — enforcement / inspection procedure
    "LMPC-R19-003", "LMPC-R19-006", "LMPC-R19-009",
    "LMPC-R19-012", "LMPC-R19-013",
    # Rule 20 — enforcement action for missing declarations
    "LMPC-R20-002",
    # Rule 21 — verification procedure (requires weighing)
    "LMPC-R21-004",
    # Rule 22 — MPE limit / enforcement sampling tables
    "LMPC-R22-002", "LMPC-R22-003", "LMPC-R22-004", "LMPC-R22-005",
    # Rule 27 — registration (not a label check)
    "LMPC-R27-001", "LMPC-R27-002", "LMPC-R27-003", "LMPC-R27-004",
    "LMPC-R27-005", "LMPC-R27-006", "LMPC-R27-007", "LMPC-R27-008",
    "LMPC-R27-009", "LMPC-R27-010", "LMPC-R27-011",
    # Rule 28 — shorter address registration
    "LMPC-R28-001", "LMPC-R28-002",
    # Rule 34 — savings provisions (transition law)
    "LMPC-R34-002",
    # Schedules — lookup tables, MPE tables, inspection forms (not label checks)
    "LMPC-S02-001", "LMPC-S03-001", "LMPC-S04-001",
    "LMPC-S05-001", "LMPC-S06-001", "LMPC-S07-001",
}

# ---------------------------------------------------------------------------
# B. Empty-field image_checkable presence rules — precise fix per rule
#    Each tuple: (rule_id, new_validation_dict, optional_new_scope)
# ---------------------------------------------------------------------------
FIELD_FIXES: list[tuple[str, dict, str | None]] = [
    # R6-001: manufacturer / packer / importer name on label
    ("LMPC-R6-001", {
        "kind": "any_present",
        "fields": ["manufacturer_name", "packer_name", "importer_name"],
    }, None),

    # R6-010: best-before / use-by date
    ("LMPC-R6-010", {
        "kind": "present",
        "field": "best_before",
    }, None),

    # R6-007: dimensions where relevant — product-category-specific; cannot determine
    # applicability from label image alone without knowing what commodity type is in the box
    ("LMPC-R6-007", {
        "kind": "always_manual",
    }, None),

    # R6-011: QR code containing address info (electronic products)
    ("LMPC-R6-011", {
        "kind": "always_manual",
    }, None),

    # R6-012: QR code containing product info (electronic products)
    ("LMPC-R6-012", {
        "kind": "always_manual",
    }, None),

    # R6-013: QR code containing dimension info (electronic products)
    ("LMPC-R6-013", {
        "kind": "always_manual",
    }, None),

    # R6-015: QR code containing consumer-care info (electronic products)
    ("LMPC-R6-015", {
        "kind": "always_manual",
    }, None),

    # R6-017: other sticker declarations (supplementary, context-dependent)
    ("LMPC-R6-017", {
        "kind": "always_manual",
    }, None),

    # R6-018: optional barcode / QR / e-code scheme info
    ("LMPC-R6-018", {
        "kind": "always_manual",
    }, None),

    # R6-019: packages containing multiple components
    ("LMPC-R6-019", {
        "kind": "always_manual",
    }, None),

    # R6-020: historical transitional packaging permission — reference
    ("LMPC-R6-020", {
        "kind": "reference",
    }, "reference"),

    # R6-028: combination / group / multi-piece package exception — reference
    ("LMPC-R6-028", {
        "kind": "reference",
    }, "reference"),

    # R10-001: manufacturer/packer/importer name and complete address
    ("LMPC-R10-001", {
        "kind": "any_present",
        "fields": ["manufacturer_name", "packer_name", "importer_name", "manufacturer_address"],
    }, None),

    # R10-002: explanation of "complete address" — administrative note
    ("LMPC-R10-002", {
        "kind": "reference",
    }, "reference"),

    # R10-003: actual business/corporate name — label check
    ("LMPC-R10-003", {
        "kind": "present",
        "field": "manufacturer_name",
    }, None),

    # R18-002: no sale above MRP — dealer behaviour rule, not a label-only check.
    # The MRP declaration itself is checked by R6-008/6-009; this rule is about
    # what the dealer charges the consumer, requiring a test purchase to verify.
    ("LMPC-R18-002", {
        "kind": "always_manual",
    }, None),

    # Remaining present-with-empty-field rules that are administrative/procedural
    # and were not caught by the ADMIN_TO_REFERENCE set
    ("LMPC-R19-012", {"kind": "reference"}, "reference"),
    ("LMPC-R19-013", {"kind": "reference"}, "reference"),
    ("LMPC-R27-005", {"kind": "reference"}, "reference"),
    ("LMPC-R27-007", {"kind": "reference"}, "reference"),
]

# ---------------------------------------------------------------------------
# C. needs_review calculation rules — precise fix
# ---------------------------------------------------------------------------
NEEDS_REVIEW_FIXES: list[tuple[str, dict, str | None]] = [
    # R6-027: 6(11) — multi-piece package quantity arithmetic.
    # Rule: the declared quantity of each piece × number of pieces must equal the
    # total declared quantity. This requires physical counting and measurement,
    # not image OCR alone.
    ("LMPC-R6-027", {"kind": "always_manual"}, None),

    # R7-008 to R7-011: 7(4) — font size rules for "other area" packages.
    # The PDF gives area-based thresholds (mm² of total area → minimum mm height).
    # Converting package area to mm from a photograph requires calibration that is
    # not available. Mark always_manual with the OCR caveat.
    ("LMPC-R7-008", {"kind": "always_manual"}, None),
    ("LMPC-R7-009", {"kind": "always_manual"}, None),
    ("LMPC-R7-010", {"kind": "always_manual"}, None),
    ("LMPC-R7-011", {"kind": "always_manual"}, None),

    # R11-001: 11(1) — MPE tolerance calculation. Requires weighing equipment.
    ("LMPC-R11-001", {"kind": "reference"}, "reference"),

    # R19-009: 19(6)(a) — enforcement lot / re-inspection calculation.
    ("LMPC-R19-009", {"kind": "reference"}, "reference"),

    # R22-002 to R22-005: MPE limits and sampling tables.
    ("LMPC-R22-002", {"kind": "reference"}, "reference"),
    ("LMPC-R22-003", {"kind": "reference"}, "reference"),
    ("LMPC-R22-004", {"kind": "reference"}, "reference"),
    ("LMPC-R22-005", {"kind": "reference"}, "reference"),

    # Schedules V and VI: MPE schedule table and net-quantity determination method.
    ("LMPC-S05-001", {"kind": "reference"}, "reference"),
    ("LMPC-S06-001", {"kind": "reference"}, "reference"),
]

# ---------------------------------------------------------------------------
# D. cross_source rules — add external_regulation_reference subtype
#    These rules reference external statutes, not an online listing.
#    The engine's _cross_source_row already handles this subtype (always MANUAL_REVIEW
#    with a citation flag). No engine change needed.
# ---------------------------------------------------------------------------
CROSS_SOURCE_FIXES: set[str] = {
    "LMPC-R6-024",   # 6(10) — e-commerce mandatory declarations
    "LMPC-R6-025",   # 6(10A) — imported-product search filter (2026)
    "LMPC-R6-026",   # 6(10A) — future 2027 wording
    "LMPC-R7-003",   # 7(2) proviso — medical device cross-ref
    "LMPC-R7-005",   # 7(3) proviso — medical device letter-height
    "LMPC-R7-007",   # 7(5) — other-law font exception
    "LMPC-R10-003",  # already fixed in FIELD_FIXES — skip
    "LMPC-R24-004",  # 24 proviso — other-law exception
    "LMPC-R27-008",  # 27(3) proviso — annual online update (reference)
}
# R10-003 handled separately in FIELD_FIXES; remove from cross_source set
CROSS_SOURCE_FIXES.discard("LMPC-R10-003")

# R27-008 is administrative — move to reference
CROSS_SOURCE_TO_REFERENCE: set[str] = {"LMPC-R27-008"}

# ---------------------------------------------------------------------------
# Main patch logic
# ---------------------------------------------------------------------------
def _set_reference(rule: dict, reason: str) -> None:
    rule["scope"] = "reference"
    rule["type"] = "reference"
    rule["validation"] = {"kind": "reference"}
    rule.setdefault("_a2_note", reason)


def patch(rules: list[dict]) -> tuple[list[dict], dict]:
    stats = {
        "admin_to_reference": 0,
        "field_fixed": 0,
        "needs_review_fixed": 0,
        "cross_source_subtype": 0,
        "cross_source_to_reference": 0,
        "no_match": [],
    }
    idx = {r["rule_id"]: r for r in rules}

    # A — admin to reference
    for rid in ADMIN_TO_REFERENCE:
        r = idx.get(rid)
        if r:
            _set_reference(r, "Administrative/enforcement provision — not a label declaration check.")
            stats["admin_to_reference"] += 1
        else:
            stats["no_match"].append(f"A:{rid}")

    # B — field fixes
    for rid, new_val, new_scope in FIELD_FIXES:
        r = idx.get(rid)
        if r:
            r["validation"] = new_val
            if new_scope:
                r["scope"] = new_scope
                if new_scope == "reference":
                    r["type"] = "reference"
            stats["field_fixed"] += 1
        else:
            stats["no_match"].append(f"B:{rid}")

    # C — needs_review fixes
    for rid, new_val, new_scope in NEEDS_REVIEW_FIXES:
        r = idx.get(rid)
        if r:
            r["validation"] = new_val
            if new_scope:
                r["scope"] = new_scope
                if new_scope == "reference":
                    r["type"] = "reference"
            stats["needs_review_fixed"] += 1
        else:
            stats["no_match"].append(f"C:{rid}")

    # D — cross_source subtype
    for rid in CROSS_SOURCE_FIXES:
        r = idx.get(rid)
        if r:
            val = r.get("validation", {})
            if val.get("kind") == "cross_source":
                val["subtype"] = "external_regulation_reference"
                val["external_source"] = r.get("description", "")[:200]
                stats["cross_source_subtype"] += 1
            else:
                # Was already fixed elsewhere (e.g. field_fixes changed the kind)
                pass
        else:
            stats["no_match"].append(f"D:{rid}")

    for rid in CROSS_SOURCE_TO_REFERENCE:
        r = idx.get(rid)
        if r:
            _set_reference(r, "Administrative online-update provision — reference only.")
            stats["cross_source_to_reference"] += 1
        else:
            stats["no_match"].append(f"D_ref:{rid}")

    # Final pass: any remaining image_checkable rule with kind='present' + empty field
    # that slipped through → change to always_manual (safe fallback: never produces
    # a false NON_COMPLIANT)
    remaining_empty = 0
    for r in rules:
        if (r.get("scope") == "image_checkable"
                and r.get("validation", {}).get("kind") == "present"
                and not r.get("validation", {}).get("field")):
            r["validation"] = {"kind": "always_manual"}
            r.setdefault("_a2_note", "Fallback: empty field on image_checkable present rule — changed to always_manual to prevent false NON_COMPLIANT.")
            remaining_empty += 1
    stats["remaining_empty_fallback"] = remaining_empty

    return rules, stats


def main() -> None:
    with open(JSON_PATH) as f:
        rules = json.load(f)

    print(f"Loaded {len(rules)} rules from {JSON_PATH.name}")
    original_ic = sum(1 for r in rules if r.get("scope") == "image_checkable")
    original_ref = sum(1 for r in rules if r.get("scope") == "reference")
    print(f"Before: image_checkable={original_ic}, reference={original_ref}")

    rules, stats = patch(rules)

    new_ic = sum(1 for r in rules if r.get("scope") == "image_checkable")
    new_ref = sum(1 for r in rules if r.get("scope") == "reference")
    new_manual = sum(1 for r in rules if r.get("scope") == "manual_review")

    print(f"\nAfter: image_checkable={new_ic}, manual_review={new_manual}, reference={new_ref}")
    print(f"\nPatch stats:")
    for k, v in stats.items():
        if k != "no_match":
            print(f"  {k}: {v}")
    if stats["no_match"]:
        print(f"  WARNING — no_match rule_ids: {stats['no_match']}")

    # Verify no image_checkable rules have empty field
    empty_after = [r["rule_id"] for r in rules
                   if r.get("scope") == "image_checkable"
                   and r.get("validation", {}).get("kind") == "present"
                   and not r.get("validation", {}).get("field")]
    if empty_after:
        print(f"\n⚠ Still have {len(empty_after)} empty-field present rules: {empty_after}")
    else:
        print("\n✅ No image_checkable rules with empty present field remain.")

    # Show validation kind breakdown for image_checkable
    from collections import Counter
    active_ic = [r for r in rules if r.get("scope") == "image_checkable" and r.get("status") == "active"]
    kinds = Counter(r["validation"].get("kind","?") for r in active_ic)
    print(f"\nValidation kinds (active image_checkable): {dict(kinds)}")

    with open(JSON_PATH, "w") as f:
        json.dump(rules, f, indent=2, default=str)
    print(f"\nSaved {len(rules)} patched rules → {JSON_PATH}")


if __name__ == "__main__":
    main()
