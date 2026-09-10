"""Normalization module — a standalone, testable unit.

Converts raw OCR text variants into structured, comparable values for the field
catalogue (quantity, price/MRP, month-year dates). It is intentionally NOT inlined
into the OCR engine or the rule engine:

  * the OCR engine emits raw regions (`services/ocr.py`),
  * the matcher (`services/matcher.py`) normalizes raw text through THIS module
    and stores the normalized value alongside the original `raw_text`,
  * the rule engine (`services/rule_engine.py`) only ever receives the
    already-normalized product facts (ExtractedField rows) — never raw OCR text.

Every normalizer returns the original raw text alongside the normalized value so
evidence and audit trails keep the source string.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Quantity ("NET QTY: 5 kg", "5kg", "500 g", "1 litre", "250 GMS", "1 L")
# ---------------------------------------------------------------------------
_QTY_UNITS: dict[str, str] = {
    "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g", "gr": "g",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogram": "kg", "kilograms": "kg",
    "ml": "ml", "millilitre": "ml", "milliliter": "ml", "millilitres": "ml", "milliliters": "ml", "cc": "ml",
    "l": "l", "litre": "l", "liter": "l", "litres": "l", "liters": "l",
    "cl": "cl", "centilitre": "cl", "centiliter": "cl",
    "mg": "mg", "milligram": "mg", "milligrams": "mg",
}
_QTY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([a-zA-Z]+)", re.IGNORECASE)


def normalize_quantity(text: str) -> dict | None:
    """Extract {value, unit, display, raw_text} from raw quantity text.

    Handles '5 kg', '5kg', '5 KGS', '250 gms', '1 litre', '500 ml', 'NET QTY: 5 kg'.
    Returns None when no parseable quantity is present (unit unknown / no digits).
    """
    raw = (text or "").strip()
    for m in _QTY_RE.finditer(raw):
        num = float(m.group(1))
        unit_raw = m.group(2).lower()
        if unit_raw in _QTY_UNITS:
            unit = _QTY_UNITS[unit_raw]
            display = f"{_fmt_num(num)} {unit}"
            return {"value": round(num, 4), "unit": unit, "display": display, "raw_text": raw}
    return None


def quantity_to_grams(value: str | float, unit: str | None = None) -> float | None:
    """Normalise a quantity to grams for cross-field comparisons."""
    if unit is None:
        hit = normalize_quantity(value if isinstance(value, str) else f"{value}")
        if hit is None:
            return None
        num, unit = hit["value"], hit["unit"]
    else:
        num = float(value)
        unit = unit.lower()
    if unit in ("g", "mg", "ml", "l", "cl"):
        pass
    if unit == "g":
        return num
    if unit == "kg":
        return num * 1000
    if unit == "mg":
        return num / 1000
    if unit == "ml":
        return num  # ml ≈ g for threshold purposes
    if unit == "l":
        return num * 1000
    if unit == "cl":
        return num * 10
    return None


def _fmt_num(num: float) -> str:
    if num == int(num):
        return str(int(num))
    return str(round(num, 4)).rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Price / MRP ("₹450", "Rs. 450", "M.R.P. Rs.450 (Inclusive of all taxes)",
#              "MRP ₹ 50", "INR 49.50", "450")
# ---------------------------------------------------------------------------
_AMOUNT_RE = re.compile(
    r"(?:rs\.?|inr|₹|\$|rupees?)\s*(\d+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)


def normalize_amount(text: str) -> dict | None:
    """Extract {value, currency, display, raw_text} from raw price text.

    Currency detection: ₹ / 'Rs.' / 'INR' -> INR; '$' -> USD; bare digits -> INR
    (the label is Indian retail packaging, MRP is always INR). Preserves raw text.
    Handles thousands separators ('₹ 1,200.00').
    """
    raw = (text or "").strip()
    m = _AMOUNT_RE.search(raw.replace(",", ""))
    if not m:
        return None
    value = float(m.group(1) if m.group(1) else m.group(2))
    lower = raw.lower()
    currency = "USD" if "$" in raw else ("INR" if ("₹" in raw or "rs" in lower or "inr" in lower or "rupee" in lower) else "INR")
    display = f"₹{_fmt_num(value)}" if currency == "INR" else f"${_fmt_num(value)}"
    return {"value": value, "currency": currency, "display": display, "raw_text": raw}


# ---------------------------------------------------------------------------
# Month-year dates ("AUG 2026", "Aug-2026", "08/2026", "Packed: 08-2026",
#                   "AUGUST 2026", "AUG. 2026")
# ---------------------------------------------------------------------------
_MONTHS = {
    "JAN": "JAN", "JANUARY": "JAN", "FEB": "FEB", "FEBRUARY": "FEB",
    "MAR": "MAR", "MARCH": "MAR", "APR": "APR", "APRIL": "APR",
    "MAY": "MAY", "JUN": "JUN", "JUNE": "JUN", "JUL": "JUL", "JULY": "JUL",
    "AUG": "AUG", "AUGUST": "AUG", "SEP": "SEP", "SEPT": "SEP", "SEPTEMBER": "SEP",
    "OCT": "OCT", "OCTOBER": "OCT", "NOV": "NOV", "NOVEMBER": "NOV",
    "DEC": "DEC", "DECEMBER": "DEC",
}
_MONTH_ABBR = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_MONTH_NAME_RE = re.compile(
    r"\b(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER|"
    r"JAN|FEB|MAR|APR|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)[A-Z]*[\s./\-]*(\d{4})\b",
    re.IGNORECASE,
)
_MONTH_NUM_RE = re.compile(r"\b(\d{1,2})[\s./\-](\d{4})\b")


def normalize_date_month_year(text: str) -> dict | None:
    """Extract {value: 'AUG 2026', raw_text} from month/year date text."""
    raw = (text or "").strip()
    m = _MONTH_NAME_RE.search(raw)
    if m:
        month = _MONTHS[m.group(1).upper()]
        year = m.group(2)
        return {"value": f"{month} {year}", "raw_text": raw}
    m = _MONTH_NUM_RE.search(raw)
    if m:
        mon = int(m.group(1))
        if 1 <= mon <= 12:
            return {"value": f"{_MONTH_ABBR[mon - 1]} {m.group(2)}", "raw_text": raw}
    return None