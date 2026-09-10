"""Field-matching layer: maps raw OCR text to canonical declaration fields.

THE ROLE OF THIS LAYER (and the optional LLM behind it) is strictly:
    text -> field name (and a normalised value)
It NEVER evaluates compliance, never returns PASS/FAIL and never cites rules.
All pass/fail/review decisions live in the deterministic rule engine.

A deterministic matcher is the default so the prototype is fully offline;
when FIELD_MATCHER=ollama the OllamaFieldMatcher is consulted first for lines
the deterministic pass could not classify, using a strict JSON-only prompt.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field

from ..config import settings
from .normalizer import normalize_amount, normalize_date_month_year, normalize_quantity
from .ocr import OcrRegion

# Confidence bands (configurable thresholds used across the UI)
HIGH_CONF = 0.90   # green  — definitely detected
LOW_CONF = 0.65    # below -> definitely needs verification

# Canonical field catalogue used by extraction + rule engine + UI
FIELD_CATALOG: dict[str, dict] = {
    "product_name": {"label": "Product Name", "category": "product"},
    "brand": {"label": "Brand", "category": "product"},
    "product_type": {"label": "Product Type / Variant", "category": "product"},
    "net_quantity": {"label": "Net Quantity", "category": "quantity"},
    "items_count": {"label": "Number of Items", "category": "quantity"},
    "mrp_value": {"label": "MRP (Retail Sale Price)", "category": "price"},
    "inclusive_taxes_phrase": {"label": "“Inclusive of all taxes” wording", "category": "price"},
    "manufacturer_name": {"label": "Manufacturer Name", "category": "manufacturer"},
    "manufacturer_address": {"label": "Manufacturer / Packer Address", "category": "manufacturer"},
    "packer_name": {"label": "Packer Name", "category": "manufacturer"},
    "importer_name": {"label": "Importer Name", "category": "manufacturer"},
    "importer_address": {"label": "Importer Address", "category": "manufacturer"},
    "consumer_care_number": {"label": "Consumer Care Number", "category": "consumer"},
    "consumer_email": {"label": "Consumer Care Email", "category": "consumer"},
    "consumer_website": {"label": "Consumer Care Website", "category": "consumer"},
    "date_of_packing": {"label": "Month & Year of Packing / Manufacture", "category": "dates"},
    "best_before": {"label": "Best Before / Use By", "category": "dates"},
    "expiry_date": {"label": "Expiry Date", "category": "dates"},
    "country_of_origin": {"label": "Country of Origin", "category": "origin"},
    "other": {"label": "Other Detected Text", "category": "other"},
}

MANDATORY_FIELD_SET = [
    "product_name", "manufacturer_name", "manufacturer_address", "net_quantity",
    "date_of_packing", "mrp_value", "inclusive_taxes_phrase", "consumer_care_number",
    "country_of_origin", "best_before",
]


@dataclass
class FieldHit:
    field: str
    value: str
    raw: str
    confidence: float
    rule_name: str = ""          # which pattern matched (auditability)


_PREFIX_STRIP = r"^\s*(?:manufactur(?:ed|er)?|pack(?:ed|er)?|import(?:ed|er)?|mfd|mfr|by|for)\b[:\-.]*\s*"

_PATTERNS: list[tuple[str, str, str | None, float]] = [
    # (regex, field, value-template-or-None, conf multiplier)
    (r"\bm\.?r\.?p\.?\b|max(?:imum)?\s+retail\s+price|\bretail\s+price\b|\bmrp\b", "mrp_value", None, 0.99),
    (r"incl(?:usive)?\.?\s+of\s+all\s+taxes|incl\s+all\s+taxes", "inclusive_taxes_phrase", "present", 0.97),
    (r"net(?:\.)?\s*(?:qty|quantity|weight|wt|contents|content)\b", "net_quantity", None, 0.98),
    (r"\bno\.?\s*(?:of)?\s*(?:items|pieces|count|pcs)\b|net\s+count", "items_count", None, 0.95),
    (r"consumer\s*(?:care|counselling|grievance)|customer\s*care|toll\s*free", "consumer_care_number", None, 0.96),
    (r"country\s+of\s+origin|made\s+in\b", "country_of_origin", None, 0.97),
    (r"\bpacked\s*(?:on|in|at|by)?\b|packing\s*(?:date|month)|m\.?f\.?g\.?\s*(?:date|month)|date\s+of\s+manufacture|manufactur\w*\s*(?:on|date|month)", "date_of_packing", None, 0.92),
    (r"best\s*-?\s*before|use\s*-?\s*by|best\s+before\s+end", "best_before", None, 0.96),
    (r"expiry\s*:|exp\.?\s*date|expires?\b", "expiry_date", None, 0.95),
    (r"\bwww\.[\w.\-/]+\b|https?://", "consumer_website", None, 0.98),
    (r"[\w.+-]+@[\w-]+\.[\w.]+", "consumer_email", None, 0.97),
]

_ENTITY_KEYWORD = re.compile(
    r"\b(manufactur(?:ed|er|ing)?|pack(?:ed|er|ing)?|import(?:ed|er|ing)?|mfd|mfr|bottled\s+by|distribut(?:ed|or)?\s+by)\b",
    re.IGNORECASE,
)
_ADDRESS_HINT = re.compile(r"(p\.?o\.?|street|road|rd|nagar|colony|layout|industrial|estate|hyderabad|telangana|mumbai|delhi|bangalore|chennai|kolkata|pune|ahmedabad|gurgaon|noida|india|\b\d{6}\b)", re.IGNORECASE)
_CITY_ONLY = re.compile(r"^(hyderabad|telangana|mumbai|maharashtra|delhi|ncr|new delhi|bangalore|karnataka|chennai|tamil nadu|kolkata|west bengal|pune|gurgaon|haryana|noida|uttar pradesh|ahmedabad|gujarat|india)[,.\s]*$", re.IGNORECASE)
_PHONE = re.compile(r"(?:\+?91[\s-]?)?(?:1[89]00[\s-]?\d{3}[\s-]?\d{4}|\d{3,5}[\s-]\d{3,5}[\s-]\d{3,5}|\d{10,12})")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_QTY_GENERIC = re.compile(r"(\d+(?:\.\d+)?)\s*$")


def _normalise_quantity(raw: str) -> str | None:
    """Normalise a quantity string via the shared normalizer module."""
    hit = normalize_quantity(raw)
    if hit:
        return hit["display"]
    m = _QTY_GENERIC.search(raw)
    if m:
        return m.group(1)
    return None


def _strip_label(text: str) -> str:
    return re.sub(_PREFIX_STRIP, "", text).strip(" :.-–—").strip()


def classify_line(region: OcrRegion) -> list[FieldHit]:
    """Classify one OCR region into zero or more field hits (never a verdict)."""
    text = region.text.strip()
    if not text:
        return []
    lower = text.lower()
    hits: list[FieldHit] = []

    # price / wording / contact patterns with value extraction
    if re.search(r"\bm\.?r\.?p\.?\b|max(?:imum)?\s+retail\s+price|\bretail\s+price\b|\bmrp\b", lower):
        amount = normalize_amount(text)
        value = amount["display"] if amount else text
        hits.append(FieldHit("mrp_value", value, text, round(region.confidence * 0.99, 4), "mrp_pattern"))

    if re.search(r"incl(?:usive)?\.?\s+of\s+all\s+taxes", lower):
        hits.append(FieldHit("inclusive_taxes_phrase", "present", text, round(region.confidence * 0.99, 4), "taxes_wording"))

    if re.search(r"net(?:\.)?\s*(?:qty|quantity|weight|wt|contents)\b", lower):
        q = _normalise_quantity(text)
        if q:
            hits.append(FieldHit("net_quantity", q, text, round(region.confidence * 0.99, 4), "net_qty_value"))
        else:
            hits.append(FieldHit("net_quantity", text, text, region.confidence, "net_qty_raw"))
    elif re.search(r"\bno\.?\s*(?:of)?\s*(?:items|pieces|pcs)\b|net\s+count", lower):
        q = _normalise_quantity(text)
        if q:
            hits.append(FieldHit("items_count", q, text, round(region.confidence * 0.98, 4), "item_count"))

    if re.search(r"consumer\s*(?:care|counselling)|customer\s*c(a|a)re|toll\s*free|customer\s*support|1800-", lower):
        phone = _PHONE.search(text)
        email = _EMAIL.search(text)
        if phone:
            hits.append(FieldHit("consumer_care_number", phone.group(0).strip(), text,
                                 round(region.confidence * 0.99, 4), "consumer_phone"))
        elif email:
            hits.append(FieldHit("consumer_email", email.group(0), text, round(region.confidence * 0.97, 4), "consumer_email"))

    if re.search(r"country\s+of\s+origin|made\s+in\b", lower):
        value = _strip_label(text.split(":", 1)[-1]) if ":" in text else _strip_label(re.sub(r"country\s+of\s+origin|made\s+in", "", text, flags=re.I))
        if value:
            hits.append(FieldHit("country_of_origin", value, text, round(region.confidence * 0.97, 4), "origin"))

    if re.search(r"\b(best\s*-?\s*before|use\s*-?\s*by)\b", lower):
        value = _strip_label(text.split(":", 1)[-1]) if ":" in text else _strip_label(re.sub(r"best\s*-?\s*before|use\s*-?\s*by", "", text, flags=re.I))
        hits.append(FieldHit("best_before", value or text, text, round(region.confidence * 0.96, 4), "best_before"))

    if re.search(r"\bexpiry\b|exp\.?\s*date", lower) and not hits:
        value = _strip_label(text.split(":", 1)[-1]) if ":" in text else text
        hits.append(FieldHit("expiry_date", value or text, text, region.confidence, "expiry"))

    date_hit = normalize_date_month_year(text)
    date_kw = re.search(r"packed|packing|mfg|manufactur|date of (?:packing|manufacture)|import", lower)
    if date_hit and date_kw:
        hits.append(FieldHit("date_of_packing", date_hit["value"], text,
                             round(region.confidence * 0.98, 4), "month_year"))

    if not any(h.field.startswith("consumer_") for h in hits):
        email = _EMAIL.search(text)
        if email:
            hits.append(FieldHit("consumer_email", email.group(0), text,
                                 round(region.confidence * 0.95, 4), "email"))
        if re.search(r"\bwww\.|https?://", lower):
            m = re.search(r"(?:www\.)?[\w.\-/]+", text)
            hits.append(FieldHit("consumer_website", m.group(0) if m else text, text,
                                 round(region.confidence * 0.95, 4), "website"))

    return hits


_ENTITY_SKIP = re.compile(
    r"retail sale|marketed for|storage|customer\s*(?:care|support)|toll\s*free|"
    r"best\s+-?\s*before|use\s+-?\s*by|expir|months?\s+from", re.IGNORECASE)
# date-style statements like "Packed: AUG 2026" / "Packed on 15-08-2026" are not packers
_PACK_DATE_STATEMENT = re.compile(
    r"\bpacked\s*(?:on|in|at)?\s*[:.]?\s*(?:"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4})",
    re.IGNORECASE)


def _entity_value(text: str) -> str:
    """Strip a leading 'Manufactured & Packed by:'-style header to the name/address."""
    m = re.match(r"^\s*(.*?[:.])\s*(.*)$", text, re.S)
    if m:
        prefix, rest = m.group(1), m.group(2).strip()
        if _ENTITY_KEYWORD.search(prefix) and rest and len(rest) >= 2:
            # keep a trailing full-stop (e.g. "Pvt. Ltd.") but drop other debris
            return re.sub(r"^[\s,;:]+|[\s,;:]+$", "", rest)
    return _strip_label(text)


def classify_entity_line(region: OcrRegion) -> FieldHit | None:
    """Manufacturer / packer / importer line detection (name + address heuristics)."""
    text = region.text.strip()
    lower = text.lower()
    if not text or _ENTITY_KEYWORD.search(text) is None:
        return None
    if _ENTITY_SKIP.search(lower):
        return None
    if "manufactur" in lower or re.search(r"\bmfd\b|\bmfr\b", lower):
        kind = "manufacturer_name"
    elif "pack" in lower:
        # "packed on/in/at + date", "packing date" etc. describe the date, not a packer
        if _PACK_DATE_STATEMENT.search(lower) and not re.search(r"by\b", lower):
            return None
        kind = "packer_name"
    elif "import" in lower:
        kind = "importer_name"
    else:
        return None
    value = _entity_value(text)
    if not value or len(value.split()) < 2:
        return None
    return FieldHit(kind, value, text, round(region.confidence * 0.97, 4), "entity_keyword")


def classify_plain_line(region: OcrRegion, top_zone: bool, is_tallest: bool) -> FieldHit | None:
    """Fallback for lines with no keyword: address hints, origin, then product name."""
    text = region.text.strip()
    lower = text.lower()
    if not text:
        return None
    if re.search(r"consumer|care|customer|retail sale|marketed for|storage", lower):
        return None
    if _CITY_ONLY.search(text) or _ADDRESS_HINT.search(text):
        return FieldHit("manufacturer_address", text, text, round(region.confidence * 0.99, 4), "address_hint")
    if top_zone and (is_tallest or region.y < 0.28):
        return FieldHit("product_name", text, text, round(region.confidence * 0.98, 4), "heading_fallback")
    return None


def default_bands(confidence: float) -> str:
    """Map a confidence to the field status vocabulary (DETECTED/UNCERTAIN)."""
    if confidence >= HIGH_CONF:
        return "DETECTED"
    return "UNCERTAIN"


# ---------------------------------------------------------------------------
# Optional LLM matcher (strictly field mapping, never compliance)
# ---------------------------------------------------------------------------
class OllamaFieldMatcher:
    """Asks a local model (Ollama/Qwen) to label *unclassified* OCR lines only.

    Prompt is constrained to output a JSON object {region_index: field_name}
    drawn from the canonical catalogue, and explicitly forbids compliance talk.
    """

    def __init__(self) -> None:
        self.base = settings.OLLAMA_BASE_URL.rstrip("/")
        self.model = settings.OLLAMA_MODEL
        self.timeout = settings.LLM_TIMEOUT_SECONDS

    def available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310
                return resp.status == 200
        except Exception:
            return False

    def match(self, lines: list[str]) -> dict[int, str]:
        catalogue = ", ".join(field for field in FIELD_CATALOG if field != "other")
        sys_prompt = (
            "You map printed commodity-label text to a canonical field name. "
            "You only perform field identification — you never judge legal compliance. "
            f"Allowed field names: {catalogue} or \"other\". "
            "Reply with valid JSON only: {\"<index>\": \"<field_name>\"} for the lines you can classify."
        )
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": "Classify these OCR lines (index: text):\n" +
                 "\n".join(f"{i}: {t}" for i, t in enumerate(lines))},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0},
        }).encode()
        req = urllib.request.Request(
            f"{self.base}/api/chat", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                payload = json.loads(resp.read().decode())
            content = payload.get("message", {}).get("content", "")
            parsed = json.loads(content)
        except Exception:
            return {}
        result: dict[int, str] = {}
        for k, v in parsed.items():
            try:
                idx = int(k)
            except (TypeError, ValueError):
                continue
            if isinstance(v, str) and v in FIELD_CATALOG and v != "other":
                result[idx] = v
        return result
