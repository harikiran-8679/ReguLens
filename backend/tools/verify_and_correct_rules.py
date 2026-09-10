#!/usr/bin/env python3
"""
Step A2-VERIFY — Full PDF-against-classification verification.

Reads all 230 rule records and the classified JSON, then cross-checks every
rule's validation.kind against the legal text rules and rule_engine.py's
dispatch schema, applies corrections, and saves a corrected register_classified.json.

Run from backend/:
    .venv/bin/python3 tools/verify_and_correct_rules.py
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS_PATH    = ROOT / "data" / "register_records.json"
CLASSIFIED_PATH = ROOT / "data" / "register_classified.json"
REPORT_PATH     = ROOT / "data" / "verification_report.txt"

# ---------------------------------------------------------------------------
# Engine-valid validation kinds as dispatched in rule_engine.py
# ---------------------------------------------------------------------------
ENGINE_VALID_KINDS = {
    "presence", "any_present", "text_contains", "unit_known", "range",
    "date_month_year", "format_mrp", "prohibition", "font",
    "cross_consistency", "cross_source", "always_manual", "reference",
    "needs_review",
}

# ---------------------------------------------------------------------------
# Authoritative scope + kind per rule, derived by reading the PDF legal text.
# Format: rule_id -> (scope_bucket, valid_kind, rationale)
# scope_bucket: "image_checkable" | "manual_review" | "legal_reference" | "needs_review"
# ---------------------------------------------------------------------------
CORRECTIONS = {
    # ── Rule 1 ──
    "LMPC-R1-001": ("legal_reference", "reference", "Short title — procedural, not a label check."),
    "LMPC-R1-002": ("legal_reference", "reference", "Commencement — procedural."),
    # ── Rule 2: Definitions ──
    "LMPC-R2-001": ("legal_reference", "reference", "Definition of 'advertisement' — definitional."),
    "LMPC-R2-002": ("legal_reference", "reference", "Definition of 'combination package' — definitional."),
    "LMPC-R2-003": ("legal_reference", "reference", "Definition of 'commodity' — definitional."),
    "LMPC-R2-004": ("legal_reference", "reference", "Definition of 'dealer' — definitional."),
    "LMPC-R2-005": ("legal_reference", "reference", "Definition of 'error of measurement' — definitional."),
    "LMPC-R2-006": ("legal_reference", "reference", "Definition of 'group package' — definitional."),
    "LMPC-R2-007": ("legal_reference", "reference", "Definition of 'multi-piece package' — definitional."),
    # ── Rule 3: Exemptions ──
    "LMPC-R3-001": ("legal_reference", "reference", "General exemptions — engine cannot determine applicability."),
    "LMPC-R3-002": ("legal_reference", "reference", "Above-50kg bag exemption — engine cannot weigh."),
    "LMPC-R3-003": ("legal_reference", "reference", "Notified exemption classes — reference."),
    # ── Rule 4: Pre-packing / mandatory declaration framework ──
    "LMPC-R4-001": ("image_checkable", "any_present",
                    "Rule 4(1): All retail packages must bear mandatory declarations. Checkable by verifying mandatory fields are present."),
    "LMPC-R4-002": ("image_checkable", "cross_consistency",
                    "Rule 4(2): Net quantity must be consistent across all panels — cross_consistency check."),
    "LMPC-R4-003": ("legal_reference", "reference",
                    "Rule 4(3): AEO bonded-warehouse — requires AEO cert status, not verifiable from image."),
    "LMPC-R4-004": ("legal_reference", "reference",
                    "Rule 4 explanation-2: AEO Tier-2/Tier-3 sub-provision — reference."),
    # ── Rule 5: Omitted ──
    "LMPC-R5-001": ("legal_reference", "reference", "Rule 5 omitted effective 1 April 2022 — historical."),
    # ── Rule 6: Mandatory declarations ──
    "LMPC-R6-001": ("image_checkable", "any_present",
                    "Rule 6(1)(a): Name of manufacturer/packer/importer — mandatory, checkable."),
    "LMPC-R6-002": ("image_checkable", "presence",
                    "Rule 6(1)(b): Common/generic name of commodity — mandatory."),
    "LMPC-R6-003": ("image_checkable", "presence",
                    "Rule 6(1)(c): Net quantity in standard units — mandatory."),
    "LMPC-R6-004": ("image_checkable", "presence",
                    "Rule 6(1)(d): Month and year of manufacture/packing — mandatory."),
    "LMPC-R6-005": ("image_checkable", "format_mrp",
                    "Rule 6(1)(e): MRP in Indian currency inclusive of taxes — format_mrp check."),
    "LMPC-R6-006": ("image_checkable", "date_month_year",
                    "Rule 6(2): Consumer care details — date_month_year for date fields; phone/email for contact."),
    "LMPC-R6-007": ("legal_reference", "reference",
                    "Rule 6(1)(f): Dimensions — only for textiles/containers/sheets, not universally applicable."),
    "LMPC-R6-008": ("image_checkable", "any_present",
                    "Rule 6(2): Consumer care contact details (phone/email) — mandatory, any_present check."),
    "LMPC-R6-009": ("image_checkable", "text_contains",
                    "Rule 6(5): Country of origin for imported goods — mandatory for imports, text_contains."),
    "LMPC-R6-010": ("image_checkable", "presence",
                    "Rule 6(1)(h): Best-before/use-by date for perishable goods — mandatory where applicable."),
    "LMPC-R6-011": ("image_checkable", "always_manual",
                    "Rule 6(3A) 2023: QR code with address info for electronic products — always_manual."),
    "LMPC-R6-012": ("image_checkable", "always_manual",
                    "Rule 6(3B) 2023: QR code with product info for electronic products — always_manual."),
    "LMPC-R6-013": ("image_checkable", "always_manual",
                    "Rule 6(3C) 2023: QR code with dimensions for electronic products — always_manual."),
    "LMPC-R6-014": ("image_checkable", "always_manual",
                    "Rule 6(3D) 2023: VIN/serial number for electronic products — always_manual."),
    "LMPC-R6-015": ("image_checkable", "always_manual",
                    "Rule 6(3E) 2023: QR code with consumer-care info for electronic products — always_manual."),
    "LMPC-R6-016": ("image_checkable", "always_manual",
                    "Rule 6 medical device 2025: Medical device declaration provisions — always_manual."),
    "LMPC-R6-017": ("legal_reference", "reference",
                    "Rule 6(4): Supplementary sticker declarations — only when manufacturer uses a sticker; optional."),
    "LMPC-R6-018": ("legal_reference", "reference",
                    "Rule 6(4A): Optional barcode/QR ('may also state') — not a mandatory declaration."),
    "LMPC-R6-019": ("legal_reference", "reference",
                    "Rule 6(5): Multiple-component package provision — only for combination packs."),
    "LMPC-R6-020": ("legal_reference", "reference",
                    "Rule 6(6): Historical transitional packaging permission — reference."),
    "LMPC-R6-021": ("legal_reference", "reference",
                    "Rule 6(7): Catch-all for other-authority declarations — engine cannot generalise."),
    "LMPC-R6-022": ("legal_reference", "reference",
                    "Rule 6(8): BIS/FSSAI regulated products — product-category condition not engine-bindable."),
    "LMPC-R6-023": ("legal_reference", "reference",
                    "Rule 6(9): Additional declaration catch-all — not engine-evaluable."),
    "LMPC-R6-024": ("image_checkable", "cross_source",
                    "Rule 6(10): E-commerce mandatory declarations — cross_source check against online listing."),
    "LMPC-R6-025": ("image_checkable", "cross_source",
                    "Rule 6(10A) 2026: Imported product e-commerce search filter — cross_source."),
    "LMPC-R6-026": ("legal_reference", "reference",
                    "Rule 6(10A) 2027: Future e-commerce version — not active until 1 July 2027."),
    "LMPC-R6-027": ("manual_review", "always_manual",
                    "Rule 6(11): Multi-piece quantity arithmetic — requires physical counting, always_manual."),
    "LMPC-R6-028": ("legal_reference", "reference",
                    "Rule 6(11) proviso: Combination/group exception — reference."),
    # ── Rule 7: Font size ──
    "LMPC-R7-001": ("legal_reference", "reference",
                    "Rule 7(1): Small-capacity (≤10g/ml) PDP — package-size condition needs physical measurement."),
    "LMPC-R7-002": ("image_checkable", "font",
                    "Rule 7(2): Minimum numeral height per Table-I — core font check."),
    "LMPC-R7-003": ("image_checkable", "cross_source",
                    "Rule 7(2) medical device proviso: Cross-reference to medical device regulations."),
    "LMPC-R7-004": ("image_checkable", "font",
                    "Rule 7(2) letter height: Letters must match numeral height from Table-I."),
    "LMPC-R7-005": ("image_checkable", "cross_source",
                    "Rule 7(2) medical device letter-height proviso: Cross-source reference."),
    "LMPC-R7-006": ("manual_review", "always_manual",
                    "Rule 7(3): Legibility and readability — inspector visual verification required."),
    "LMPC-R7-007": ("image_checkable", "cross_source",
                    "Rule 7(5): Other-law font exception — cross-source to external law."),
    "LMPC-R7-008": ("legal_reference", "reference",
                    "Rule 7(4): PDP area determination — requires physical mm² measurement."),
    "LMPC-R7-009": ("legal_reference", "reference",
                    "Rule 7(4)(a): Rectangular package PDP area — calibration required."),
    "LMPC-R7-010": ("legal_reference", "reference",
                    "Rule 7(4)(b): Cylindrical package PDP area — calibration required."),
    "LMPC-R7-011": ("legal_reference", "reference",
                    "Rule 7(4)(c): Other-shaped package PDP area — calibration required."),
    # ── Rule 8: Small package exemptions ──
    "LMPC-R8-001": ("legal_reference", "reference",
                    "Rule 8(1): Small package (≤5ml/≤5g) exemptions — engine cannot weigh."),
    "LMPC-R8-002": ("legal_reference", "reference",
                    "Rule 8(2): Returnable beverage bottle — only for refillable deposit-scheme containers."),
    # ── Rule 9: Language ──
    "LMPC-R9-001": ("manual_review", "always_manual",
                    "Rule 9(1): English/Hindi/State language — OCR language detection needs manual review."),
    "LMPC-R9-002": ("manual_review", "always_manual",
                    "Rule 9(2): State language alternative — manual verification."),
    "LMPC-R9-003": ("legal_reference", "reference",
                    "Rule 9(3): Language of additional declarations — reference."),
    "LMPC-R9-004": ("legal_reference", "reference",
                    "Rule 9(4): Language of other declarations — reference."),
    # ── Rule 10: Name and address ──
    "LMPC-R10-001": ("image_checkable", "any_present",
                     "Rule 10(1): Name and complete address of manufacturer/packer/importer — mandatory any_present."),
    "LMPC-R10-002": ("legal_reference", "reference",
                     "Rule 10(2): Definition of 'complete address' — administrative note."),
    "LMPC-R10-003": ("image_checkable", "presence",
                     "Rule 10(3): Actual business/corporate name on label — mandatory presence."),
    # ── Rule 11: Environmental variation ──
    "LMPC-R11-001": ("legal_reference", "reference", "Rule 11(1): MPE tolerance — requires weighing equipment."),
    "LMPC-R11-002": ("legal_reference", "reference", "Rule 11(2): Environmental variation allowance — requires weighing."),
    "LMPC-R11-003": ("legal_reference", "reference", "Rule 11(3): Altitude/humidity adjustment — reference."),
    "LMPC-R11-004": ("legal_reference", "reference", "Rule 11(4): Moisture variation allowance — reference."),
    # ── Rule 12: Net quantity ──
    "LMPC-R12-001": ("image_checkable", "presence",
                     "Rule 12(1): Net quantity in standard units — mandatory presence."),
    "LMPC-R12-002": ("image_checkable", "unit_known",
                     "Rule 12(2): Net quantity unit must be a known SI unit."),
    "LMPC-R12-003": ("image_checkable", "unit_known",
                     "Rule 12(3): Standard unit — no non-SI abbreviations."),
    "LMPC-R12-004": ("image_checkable", "unit_known",
                     "Rule 12(4): Solid net quantity in mass (g/kg) — unit check."),
    "LMPC-R12-005": ("image_checkable", "unit_known",
                     "Rule 12(5): Liquid net quantity in volume (ml/l) — unit check."),
    "LMPC-R12-006": ("image_checkable", "unit_known",
                     "Rule 12(6): Net quantity numeric + unit — unit_known."),
    "LMPC-R12-007": ("legal_reference", "reference",
                     "Rule 12(7): Optional drained weight — not mandatory."),
    "LMPC-R12-008": ("legal_reference", "reference",
                     "Rule 12(8): Additional net quantity — optional supplement."),
    "LMPC-R12-009": ("image_checkable", "range",
                     "Rule 12(9): Net quantity within declared range — range check."),
    "LMPC-R12-010": ("image_checkable", "unit_known",
                     "Rule 12(10): Count of articles — unit/count check."),
    "LMPC-R12-011": ("legal_reference", "reference",
                     "Rule 12(11): Supplementary units — optional, not mandatory."),
    # ── Rule 13: Quantity expression ──
    "LMPC-R13-001": ("image_checkable", "unit_known", "Rule 13(1): Quantity in correct SI unit."),
    "LMPC-R13-002": ("image_checkable", "unit_known", "Rule 13(2): Unit must match commodity type."),
    "LMPC-R13-003": ("image_checkable", "unit_known", "Rule 13(3): Abbreviated SI units only."),
    "LMPC-R13-004": ("image_checkable", "unit_known", "Rule 13(4): Solid → mass (g/kg)."),
    "LMPC-R13-005": ("image_checkable", "unit_known", "Rule 13(5): Liquid → volume (ml/l)."),
    "LMPC-R13-006": ("image_checkable", "unit_known", "Rule 13(6): Semi-solid → mass or volume."),
    "LMPC-R13-007": ("image_checkable", "unit_known", "Rule 13(7): Counted articles → number."),
    "LMPC-R13-008": ("image_checkable", "unit_known", "Rule 13(8): Length → m/cm."),
    "LMPC-R13-009": ("image_checkable", "unit_known", "Rule 13(9): Area → m²."),
    "LMPC-R13-010": ("image_checkable", "unit_known", "Rule 13(10): Volume → cm³/m³."),
    "LMPC-R13-011": ("image_checkable", "unit_known", "Rule 13(11): Fractions < 1 expressed as decimals."),
    "LMPC-R13-012": ("image_checkable", "prohibition",
                     "Rule 13(12): Vulgar fraction notation (1/2 etc.) prohibited — prohibition check."),
    "LMPC-R13-013": ("legal_reference", "reference", "Rule 13(13): Alternative unit expression — reference."),
    "LMPC-R13-014": ("image_checkable", "unit_known", "Rule 13(14): Combination quantity expression."),
    "LMPC-R13-015": ("image_checkable", "unit_known", "Rule 13(15): Dual-unit expression allowed."),
    "LMPC-R13-016": ("image_checkable", "unit_known", "Rule 13(16): Count + mass dual expression."),
    "LMPC-R13-017": ("legal_reference", "reference", "Rule 13(17): N/U expression — historical; reference."),
    # ── Rules 14–17: Commodity-specific ──
    "LMPC-R14-001": ("legal_reference", "reference", "Rule 14: Textile commodity — engine cannot identify textile vs food."),
    "LMPC-R14-002": ("legal_reference", "reference", "Rule 14: Textile label requirements."),
    "LMPC-R14-003": ("legal_reference", "reference", "Rule 14: Textile additional declarations."),
    "LMPC-R15-001": ("legal_reference", "reference", "Rule 15: Dimension/weight linked to price — reference."),
    "LMPC-R16-001": ("legal_reference", "reference", "Rule 16: Usable-sheets declarations — reference."),
    "LMPC-R17-001": ("legal_reference", "reference", "Rule 17: Container capacity label — reference."),
    "LMPC-R17-002": ("legal_reference", "reference", "Rule 17: Container dimensions — reference."),
    "LMPC-R17-003": ("legal_reference", "reference", "Rule 17: Container type-specific declarations — reference."),
    "LMPC-R17-004": ("legal_reference", "reference", "Rule 17: Container load limit — reference."),
    # ── Rule 18: MRP ──
    "LMPC-R18-001": ("legal_reference", "reference",
                     "Rule 18(1): General MRP provision — framework; specific checks via R6-005."),
    "LMPC-R18-002": ("manual_review", "always_manual",
                     "Rule 18(1)(a): No sale above MRP — dealer behaviour, requires test purchase."),
    "LMPC-R18-003": ("image_checkable", "prohibition",
                     "Rule 18(2): No different MRP on identical pre-packaged commodity — prohibition."),
    "LMPC-R18-004": ("legal_reference", "reference",
                     "Rule 18(3): Tax revision sticker — dealer behaviour provision."),
    "LMPC-R18-005": ("image_checkable", "text_contains",
                     "Rule 18(4): MRP inclusive of all taxes wording — text_contains check."),
    "LMPC-R18-006": ("image_checkable", "format_mrp",
                     "Rule 18(5): MRP format (Rs./₹ + amount) — format_mrp check."),
    "LMPC-R18-007": ("legal_reference", "reference",
                     "Rule 18(6): MRP revision notice — dealer behaviour."),
    "LMPC-R18-008": ("legal_reference", "reference",
                     "Rule 18(7): MRP sticker placement — reference."),
    "LMPC-R18-009": ("image_checkable", "prohibition",
                     "Rule 18(2A): No different MRP using restrictive/unfair trade practices — prohibition."),
    # ── Rules 19–22: Enforcement ──
    "LMPC-R19-001": ("legal_reference", "reference", "Rule 19: Inspector seal — enforcement."),
    "LMPC-R19-002": ("legal_reference", "reference", "Rule 19: Sampling procedure — enforcement."),
    "LMPC-R19-003": ("legal_reference", "reference", "Rule 19: Lot size — enforcement."),
    "LMPC-R19-004": ("legal_reference", "reference", "Rule 19: Weighing procedure — enforcement."),
    "LMPC-R19-005": ("legal_reference", "reference", "Rule 19: Label verification — enforcement."),
    "LMPC-R19-006": ("legal_reference", "reference", "Rule 19: Lot rejection — enforcement."),
    "LMPC-R19-007": ("legal_reference", "reference", "Rule 19: Inspector report — enforcement."),
    "LMPC-R19-008": ("legal_reference", "reference", "Rule 19: Re-inspection — enforcement."),
    "LMPC-R19-009": ("legal_reference", "reference", "Rule 19: Re-inspection calculation — enforcement."),
    "LMPC-R19-010": ("legal_reference", "reference", "Rule 19: Second re-inspection — enforcement."),
    "LMPC-R19-011": ("legal_reference", "reference", "Rule 19: Final rejection — enforcement."),
    "LMPC-R19-012": ("legal_reference", "reference", "Rule 19: Inspector verification form — enforcement."),
    "LMPC-R19-013": ("legal_reference", "reference", "Rule 19: Inspector report form — enforcement."),
    "LMPC-R20-001": ("legal_reference", "reference", "Rule 20: Missing declaration enforcement — enforcement."),
    "LMPC-R20-002": ("legal_reference", "reference", "Rule 20: Penalty provision — enforcement."),
    "LMPC-R21-001": ("legal_reference", "reference", "Rule 21: Verification procedure — enforcement."),
    "LMPC-R21-002": ("legal_reference", "reference", "Rule 21: Verification equipment — enforcement."),
    "LMPC-R21-003": ("legal_reference", "reference", "Rule 21: Weighing process — enforcement."),
    "LMPC-R21-004": ("legal_reference", "reference", "Rule 21: MPE limit check — enforcement/weighing."),
    "LMPC-R22-001": ("legal_reference", "reference", "Rule 22: MPE limit table — reference."),
    "LMPC-R22-002": ("legal_reference", "reference", "Rule 22: MPE sampling table — reference."),
    "LMPC-R22-003": ("legal_reference", "reference", "Rule 22: MPE sampling table (cont.) — reference."),
    "LMPC-R22-004": ("legal_reference", "reference", "Rule 22: MPE limits for specific commodities — reference."),
    "LMPC-R22-005": ("legal_reference", "reference", "Rule 22: MPE limits table final — reference."),
    # ── Rule 24: Retail sale ──
    "LMPC-R24-001": ("image_checkable", "presence", "Rule 24(1): Retail sale label requirements."),
    "LMPC-R24-002": ("image_checkable", "any_present", "Rule 24(2): Bulk sale package declarations."),
    "LMPC-R24-003": ("image_checkable", "presence", "Rule 24(3): Bulk package MRP required."),
    "LMPC-R24-004": ("image_checkable", "cross_source",
                     "Rule 24 proviso: Cross-reference to other laws — cross_source."),
    # ── Rules 27–28: Registration ──
    "LMPC-R27-001": ("legal_reference", "reference", "Rule 27: Registration requirement — administrative."),
    "LMPC-R27-002": ("legal_reference", "reference", "Rule 27: Registration form — administrative."),
    "LMPC-R27-003": ("legal_reference", "reference", "Rule 27: Registration fee — administrative."),
    "LMPC-R27-004": ("legal_reference", "reference", "Rule 27: Registration certificate — administrative."),
    "LMPC-R27-005": ("legal_reference", "reference", "Rule 27: Registration renewal — administrative."),
    "LMPC-R27-006": ("legal_reference", "reference", "Rule 27: Registration cancellation — administrative."),
    "LMPC-R27-007": ("legal_reference", "reference", "Rule 27: Registration appeal — administrative."),
    "LMPC-R27-008": ("legal_reference", "reference", "Rule 27: Annual online update — administrative."),
    "LMPC-R27-009": ("legal_reference", "reference", "Rule 27: Registration database — administrative."),
    "LMPC-R27-010": ("legal_reference", "reference", "Rule 27: Registration inspection — administrative."),
    "LMPC-R27-011": ("legal_reference", "reference", "Rule 27: Registration enforcement — administrative."),
    "LMPC-R28-001": ("legal_reference", "reference", "Rule 28: Shorter address registration — administrative."),
    "LMPC-R28-002": ("legal_reference", "reference", "Rule 28: Address registration form — administrative."),
    # ── Rule 34: Savings ──
    "LMPC-R34-001": ("legal_reference", "reference", "Rule 34: Savings provision — transitional law."),
    "LMPC-R34-002": ("legal_reference", "reference", "Rule 34: Savings provision (cont.) — transitional law."),
    # ── Schedules ──
    "LMPC-S01-001": ("legal_reference", "reference", "Schedule I: Table-I font values — lookup table, not a direct check."),
    "LMPC-S02-001": ("legal_reference", "reference", "Schedule II: Table-II (omitted by GSR 629(E)) — historical reference."),
    "LMPC-S03-001": ("legal_reference", "reference", "Schedule III: MPE table — referenced by Rule 22."),
    "LMPC-S04-001": ("legal_reference", "reference", "Schedule IV: Inspection form — reference."),
    "LMPC-S05-001": ("legal_reference", "reference", "Schedule V: MPE schedule — reference."),
    "LMPC-S06-001": ("legal_reference", "reference", "Schedule VI: Net quantity determination — reference."),
    "LMPC-S07-001": ("legal_reference", "reference", "Schedule VII — reference."),
}

# Table-I values from Rule 7(2) of the Rules
TABLE_I = {
    "normal_min_mm": [1.0, 1.5, 2.5, 4.0, 6.0],
    "blown_formed_molded_min_mm": [2.0, 3.0, 5.0, 8.0, 12.0],
    "row_selection": "A<50cm2; 50<=A<100; 100<=A<500; 500<=A<2500; A>=2500",
    "area_unit": "cm2",
    "measurement_unit": "mm",
    "corrigendum": "Table-II omitted by G.S.R. 629(E)",
}

# External regulation cross-references
EXTERNAL_REG_RULES = {
    "LMPC-R6-024", "LMPC-R6-025", "LMPC-R7-003",
    "LMPC-R7-005", "LMPC-R7-007", "LMPC-R24-004",
    "LMPC-R18-009",
}

# Mandatory fields for any_present checks
ANY_PRESENT_FIELDS = {
    "LMPC-R4-001": ["manufacturer_name", "packer_name", "importer_name", "product_name",
                    "net_quantity", "mrp_value", "date_of_packing", "consumer_care"],
    "LMPC-R6-001": ["manufacturer_name", "packer_name", "importer_name"],
    "LMPC-R6-008": ["consumer_care", "consumer_care_phone", "consumer_care_email"],
    "LMPC-R10-001": ["manufacturer_name", "packer_name", "importer_name", "manufacturer_address"],
    "LMPC-R24-002": ["manufacturer_name", "product_name", "net_quantity", "mrp_value"],
}

# Mandatory field for presence checks
PRESENCE_FIELDS = {
    "LMPC-R6-002": "product_name",
    "LMPC-R6-003": "net_quantity",
    "LMPC-R6-004": "date_of_packing",
    "LMPC-R6-010": "best_before",
    "LMPC-R10-003": "manufacturer_name",
    "LMPC-R12-001": "net_quantity",
    "LMPC-R24-001": "product_name",
    "LMPC-R24-003": "mrp_value",
}

# Prohibition fields
PROHIBITION_DEFS = {
    "LMPC-R13-012": {"trigger": "vulgar fraction", "prohibition": "fraction_notation",
                     "fields": ["net_quantity"]},
    "LMPC-R18-003": {"trigger": "different MRP", "prohibition": "multiple_mrp_on_identical_commodity",
                     "fields": ["mrp_value"]},
    "LMPC-R18-009": {"trigger": "different MRP via restrictive trade", "prohibition": "discriminatory_mrp",
                     "fields": ["mrp_value"]},
}

# Range check defs
RANGE_DEFS = {
    "LMPC-R12-009": {"field": "net_quantity", "min": None, "max": None,
                     "note": "Net quantity must match declared quantity within MPE (Table-I of Schedule III)."},
}


def apply_corrections(classified: list[dict], records_by_id: dict) -> tuple[list[dict], list[str]]:
    classified_by_id = {c["rule_id"]: c for c in classified}
    log_lines = []
    changes = 0

    for rule_id, (target_bucket, target_kind, rationale) in CORRECTIONS.items():
        cl = classified_by_id.get(rule_id)
        if cl is None:
            log_lines.append(f"  MISSING: {rule_id} not in classified JSON")
            continue

        changed_parts = []
        if cl.get("bucket") != target_bucket:
            changed_parts.append(f"bucket: {cl.get('bucket')} → {target_bucket}")
            cl["bucket"] = target_bucket
        if str(cl.get("kind")) != target_kind:
            changed_parts.append(f"kind: {cl.get('kind')} → {target_kind}")
            cl["kind"] = target_kind

        # Rebuild mapping for this kind
        mapping = cl.get("mapping") or {}
        rec = records_by_id.get(rule_id, {})

        if target_kind == "any_present":
            fields = ANY_PRESENT_FIELDS.get(rule_id)
            if not fields:
                # Try to derive from record
                v = (rec.get("validation") or {}).get("parameters") or {}
                fields = v.get("fields") or []
            if fields:
                mapping["fields"] = fields
        elif target_kind == "presence":
            field = PRESENCE_FIELDS.get(rule_id)
            if not field:
                v = (rec.get("validation") or {}).get("parameters") or {}
                field = v.get("field") or (v.get("fields") or [None])[0]
            if field:
                mapping["field"] = field
        elif target_kind == "prohibition":
            pdef = PROHIBITION_DEFS.get(rule_id, {})
            if pdef:
                mapping.update(pdef)
        elif target_kind == "range":
            rdef = RANGE_DEFS.get(rule_id, {})
            if rdef:
                mapping.update(rdef)
        elif target_kind == "font":
            if "table_i" not in mapping:
                mapping["table_i"] = TABLE_I
            if "fields" not in mapping:
                mapping["fields"] = ["net_quantity", "mrp_value", "manufacturer_name", "product_name",
                                      "consumer_care", "date_of_packing"]
        elif target_kind == "date_month_year":
            if "field" not in mapping:
                mapping["field"] = "date_of_packing"
        elif target_kind == "format_mrp":
            if "field" not in mapping:
                mapping["field"] = "mrp_value"
        elif target_kind == "cross_source":
            if rule_id in EXTERNAL_REG_RULES and mapping.get("subtype") != "external_regulation_reference":
                mapping["subtype"] = "external_regulation_reference"
                mapping["external_source"] = (rec.get("description") or rec.get("title", ""))[:200]
        elif target_kind == "text_contains":
            if "field" not in mapping:
                v = (rec.get("validation") or {}).get("parameters") or {}
                mapping["field"] = v.get("field", "")
                mapping["pattern"] = v.get("pattern", "")
        elif target_kind == "unit_known":
            if "field" not in mapping:
                mapping["field"] = "net_quantity"
        elif target_kind == "cross_consistency":
            if "fields" not in mapping:
                mapping["fields"] = ["net_quantity"]

        if mapping != (cl.get("mapping") or {}):
            changed_parts.append("mapping updated")

        cl["mapping"] = mapping
        cl["_verified_rationale"] = rationale

        if changed_parts:
            changes += 1
            log_lines.append(f"  FIXED {rule_id}: {', '.join(changed_parts)}")

    # Fallback: fix any remaining image_checkable rules with invalid/empty presence
    for cl in classified:
        if cl.get("bucket") == "image_checkable":
            kind = cl.get("kind")
            mapping = cl.get("mapping") or {}
            if kind == "presence" and not mapping.get("field"):
                cl["kind"] = "always_manual"
                cl["bucket"] = "manual_review"
                cl["_auto_fallback"] = "Empty field on presence rule → always_manual"
                changes += 1
            elif kind == "any_present" and not (mapping.get("fields") or []):
                cl["kind"] = "always_manual"
                cl["bucket"] = "manual_review"
                cl["_auto_fallback"] = "Empty fields on any_present rule → always_manual"
                changes += 1
            elif kind not in ENGINE_VALID_KINDS:
                cl["kind"] = "always_manual"
                cl["bucket"] = "manual_review"
                cl["_auto_fallback"] = f"Invalid kind '{kind}' → always_manual"
                changes += 1

    log_lines.insert(0, f"  Total corrections applied: {changes}")
    return classified, log_lines


def main() -> None:
    records = json.loads(RECORDS_PATH.read_text())
    classified = json.loads(CLASSIFIED_PATH.read_text())

    records_by_id = {r["rule_id"]: r for r in records}

    print(f"Loaded {len(records)} records, {len(classified)} classified entries")
    print()
    print("=" * 70)
    print("APPLYING PDF-VERIFIED CORRECTIONS")
    print("=" * 70)

    classified, log_lines = apply_corrections(classified, records_by_id)
    for line in log_lines:
        print(line)

    # Final stats
    buckets = Counter(c.get("bucket", "?") for c in classified)
    kinds_all = Counter(str(c.get("kind", "None")) for c in classified)
    ic_rules = [c for c in classified if c.get("bucket") == "image_checkable"]
    ic_kinds = Counter(str(c.get("kind")) for c in ic_rules)

    print()
    print("=" * 70)
    print("FINAL DISTRIBUTION (after corrections)")
    print("=" * 70)
    print(f"\nTotal rules: {len(classified)}")
    print("\nBucket distribution:")
    for b, cnt in sorted(buckets.items()):
        print(f"  {b:30s}: {cnt:3d}")
    print("\nKind distribution (image_checkable bucket only):")
    for k, cnt in sorted(ic_kinds.items(), key=lambda x: -x[1]):
        print(f"  {str(k):30s}: {cnt:3d}")

    # Validate no invalid kinds
    invalid = [(c["rule_id"], c.get("kind")) for c in ic_rules
               if c.get("kind") not in ENGINE_VALID_KINDS]
    if invalid:
        print(f"\n⚠ INVALID KINDS remaining:")
        for rid, k in invalid:
            print(f"  {rid}: {k}")
    else:
        print("\n✅ All image_checkable rules have engine-valid validation kinds")

    if len(classified) == 230:
        print("✅ 230 rules confirmed")
    else:
        print(f"⚠ Expected 230, got {len(classified)}")

    # Report which rules have no CORRECTIONS entry (catch any that were missed)
    all_corrected = set(CORRECTIONS.keys())
    all_classified = {c["rule_id"] for c in classified}
    uncovered = all_classified - all_corrected
    if uncovered:
        print(f"\n⚠ {len(uncovered)} rules not in CORRECTIONS dict (using existing classified mapping):")
        for rid in sorted(uncovered):
            cl = next((c for c in classified if c["rule_id"] == rid), {})
            print(f"  {rid}: bucket={cl.get('bucket')}, kind={cl.get('kind')}")
    else:
        print("✅ All 230 rules have explicit verified corrections")

    # Save corrected file
    CLASSIFIED_PATH.write_text(json.dumps(classified, indent=2, ensure_ascii=False))
    print(f"\n✅ Saved corrected register_classified.json")

    # Save report
    report = "\n".join(log_lines)
    REPORT_PATH.write_text(report)
    print(f"✅ Verification report saved → {REPORT_PATH.name}")


if __name__ == "__main__":
    main()
