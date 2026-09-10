# Rule-register import — A0/A1/A2 evidence (230-record corrected register)

Working artifacts (all generated from the PDF, no prior JSON used):

| File | Contents |
|------|----------|
| `backend/data/register_records.json` | 230 fully-parsed records from `Legal_Metrology_..._CORRECTED_FINAL.pdf` |
| `backend/data/register_classified.json` | A1 bucket + A2 engine-kind mapping for all 230 |
| `backend/data/register_classification_report.txt` | Counts + needs_review list |
| `backend/tools/extract_register.py` | PDF -> 230 structured records (schema-driven, documented repairs) |
| `backend/tools/classify_rules.py` | A1 classification + A2 mapping |

## A0 — extraction confirmation

* 230 records, contiguous `1..230`; header text "Records included: 230" verified.
* Records carry the full register shape: `rule_id`, `rule_number`, `sub_rule`,
  `title`, `type`, `category`, `requirement {field, required, description}`,
  `applicability {commodity_type/channel/scope}`, `conditions`, `validation
  {type, validation_subtype?, parameters{…}}`, `severity`, `evidence_required`,
  `effective_from`, `effective_to`, `version`, `source`, `status`.
* Source register has genuine authoring defects, repaired transparently
  (logged per-record in `_repairs`, nothing silently invented):

  | seq | rule_id | defect | repair evidence |
  |-----|---------|--------|-----------------|
  | 1 | LMPC-R1-001 | PDF truncates record at page-wrap (no tail, desc. cut at "Rules,") | tail + "2011." reconstructed from sibling 1(2) / statutory short title |
  | 47 | LMPC-R6-003 | overlay merges version into `effective_to: null version 2011.0` | un-merged → `effective_to=null`, `version=2011.0` |
  | 179/189/214 | R24-003/R26-009/R33-002 | `effective_from: null` literal in PDF | filled from each record's own prose/sibling windows |
  | 223–230 | schedules | `RULE <Schedule>` separators + annex leaked into status/version | stripped; annex excluded from record bodies |
  | 13,36,62,97,175 | several | next record's amendment chain overlaid onto `version:` | version trimmed at first `" source "` |

  Residual QA scan is clean: no missing core fields except Schedule rows (which
  legitimately have no `sub_rule`) and legitimate version labels such as
  `2022.4-commencement-control` / `2011.0 + applicable amendments`.

## A1 — classification (register-faithful)

Counts across the 230 records (see full reasoning per record in
`register_classified.json`):

| Bucket | Count |
|--------|-------|
| image_checkable (evaluated per inspection) | 116 |
| legal_reference (stored, cited, excluded from select_rules) | 106 |
| manual_review (always MANUAL_REVIEW when applicable) | 8 |
| unclassified / needs_review | 0 |

Note: the register's own taxonomy differs from the prompt's assumed rule-level
types (the register uses `validation.type` = presence/unit/format/font_size/
prohibition/cross_* and rule `type` = compliance/procedure/definition/
exemption/conditional/prohibition/calculation), so classification is driven by
the register's real signals (rule.type × validation.type), which is the
defensible reading.

## A2 — mapping summary (image-checkable records)

| Engine validation.kind | Count |
|------------------------|-------|
| unit_known | 19 |
| any_present | 18 |
| range | 14 |
| cross_source | 8 |
| text_contains | 8 |
| always_manual | 7 |
| prohibition | 6 |
| cross_consistency | 5 |
| date_month_year | 3 |
| font (rule.type=font, Table-I bands preserved) | 2 |
| format_mrp | 1 |
| **needs_review** | **25** |

59 records carry a `needs_review` annotation with a specific reason (mostly
conditional triggers that must be resolved into `rule.conditions` + an
underlying kind, and format/legibility rules whose parameter block gives no
machine-usable pattern/threshold). Per the brief these must NOT be guessed;
they are listed record-by-record in the report file.
