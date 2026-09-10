# Legal Metrology Inspection Platform (SIH26034)

A full-stack **Legal Metrology Inspection Platform** for enforcement inspectors: photograph or
upload images of a packaged commodity, extract mandatory declarations via an image-quality →
OCR → field-matching pipeline, validate them against a **versioned, date-aware rule engine**
modelled on the Legal Metrology (Packaged Commodities) Rules, 2011, and produce an
evidence-backed compliance report (PDF + editable DOCX).

> **Design principle that must stay visible in the code:** the LLM / matcher is **never** asked
> "is this compliant?" — it only maps OCR text to structured field names. Every pass/fail/
> review decision comes from the deterministic rule engine (`backend/app/services/rule_engine.py`).

---

## Stack

| Layer     | Technology |
|-----------|------------|
| Frontend  | React 18 (Vite) + TypeScript + TailwindCSS, mobile-responsive |
| Backend   | Python 3.12 · FastAPI |
| Database  | PostgreSQL 16 (Docker Compose) |
| Storage   | Local volume (path referenced from Postgres) |
| OCR       | **PaddleOCR (primary)** with automatic **Tesseract fallback**; `demo` mode replays ground truth labelled “PaddleOCR (simulated)” |
| Field matcher | Pluggable — `demo` (deterministic default), `ollama` (`qwen2.5`) |
| CV        | OpenCV (blur / glare / lighting / framing checks) |
| Reports   | ReportLab (PDF) + python-docx (editable) |
| Auth      | JWT, role-based (Inspector / Admin) |

## Quick start

```bash
# 1. Start the full stack (Postgres + API). First boot seeds users, rules and demo data.
docker compose up -d --build

# 2. Start the frontend dev server (proxies /api to the API container on :8000)
cd frontend
npm install
npm run dev          # → http://localhost:5174
```

Open **http://localhost:5174**.

### Demo accounts

The two **primary demo accounts** are seeded at database setup (fixed values, persisted across
restarts) and shown directly on the login pages — plus shown pre-filled in the login forms:

| Role | Username | Password |
|------|----------|----------|
| **Admin** | `admin@demo.com` | `Admin@123` |
| **Inspector** | `inspector@demo.com` | `Inspector@123` |

| Role | Username | Password |
|------|----------|----------|
| Inspector | `LM-INS-00125` | `inspector123` |
| Inspector | `LM-INS-00131` | `inspector123` |
| Admin | `ADM-001` | `admin123` |

The login forms are pre-filled with the demo inspector/admin credentials — just press **🔐 LOGIN**.
Admins can create additional inspector accounts from **Admin Dashboard → Inspectors → + Add
Inspector**; the new inspector can log in immediately with the credentials entered there.

### Seeded demo inspections

Six inspections are pushed through the real pipeline on first boot (images are *generated*
label renders, then processed end-to-end):

- `LM-2026-00125` — draft (empty session, start point for the guided flow)
- `LM-2026-00126` — **finalised · non-compliant** (owner: `LM-INS-00131`)
- `LM-2026-00127` — pending review · non-compliant
- `LM-2026-00128` — **finalised · compliant** (PDF + DOCX reports pre-generated)
- `LM-2026-00129` — pending review · **guided walkthrough demo** (missing tax-inclusive MRP
  wording, small MRP font, missing consumer care → 2 non-compliant / 3 manual-review items,
  plus a **cross-source mismatch**: the online listing says 4 kg while the package says 5 kg →
  `POTENTIAL_NON_COMPLIANCE` with both values shown side by side on the Compliance Result page)
- `LM-2026-00130` — pending review · **cross-field conflict demo**: front panel declares
  `NET QTY: 500 g`, back panel declares `NET QTY: 250 g` → the cross-field consistency check
  produces `POTENTIAL_NON_COMPLIANCE` with both values and both evidence images

Open the **Inspector Dashboard → LM-2026-00129** to walk steps 2→7 (Capture → OCR → Rule Engine
→ Compliance Result → Violations → Font → Placement → Evidence → Review → Report Preview → Export).
Try the **“Compare against package”** box on the Compliance Result page to enter any online
listing value and re-run the cross-source check.

### The four compliance states (Section 0 of the build spec)

Exactly four states are used for every compliance verdict — database column
(`rule_results.result`, enforced by a CHECK constraint), backend logic, every frontend page
and the PDF report. Nothing else is stored or rendered:

| State | Meaning |
|---|---|
| `COMPLIANT` | rule requirement satisfied |
| `NON_COMPLIANT` | a single rule failed with sufficient confidence and image coverage |
| `MANUAL_REVIEW` | low confidence, poor image quality or borderline measurement — never silently treated as either compliant or a violation |
| `POTENTIAL_NON_COMPLIANCE` | **reserved for cross-field / cross-source mismatches** (two different net-quantity values on the same package, or a package value that differs from a manually entered online-listing value) |

Each rule result carries the structured `observed` / `expected` / `evidence` / `reason` shape
consumed by the Compliance Result page and the PDF report (Section 5 of the build spec).

## Page map (UI contract from `Pages.zip`)

Landing · Inspector/Admin Login · Inspector Dashboard · New Inspection · Image Capture/Upload
(smart-scan with live quality indicators + coverage tracking) · OCR & Data Extraction ·
Rule Engine Analysis · Compliance Result · Violation Details · Font & Readability Analysis ·
Placement/Format Analysis · Evidence Management (bounding-box overlays) · Inspector Review ·
Final Report Preview · PDF/Editable Export · Admin Dashboard · Admin Inspectors · Admin Rules
(CRUD w/ versioned rows) · Admin Audit.

## The AI pipeline (engine abstraction + demo mode)

The heavy CV/OCR/LLM pieces are behind interfaces so the whole app runs fully offline:

1. **Image quality** — `backend/app/services/quality.py` (OpenCV): blur score, glare %, lighting,
   framing, OCR-suitability verdict.
2. **OCR** — `backend/app/services/ocr.py`: `run_ocr_with_fallback()` implements the
   **PaddleOCR-first → Tesseract-fallback** chain (Paddle is the primary; Tesseract is used only
   when Paddle is unavailable, crashes, or returns fewer than `MIN_TEXT_REGIONS` regions). The
   chain, per-engine reason, and a `fallback_used` flag are returned and **persisted per image**
   (`images.ocr_engine`, `images.ocr_fallback_used`) so the OCR & Data Extraction page shows which
   engine actually read each image (e.g. amber “⚠ Tesseract (fallback)”). Tesseract confidences
   are normalised onto Paddle's scale (`normalize_confidence`: factor 0.95 + floor, capped) —
   engine scores are never passed through raw. `DemoOcrEngine` replays ground-truth text regions
   and is labelled **“PaddleOCR (simulated)”** so the demo UI matches the real primary/fallback
   design. Engines are swapped via `OCR_ENGINE`.
3. **Field matching** — `backend/app/services/matcher.py`: deterministic classifier by default;
   `OllamaFieldMatcher` (`FIELD_MATCHER=ollama`) is invoked **only** for lines the deterministic
   matcher could not label, and only to name a field — never to judge compliance.
4. **Normalization** — `backend/app/services/normalizer.py`: a standalone, testable unit that
   converts raw OCR variants (quantities, prices, month/year dates) into normalized values while
   preserving the original raw text. The matcher consumes it; the rule engine only ever receives
   already-normalized `product_facts` (ExtractedField rows) — raw OCR text never reaches it.
5. **Rule engine** — `backend/app/services/rule_engine.py`: date-aware selection
   (`effective_from <= inspection_date AND (effective_to IS NULL OR effective_to > date)`),
   applicability/conditions filtering, per-declaration font/placement/spacing expansion,
   cross-field / cross-source consistency checks, and the **only** place the four compliance
   states (`COMPLIANT` / `NON_COMPLIANT` / `MANUAL_REVIEW` / `POTENTIAL_NON_COMPLIANCE`) are
   produced.
6. **Four states, never collapsed**: 🟢 detected/verified → `COMPLIANT` · 🟡 uncertain/
   low-confidence → `MANUAL_REVIEW` (never a silent verdict) · 🔴 not found after adequate
   coverage → `NON_COMPLIANT` · 🟣 cross-field / cross-source mismatch →
   `POTENTIAL_NON_COMPLIANCE` (reserved for that purpose only).
7. **Font measurement is honestly relative**: estimated text-height ÷ panel-height ratio,
   explicitly labelled as *not* a calibrated millimetre measurement in the UI and reports.

## Project layout

```
docker-compose.yml        # postgres:16 + api (self-contained stack)
backend/
  app/
    main.py               # FastAPI app, CORS, lifespan (init + seed)
    models.py             # SQLAlchemy models (users … reports)
    seed.py               # users, categories, 21 versioned rules, demo inspections
    routers/              # auth, inspections, images, pipeline, analysis,
                          # review, evidence, reports, dashboard, meta, admin
    services/
      labelgen.py         # demo package-label renderer w/ ground truth
      quality.py          # OpenCV image-quality engine (blur/focus/lighting/glare mask/framing/distance)
      ocr.py              # OCR engine abstraction (demo/tesseract/paddle) w/ Paddle-first fallback
      normalizer.py       # standalone normalization unit (quantity/price/date, raw text preserved)
      matcher.py          # deterministic + Ollama field mapping (mapping only)
      pipeline.py         # quality→OCR→field-matching orchestration
      rule_engine.py      # deterministic versioned rule engine + cross checks + findings/evidence
      report_builder.py   # report_payload + PDF (ReportLab) + DOCX
      audit.py
  Dockerfile
frontend/
  src/
    App.tsx               # routes + role guards
    client.ts             # API client (Bearer JWT, error handling)
    auth.tsx              # auth context
    components/           # ui, layout (sidebar), flow stepper, media (overlay)
    pages/                # one file per spec page
```

## API surface (Swagger at http://localhost:8000/docs)

`/api/auth/login` `/api/auth/me` · `/api/dashboard/{inspector,admin}` · `/api/inspections`
CRUD + `/navigate` steps · `/api/inspections/{id}/images` (+ upload, `/api/images/{id}/file`) ·
`/api/inspections/{id}/ocr` (+ run) · `/fields` (+ verify, patch extracted fields) ·
`/analysis/run` · `/rule-results` · `/rule-set` · `/compliance` · `/findings` ·
`/font-analysis` (+ patch) · `/placement-analysis` (+ patch) · `/evidence` (+ upload) ·
`/review` `/finalize` `/observation` · `/report/preview` `/report/generate` `/reports`
`/reports/{id}/download` · `/admin/inspectors` `/admin/rules` `/admin/audit` · `/rules` (read) ·
`/meta/catalog`.

## Switching OCR / matcher engines

`OCR_ENGINE` selects the **primary** engine; the fallback chain always applies afterwards:

| `OCR_ENGINE` | Behaviour |
|--------------|-----------|
| `paddle` (code default; also the running compose stack) | PaddleOCR first → Tesseract fallback if Paddle is unavailable / fails / finds <1 region → demo as last resort. Every fallback is logged and flagged per image in the UI. |
| `demo` | Offline simulated mode — replays ground truth, labelled **“PaddleOCR (simulated)”**, never silently swapped. |
| `tesseract` | Tesseract first (then demo). Useful when Paddle isn't installed. |

`FIELD_MATCHER=ollama` enables the Qwen field-matching hook (requires `ollama serve` with
`qwen2.5` pulled); it is invoked only to name unclassified OCR lines, never to judge compliance.

PaddleOCR (`paddleocr==3.7.x` + `paddlepaddle>=3.0`) **is** in `requirements.txt` and is the
actually-running primary engine in both the API image and the local venv (first run downloads
the PP-OCRv6 models into `~/.paddlex/official_models/`). Tesseract (`pytesseract` + system
binary) is installed as the fallback and is exercised when Paddle is unavailable, fails, or
returns zero regions. The UI discloses the real matcher state too: the OCR page shows
**“Simulated field-matcher (deterministic)”** by default, or **“LLM field-matcher
(Ollama/Qwen)”** when `FIELD_MATCHER=ollama` and Ollama is reachable.

## Local (no-Docker) backend run

```bash
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
# start Postgres however you like on :5433 (see docker-compose.yml), or set DATABASE_URL
#   to a SQLite file for a zero-setup demo: DATABASE_URL=sqlite:///./lm_inspection.db
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Then point Vite at it — the dev proxy already targets `http://localhost:8000`.
