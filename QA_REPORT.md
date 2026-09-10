# QA / Verification Report — Legal Metrology Inspection Platform

Date: 2026-09-05 · Stack under test: FastAPI (Docker) + PostgreSQL 16 + React 18 frontend ·
OCR engine used in this pass: **tesseract 5.5 (real OCR, installed in the API image)** ·
Field matcher: deterministic demo matcher (Ollama path dormant — see §2).

Method: everything below was *run*, not described. Real OCR was executed inside the API
container on rendered label images (photoised with shading/noise/JPEG artefacts), real OpenCV
quality analysis ran on those pixel buffers, results were persisted through the actual
pipeline services (`run_ocr → run_field_matching → run_rule_analysis`), and the UI was driven
with Puppeteer against real clickable flows. Screenshots: `/tmp/qa/ui/*.png`.

**Verdict summary:** §1 PASS(with caveats) · §2 PASS(boundary) with 2 heuristic notes ·
§3 PARTIAL — 5 real OpenCV checks proven, 3 stubbed/calibrated-out · §4 PASS · §5 PASS.
This pass surfaced and fixed **7 real bugs** (see end) and confirmed the honest boundaries
between real analysis and simulation.

---

## §1 OCR + field-extraction + rule matching (real OCR)

Ran the actual tesseract path over 4 photoised variants of a known label
(product, net qty, MRP+“inclusive of all taxes”, best-before, mfg name, address, pack date).
Per-stage output is reproduced below from the run (`backend/app` pipeline used directly).

**Stage 1 — quality (OpenCV, real):** clean → `overall=good, ocr_suitability=good`
(blur 0.00, glare 0.02, lighting good). Blurry (σ2.2) → `poor`, blur **fail**
“Image is too blurry for reliable OCR…” blurriness 0.99. Glare band → glare **warn**
(9.7% of pixels overexposed) + text under the band destroyed in OCR. Dark 0.35× →
lighting **warn** “Lighting is uneven…” + softness warn. **Specific messages, not generic.**

**Stage 2 — raw OCR (real tesseract, verbatim):**
```
conf=95%  bbox=(0.081,0.086,0.833,0.045)  'ABC PREMIUM RICE'
conf=94%  bbox=(0.177,0.233,0.648,0.063)  'NET QTY: 5 kg'
conf=93%  bbox=(0.113,0.448,0.773,0.026)  'M.R.P. Rs.450 (Inclusive of all taxes)'
conf=96%  bbox=(0.235,0.557,0.530,0.022)  'Best Before: 6 Months from Packing'
conf=95%  bbox=(0.076,0.694,0.847,0.026)  'Manufactured & Packed by: ABC Foods Pvt. Ltd.'
conf=95%  bbox=(0.108,0.766,0.785,0.021)  'Plot 42, Industrial Estate, Hyderabad, Telangana - 500 001'
conf=96%  bbox=(0.346,0.871,0.309,0.020)  'Packed: AUG 2026'
```

**Stage 3 — normalisation + mapping + diff table (expected = declared ground truth):**

| field | expected | extracted | match | conf | rule fired |
|---|---|---|---|---|---|
| product_name | ABC PREMIUM RICE | ABC PREMIUM RICE | ✓ | 93% | heading_fallback |
| net_quantity | 5 kg | 5 kg | ✓ | 94% | net_qty_value |
| mrp_value | ₹450 | ₹450 | ✓ | 93% | mrp_pattern |
| inclusive_taxes_phrase | present | present | ✓ | 93% | taxes_wording |
| best_before | 6 Months from Packing | 6 Months from Packing | ✓ | 92% | best_before |
| manufacturer_name | ABC Foods Pvt. Ltd. | ABC Foods Pvt. Ltd. | ✓ | 92% | entity_keyword |
| manufacturer_address | Hyderabad, Telangana - 500 001 | Plot 42, …, 500 001 | ✓ | 94% | address_hint |
| date_of_packing | AUG 2026 | AUG 2026 | ✓ | 94% | month_year |

**Degraded-variant behaviour (non-happy path, this is the point):**
- **Blurry**: OCR still readable but MRP + address confidences drop to 88–89%; one character
  misread (“Pilot 42”). No silent accept.
- **Glare band across the label**: OCR genuinely destroyed — `'ABC PR’ UM RICE'`,
  `'NET Y¥:5kg'`, `'M.R.P. P Inclusive of all taxes)'`, mfg line truncated. Extraction left
  those fields **missing/unclassified** (best_before, net_quantity, manufacturer_name
  MISSING; mrp value garbage). This is the desired three-state behaviour: nothing force-fit,
  downstream rule engine treats absence per coverage/manual-review rules.
- **Dark 0.35×**: still legible to tesseract → 8/8 exact matches; quality engine still warns.

**Rule engine on the clean product (full DB run, real services):**
`run_rule_analysis` selected 19 rules (5 not applicable — imported-only, <50 g exemptions,
short-shelf-life conditions) → **19 evaluated, 19 passed → automated COMPLIANT**.
Coverage note: “Front and rear/side panels captured — adequate…” Rule-7 font rows and
Rule-8 placement/spacing rows evaluated per-declaration. (The failing-label scenario in the
seeded demo — missing tax-inclusive wording, tiny MRP font, no consumer care — resolves to
🔴 NON-COMPLIANT with review items; so both verdicts are reachable and were exercised.)

**Thresholds (where to tune):** `HIGH_CONF = 0.90` (→ `detected`), `LOW_CONF = 0.65`
(below → needs verification) in `backend/app/services/matcher.py`. Pipeline assigns
`detected` only at ≥ HIGH_CONF, else `uncertain`; the rule engine converts unverified
`uncertain` to **MANUAL REVIEW** (`rule_engine._state`), and `not detected` after adequate
coverage to potential FAIL. OCR engine confidence floor: 25% (`ocr.py`).

**Caveats (honest):**
- “Real packaged-commodity photo” here = photoised render (gradient, noise, JPEG). True field
  photos still need threshold calibration; tesseract ≠ the PaddleOCR primary, but the engine
  contract is identical (see fix below) so Paddle can be swapped in via `OCR_ENGINE=paddle`.
- OCR word→line grouping was added to `TesseractEngine` so its output honours the same
  line-region contract Paddle emits natively.

## §2 LLM integration boundary (field matching only)

**Exact prompt captured** by intercepting the request the `OllamaFieldMatcher` builds
(`model qwen2.5:7b`, `temperature 0.0`, `format json`):
> system: “You map printed commodity-label text to a canonical field name. You only perform
> field identification — you never judge legal compliance. Allowed field names: product_name,
> …, country_of_origin or "other". Reply with valid JSON only: {"<index>": "<field_name>"} …”

No compliance/violation language anywhere. **Call site:** `pipeline.run_field_matching` only
(`if settings.FIELD_MATCHER == "ollama" and llm.available()`), only for lines the
deterministic matcher left unclassified. Output parsed as strict JSON; **unparseable reply or
timeout → `{}` (graceful, nothing guessed)** — demonstrated by mocking an unparseable model
reply (`{}` returned) and by confirming `available() == False` when Ollama is down, in which
case extraction simply continues deterministically (the inspection does not fail).
**Hard separation:** `rule_engine.py` imports from matcher only the constant `HIGH_CONF`;
matcher imports nothing from the engine; there is no LLM call anywhere in
`rule_engine.py`, `analysis.py`, or the review/report routers.

**Edge cases (no force-fit):** stray phone `Reach us at 9866 123 456…` → unclassified;
random landline → unclassified; bare `15/08/2026` / `AUG 2026` → unclassified; garbled
`NET Y¥:5kg` → unclassified; `Rs. 50` alone → unclassified. Legit `Mfg date: AUG 2026` →
`date_of_packing`; `Packed by: Sunrise Foods, B-7 MIDC Pune` → `packer_name`; a standalone
`www.vendor.example` → maps to `consumer_website` even without consumer context (heuristic
over-match — flagged PARTIAL, easy to tighten by requiring a contact keyword).
**Determinism:** pure-regex matcher returns identical output run-to-run (verified);
Ollama is temp 0 + JSON and only consults unclassified lines. **Demo vs real engine:** demo
mode = the deterministic rule-based matcher (no network, no model). Switching
`FIELD_MATCHER=ollama` does not change the input/output contract of the pipeline
(index→canonical-field mapping).

## §3 Computer-vision / capture checks — real vs simulated (by check)

| Check | Real analysis? | How / where | Result |
|---|---|---|---|
| Blur | ✅ real | Laplacian variance, `quality.py` | fixed **inverted metric** found by QA; now fails correctly on σ2.2 blur |
| Lighting (dark/overexposed distinct) | ✅ real | mean + overbright/dark ratios | dark 0.35× → “Lighting is uneven…”; distinct thresholds for low-light vs overbright |
| Glare/reflection | ⚠️ real but **no mask geometry** | % pixels >245 | band detected (warn/fail) but no glare *region/mask* output — proxy only |
| Framing/package detection | ✅ real | Canny edge density centre vs frame | “well framed”; empty/low-edge image → “Package not detected…” |
| Orientation/tilt | ✅ real | Sobel angle distribution | tilt > 12° → “Package appears tilted…” |
| Text visibility | ✅ derived | blend of blur+glare | matches OCR reality (glare image → text_visibility 0.91 warn) |
| Focus | ⚠️ merged into blur | — | no separate focus metric — PARTIAL |
| Distance (too close/far) | ❌ **not implemented** | — | no distance estimation exists; framing edges serve as proxy — PARTIAL |
| Coverage tracking | ✅ real | `images.py` list + DB | uploads front→back update coverage; next-shot guidance on Capture page |
| Duplicate capture | ✅ real (exact) | SHA-256 hash vs same-inspection images | same file 2nd upload → `is_duplicate=true, duplicate_of=IMG-…-01` (proved via API) |
| Blur/glare *blocking* | ⚠️ advisory | quality stored; capture UI shows live messages | app does not hard-block upload — upload proceeds with manual-review outcomes |

The glare/dark/blur/flat-white calibration note applies: thresholds are heuristics tuned for
phone photos; a fully-white synthetic render triggers the glare/overbright proxy — see §1.

## §4 Database functionality

Schema (Postgres, actual): 16 tables — `users, inspections, images, ocr_results,
extracted_fields, rules, rule_results, findings, font_analyses, placement_analyses,
evidence, reports, audit_logs, product_categories` + 2 support tables; per-table columns
listed in the run output (e.g. `ocr_results`: id, inspection_id, image_id, region_id, text,
confidence, bbox… — **every extracted_field / finding carries source image + bbox + region**).
- **Per-inspector scoping**: API-level proof — inspector `LM-INS-00125` requesting inspection
  owned by `LM-INS-00131` → 403; each inspector’s dashboard/list returns only own rows.
- **Admin aggregates**: cross-inspector totals queryable (`/api/dashboard/admin`, SQL
  aggregate over all inspectors — total/finalized/compliant/non_compliant).
- **Date-aware rule versioning**: before fix, superseded historical versions were excluded
  even for past dates (a 2016 inspection would not get the 2011 font rule). Fixed in
  `rule_engine.select_rules` (exclude only `draft`; window governs). Now: inspection dated
  2016 → `PC-R7-1` (2011, superseded 2018) in force; dated 2026 → `PC-R7-2` (amended);
  dated 2008 → no font rule. Draft rows never selected.
- **Evidence chain (seeded LM-2026-00129)**: finding `F-001` (date decl.) →
  source_image `IMG-00129-01` front, `storage_path samples/LM-2026-00129/front.jpg`
  (**file exists on disk**) → field `date_of_packing` value `AUG 2026`, bbox
  `{x:0.357,y:0.867,w:0.286,h:0.032}` → raw OCR `'Packed: AUG 2026'` conf **0.54**
  (this low-confidence row is precisely why it sits in 🟡 manual review, not fail/pass).

## §5 UI / UX flow

Puppeteer drove the **real review flow on a QA inspection** (4 automated findings):
opened the review board → clicked “🔴 Requirement not satisfied” on each of 4 findings with an
inspector note → typed and saved the observation → selected 🔴 NON-COMPLIANT + final remarks →
**Finalize**. All persisted: DB shows `status=finalized, reviewed_by=LM-INS-00125`,
4 findings `confirmed + not_satisfied + notes`; report preview now renders
`NON-COMPLIANT`, the observation, final remarks, all four inspector notes, and reviewer.
**Three states visually distinct & verified in UI:** 🟢 COMPLIANT (LM-2026-00128 finalised
report) · 🔴 NON-COMPLIANT (QA run + seeded LM-2026-00126/129) · 🟡 manual-review items
(LM-2026-00129 result page shows review-required items). Screenshots in `/tmp/qa/ui/`.
No console errors across the flows.

**Bugs the UI walk caught and I fixed:** review “Save decision” called `PATCH /findings/{id}`
but the route is `/inspections/findings/{id}` (UI decisions were 404ing); report preview
showed the result as `NON_COMPLIANT` and omitted final remarks + inspector notes (now shown).
Review overrides keep the engine result in the audit trail (`review.py` maps to
inspector_status while `engine_result` is untouched).

## Bugs found & fixed during this QA pass

1. **Blur metric inverted** in `quality.py` — sharp images failed “too blurry”, blurred ones passed.
2. **Date-aware rule selection ignored superseded-but-then-effective versions** (`select_rules` gated on `status='active'`).
3. **Tesseract emitted word boxes** that broke line-level field matching — added word→line grouping so all OCR engines honour one contract.
4. **“Best Before: …Packing” and “Packed: AUG 2026” misclassified as packer** (entity matcher); date statements excluded.
5. **“Manufactured & Packed by:” prefix not stripped** from manufacturer name (and a lost-`$` regex that stripped *all* spaces — caught by the diff table).
6. **UI review decisions hit a 404 route** (`/findings/{id}` → `/inspections/findings/{id}`).
7. **Report preview** rendered `NON_COMPLIANT`, hid final remarks + finding notes.
8. Matcher `SyntaxWarning` on an escape sequence (cleaned).

## Real vs simulated — the blunt summary

- **Real:** OpenCV quality checks (blur/lighting/glare%/framing/orientation), tesseract OCR,
  deterministic field matching + normalisation, DB persistence, rule engine (incl.
  date-aware versioning), PDF/DOCX generation, review/finalise persistence, RBAC scoping,
  duplicate detection (exact-hash), coverage tracking.
- **Simulated / not-yet:** PaddleOCR primary and the Ollama model are **not running** (both
  opt-in via env; wrappers + contract verified, live model consistency not measurable
  without a model server); demo mode uses rendered-label ground truth for the *seeded*
  demo inspections; **no distance estimation**, no **focus** metric separate from blur, no
  glare **mask geometry**; blur/glare thresholds need calibration against real photographs;
  evidence overlays draw real bbox geometry on the real served image (front-end verified).

One-line per the judge-demo risk question: the parts that *look* real (CV + rules + DB +
UI wiring) are real; the heavy AI (PaddleOCR, Qwen) is genuinely dormant behind the engine
abstraction — say so in the demo rather than implying the label was read by a vision LLM.
