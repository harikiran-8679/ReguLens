"""A3 — Import the 230-record classified register into the live DB.

Reads:
  backend/data/register_records.json      (A0 — full parsed records)
  backend/data/register_classified.json   (A1/A2 — bucket + kind mapping)

Actions:
  1. Ensures the `scope` column exists (idempotent ALTER TABLE).
  2. Clears dangling rule_results / findings / evidence / font_analyses /
     placement_analyses for ALL existing inspections (foreign-key safe).
  3. Replaces the entire `rules` table (TRUNCATE + restart identity) with the
     230 mapped records.
  4. Prints a summary and verification counts.

Usage:
    cd backend
    DATABASE_URL=postgresql+psycopg://lm_app:lm_secret_dev@localhost:5433/lm_inspection \\
        python tools/import_lmpc_rules.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
SRC_RECORDS = ROOT / "data" / "register_records.json"
SRC_CLASSIFIED = ROOT / "data" / "register_classified.json"

# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://lm_app:lm_secret_dev@localhost:5433/lm_inspection",
)

def _dsn(url: str) -> str:
    """Convert SQLAlchemy-style URL to psycopg DSN."""
    url = url.replace("postgresql+psycopg://", "postgresql://")
    return url


# ---------------------------------------------------------------------------
# Bucket → scope mapping
# ---------------------------------------------------------------------------
_SCOPE = {
    "image_checkable": "image_checkable",
    "legal_reference":  "reference",
    "manual_review":    "manual_review",
    "needs_review":     "deferred",      # stored but excluded from eval loop
}

# Kinds that should be excluded from the eval loop regardless of bucket
_DEFERRED_KINDS = {"needs_review"}

# ---------------------------------------------------------------------------
# Severity normalisation (register uses UPPER; DB uses lower)
# ---------------------------------------------------------------------------
_SEV = {"HIGH": "critical", "MEDIUM": "major", "LOW": "minor",
        "INFO": "info", "critical": "critical", "major": "major",
        "minor": "minor", "info": "info"}


def _sev(v: str | None) -> str:
    return _SEV.get((v or "MEDIUM").upper(), "major")


# ---------------------------------------------------------------------------
# Build engine validation dict from classified record
# ---------------------------------------------------------------------------
def _build_validation(rec_full: dict, classified: dict) -> dict:
    kind = classified.get("kind")
    mapping = classified.get("mapping") or {}
    bucket = classified.get("bucket", "legal_reference")
    v = (rec_full.get("validation") or {})
    params = v.get("parameters") or {}

    if kind is None or bucket == "legal_reference":
        return {"kind": "reference"}

    if kind == "always_manual":
        return {"kind": "always_manual"}

    if kind == "prohibition":
        return {
            "kind": "prohibition",
            "trigger": mapping.get("trigger") or params.get("trigger") or "",
            "prohibition": mapping.get("prohibition") or params.get("prohibition") or "",
            "fields": mapping.get("fields") or [],
        }

    if kind == "font":
        table_i = mapping.get("table_i") or {}
        # Parse the semicolon-separated mm values from Table-I
        normal_mm_str = table_i.get("normal_min_mm", "")
        blown_mm_str = table_i.get("blown_formed_molded_min_mm", "")
        try:
            normal_mm = [float(x.strip()) for x in normal_mm_str.split(";") if x.strip()]
            blown_mm = [float(x.strip()) for x in blown_mm_str.split(";") if x.strip()]
        except ValueError:
            normal_mm = []
            blown_mm = []
        # Derive a conservative min_ratio from the smallest Table-I value (1.0 mm)
        # expressed as a ratio of image height. Physical mm cannot be measured from
        # OCR alone — preserved as note per "OCR_only: cannot_establish_physical_mm".
        return {
            "kind": "font",
            "type": "font",
            "min_ratio": 0.020,          # relative image-height estimate only
            "fields": mapping.get("fields") or [],
            "table_i": {
                "row_selection": table_i.get("row_selection", ""),
                "normal_min_mm": normal_mm,
                "blown_formed_molded_min_mm": blown_mm,
                "measurement_unit": "mm",
                "area_unit": "cm2",
                "ocr_note": "cannot_establish_physical_mm — relative estimate only",
                "corrigendum": table_i.get("corrigendum", ""),
            },
        }

    if kind == "cross_consistency":
        return {"kind": "cross_consistency"}

    if kind == "cross_source":
        subtype = mapping.get("subtype", "")
        if subtype == "external_regulation_reference":
            return {
                "kind": "cross_source",
                "subtype": "external_regulation_reference",
                "external_source": mapping.get("external_source") or
                                   params.get("external_source", ""),
            }
        return {"kind": "cross_source"}

    if kind == "date_month_year":
        field = mapping.get("field", "date_of_packing")
        return {"kind": "date_month_year", "field": field}

    if kind == "unit_known":
        return {"kind": "unit_known"}

    if kind == "format_mrp":
        return {"kind": "format_mrp"}

    if kind == "text_contains":
        return {"kind": "text_contains",
                "pattern": mapping.get("pattern", ""),
                "field": mapping.get("field", "")}

    if kind == "any_present":
        fields = mapping.get("fields") or []
        if len(fields) == 1:
            return {"kind": "presence", "field": fields[0]}
        return {"kind": "any_present", "fields": fields}

    if kind == "range":
        return {"kind": "range",
                "field": mapping.get("field", ""),
                "min": mapping.get("min"),
                "max": mapping.get("max")}

    if kind == "needs_review":
        return {"kind": "needs_review"}

    if kind is None:
        return {"kind": "reference"}

    return {"kind": kind}


def _build_validation_type(classified: dict) -> str:
    """Map bucket/kind to the rule.type the engine dispatches on."""
    kind = classified.get("kind")
    if kind == "font":
        return "font"
    if kind in ("cross_consistency", "cross_source"):
        return "cross"
    if kind == "needs_review" or classified.get("bucket") == "legal_reference":
        return "reference"
    return classified.get("rule_type") or "content"


# ---------------------------------------------------------------------------
# Applicability: flatten to a list of commodity_type strings
# ---------------------------------------------------------------------------
def _applicability(rec: dict) -> list[str]:
    app = rec.get("applicability") or {}
    if not app:
        return ["*"]
    ct = app.get("commodity_type") or []
    if not ct:
        return ["*"]
    # "packaged_commodity" means all categories → represent as "*"
    if any("packaged_commodity" in str(c) for c in ct):
        return ["*"]
    return [str(c) for c in ct]


# ---------------------------------------------------------------------------
# Conditions: extract engine conditions dict
# ---------------------------------------------------------------------------
def _conditions(rec: dict) -> dict | None:
    cond = rec.get("conditions")
    if not cond:
        return None
    if isinstance(cond, dict):
        out: dict = {}
        if cond.get("imported") or cond.get("import_only"):
            out["imported"] = True
        if cond.get("domestic_only"):
            out["domestic_only"] = True
        if cond.get("min_grams"):
            out["min_grams"] = cond["min_grams"]
        if cond.get("shelf_life_months_le"):
            out["shelf_life_months_le"] = cond["shelf_life_months_le"]
        if cond.get("medical_device"):
            out["medical_device"] = True
        if cond.get("electronic_product"):
            out["electronic_product"] = True
        if cond.get("alcoholic_beverage"):
            out["alcoholic_beverage"] = True
        return out or None
    return None


# ---------------------------------------------------------------------------
# Source: flatten to string
# ---------------------------------------------------------------------------
def _source(rec: dict) -> str:
    src = rec.get("source") or {}
    if isinstance(src, dict):
        parts = []
        if src.get("document"):
            parts.append(src["document"])
        if src.get("provision"):
            parts.append(f"§{src['provision']}")
        if src.get("amendment"):
            parts.append(src["amendment"])
        return "; ".join(parts)
    return str(src)


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
def _date(v) -> dt.date | None:
    if v is None or v in ("null", "", "None"):
        return None
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------
_STATUS_MAP = {
    "active": "active",
    "historical": "historical",
    "future": "future",
    "omitted": "omitted",
    "superseded": "historical",
    "draft": "draft",
}


def _status(v: str | None) -> str:
    return _STATUS_MAP.get((v or "active").lower(), "active")


# ---------------------------------------------------------------------------
# Main import
# ---------------------------------------------------------------------------
def main() -> None:
    records = json.loads(SRC_RECORDS.read_text())
    classified_list = json.loads(SRC_CLASSIFIED.read_text())
    classified_by_id = {c["rule_id"]: c for c in classified_list}

    print(f"Loaded {len(records)} records from register_records.json")
    print(f"Loaded {len(classified_list)} classified entries")

    dsn = _dsn(DATABASE_URL)
    conn = psycopg.connect(dsn, autocommit=False)

    with conn:
        with conn.cursor() as cur:
            # 0. Ensure scope column exists
            cur.execute("""
                ALTER TABLE rules ADD COLUMN IF NOT EXISTS scope VARCHAR(20)
                    DEFAULT 'image_checkable';
                CREATE INDEX IF NOT EXISTS ix_rules_scope ON rules(scope);
            """)

            # 1. Clear child tables (FK-safe order)
            print("Clearing child data for all inspections...")
            cur.execute("DELETE FROM placement_analyses")
            cur.execute("DELETE FROM font_analyses")
            cur.execute("DELETE FROM evidence")
            cur.execute("DELETE FROM findings")
            print(f"  Cleared rule_results / findings / evidence / font / placement rows")

            # 2. TRUNCATE rules table and restart identity
            cur.execute("TRUNCATE TABLE rules RESTART IDENTITY CASCADE")
            print("  Rules table truncated")

            # 3. Insert all 230 records
            inserted = 0
            skipped = 0
            now = dt.datetime.now(dt.timezone.utc)

            for seq, rec in enumerate(records, start=1):
                rule_id = (rec.get("rule_id") or f"LMPC-UNKNOWN-{seq:04d}")[:48]
                cl = classified_by_id.get(rule_id, {})
                bucket = cl.get("bucket", "legal_reference")
                scope = _SCOPE.get(bucket, "reference")
                kind = cl.get("kind")
                # needs_review rules are stored as 'deferred' regardless of bucket
                if kind in _DEFERRED_KINDS:
                    scope = "deferred"

                # Build engine fields
                validation = _build_validation(rec, cl)
                rule_type = _build_validation_type(cl)
                applicability = _applicability(rec)
                conditions = _conditions(rec)
                source_str = _source(rec)
                sev = _sev(rec.get("severity"))
                eff_from = _date(rec.get("effective_from")) or dt.date(2011, 4, 1)
                eff_to = _date(rec.get("effective_to"))
                status = _status(rec.get("status"))
                req = rec.get("requirement") or {}
                description = req.get("description") or rec.get("title") or ""
                requirement_text = description
                field_name = req.get("field") or (
                    (cl.get("mapping") or {}).get("field") or
                    ((cl.get("mapping") or {}).get("fields") or [None])[0]
                )
                required_bool = req.get("required", True)
                if isinstance(required_bool, str):
                    required_bool = required_bool.lower() != "false"

                try:
                    version_int = int(str(rec.get("version") or "1").split(".")[0].replace("20", "20")[:4] or "1")
                except (ValueError, IndexError):
                    version_int = 1

                cur.execute("""
                    INSERT INTO rules (
                        rule_id, rule_number, sub_rule, title, type, category,
                        requirement, description, field, required,
                        applicability, conditions, validation,
                        severity, evidence_required,
                        effective_from, effective_to, version, source, status, scope,
                        sort_order, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s::json, %s::json, %s::json,
                        %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s
                    )
                """, (
                    rule_id,
                    str(rec.get("rule_number") or "")[:24],
                    str(rec.get("sub_rule") or "")[:24],
                    str(rec.get("title") or "")[:200],
                    rule_type[:24],
                    str(rec.get("category") or "general")[:40],
                    requirement_text,
                    description,
                    field_name,
                    bool(required_bool),
                    json.dumps(applicability),
                    json.dumps(conditions),
                    json.dumps(validation),
                    sev,
                    bool(rec.get("evidence_required", True)),
                    eff_from,
                    eff_to,
                    version_int,
                    source_str,
                    status,
                    scope,
                    seq * 10,  # sort_order
                    now,
                    now,
                ))
                inserted += 1

            conn.commit()
            print(f"\nInserted {inserted} rules, skipped {skipped}")

            # 4. Verification
            cur.execute("SELECT scope, COUNT(*) FROM rules GROUP BY scope ORDER BY scope")
            rows = cur.fetchall()
            print("\nScope breakdown:")
            for scope_val, count in rows:
                print(f"  {scope_val:20s} {count:4d}")

            cur.execute("SELECT status, COUNT(*) FROM rules GROUP BY status ORDER BY status")
            rows = cur.fetchall()
            print("\nStatus breakdown:")
            for status_val, count in rows:
                print(f"  {status_val:20s} {count:4d}")

            cur.execute("""
                SELECT validation->>'kind', COUNT(*)
                FROM rules
                WHERE scope IN ('image_checkable', 'manual_review')
                GROUP BY validation->>'kind'
                ORDER BY COUNT(*) DESC
            """)
            rows = cur.fetchall()
            print("\nValidation.kind breakdown (eval-scope rules only):")
            for kind_val, count in rows:
                print(f"  {str(kind_val):28s} {count:4d}")

            cur.execute("SELECT COUNT(*) FROM rules WHERE status='future'")
            fut_row = cur.fetchone()
            future_count = fut_row[0] if fut_row else 0
            print(f"\nFuture-dated rules (should be excluded from current-date queries): {future_count}")

    conn.close()
    print("\n✅ Import complete. Run the rule engine on existing inspections to rebuild rule_results.")


if __name__ == "__main__":
    main()
