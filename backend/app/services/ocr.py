"""OCR engine abstraction.

The pipeline consumes an OcrRegion list regardless of the engine:

    OcrRegion = {text, confidence, bounding_box: {x, y, width, height}}  (0..1)

Engines:
  * DemoOcrEngine   — replays the ground-truth regions recorded when the demo
                      sample labels were generated, so the whole app runs
                      offline and deterministically.
  * TesseractEngine — real OCR via pytesseract (optional; needs the binary).
  * PaddleEngine    — real OCR via PaddleOCR (optional; heavy, best run in a
                      dedicated environment rather than the dev venv).

Selection happens through the OCR_ENGINE setting so the heavy engines can be
swapped in without touching the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import settings


@dataclass
class OcrRegion:
    text: str
    confidence: float
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": round(float(self.confidence), 4),
            "bounding_box": {
                "x": round(float(self.x), 4),
                "y": round(float(self.y), 4),
                "width": round(float(self.w), 4),
                "height": round(float(self.h), 4),
            },
        }


class BaseOcrEngine:
    name = "base"

    def available(self) -> bool:  # pragma: no cover - interface
        return True

    def run(self, image_path: Path, ground_truth: list[dict] | None = None) -> list[OcrRegion]:
        raise NotImplementedError


class DemoOcrEngine(BaseOcrEngine):
    """Replays label ground truth (text + boxes + confidences) for demo images."""
    name = "demo"

    def available(self) -> bool:
        return True

    def run(self, image_path: Path, ground_truth: list[dict] | None = None) -> list[OcrRegion]:
        regions: list[OcrRegion] = []
        for gt in ground_truth or []:
            conf = float(gt.get("conf", 0.97))
            if conf <= 0.30:
                continue  # simulate a line the engine could not resolve
            regions.append(
                OcrRegion(
                    text=str(gt.get("text", "")),
                    confidence=conf,
                    x=float(gt.get("x", 0)),
                    y=float(gt.get("y", 0)),
                    w=float(gt.get("w", 0)),
                    h=float(gt.get("h", 0)),
                )
            )
        return regions


class TesseractEngine(BaseOcrEngine):
    """Real OCR through pytesseract (needs system tesseract + pip pytesseract)."""
    name = "tesseract"

    def available(self) -> bool:
        try:
            import pytesseract  # type: ignore # noqa: F401

            return True
        except Exception:
            return False

    def run(self, image_path: Path, ground_truth: list[dict] | None = None) -> list[OcrRegion]:
        import pytesseract  # type: ignore
        from PIL import Image

        data = pytesseract.image_to_data(Image.open(image_path), output_type=pytesseract.Output.DICT)
        img = Image.open(image_path)
        w, h = img.size
        words: list[OcrRegion] = []
        n = len(data["text"])
        for i in range(n):
            text = (data["text"][i] or "").strip()
            conf = float(data["conf"][i]) / 100.0
            if not text or conf <= 0.25:
                continue
            words.append(
                OcrRegion(text=text, confidence=conf,
                          x=data["left"][i] / w, y=data["top"][i] / h,
                          w=data["width"][i] / w, h=data["height"][i] / h)
            )
        # tesseract returns *word* boxes; the engine contract (and Paddle's
        # native output) is *line* regions — group words sharing a text row
        # so downstream field matching sees whole lines.
        words.sort(key=lambda r: (r.y, r.x))
        lines: list[list[OcrRegion]] = []
        for word in words:
            row_y0, row_y1 = word.y, word.y + word.h
            if lines:
                prev = lines[-1]
                band_y0 = min(p.y for p in prev)
                band_y1 = max(p.y + p.h for p in prev)
                overlap = min(row_y1, band_y1) - max(row_y0, band_y0)
                avg_h = sum(p.h for p in prev) / len(prev)
                if overlap > 0.35 * min(word.h, avg_h):
                    prev.append(word)
                    continue
            lines.append([word])
        regions: list[OcrRegion] = []
        for group in lines:
            group.sort(key=lambda r: r.x)
            x0 = min(r.x for r in group)
            y0 = min(r.y for r in group)
            x1 = max(r.x + r.w for r in group)
            y1 = max(r.y + r.h for r in group)
            text = " ".join(r.text for r in group)
            conf = sum(r.confidence * (r.w * r.h) for r in group) / max(
                sum(r.w * r.h for r in group), 1e-9)
            regions.append(OcrRegion(text=text, confidence=round(conf, 4),
                                     x=x0, y=y0, w=x1 - x0, h=y1 - y0))
        return regions


class PaddleEngine(BaseOcrEngine):
    """Real OCR through PaddleOCR (heavy; requires paddlepaddle + paddlex install).

    Uses the 3.x API (PaddleOCR.predict -> OCRResult with rec_texts/rec_scores/
    rec_boxes). The engine is instantiated lazily once per process because model
    download + warm-up is expensive; a failed init makes available() False so the
    fallback chain kicks in (Tesseract first, demo last).
    """
    name = "paddle"

    _instance: Any = None
    _init_error: str = ""

    def available(self) -> bool:
        try:
            from paddleocr import PaddleOCR  # noqa: F401

            return True
        except Exception:
            return False

    @classmethod
    def _get_ocr(cls) -> Any:
        """Lazily build the shared PaddleOCR pipeline (3.x API)."""
        if cls._instance is None:
            from paddleocr import PaddleOCR

            cls._instance = PaddleOCR(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                lang="en",
                # Explicit detection sizing: the paddleocr 3.x default
                # (limit_side_len=64, limit_type='min') silently yields zero
                # detections on real photos; 960/max keeps full-res detail.
                text_det_limit_side_len=960,
                text_det_limit_type="max",
                text_rec_score_thresh=0.3,
            )
        return cls._instance

    def run(self, image_path: Path, ground_truth: list[dict] | None = None) -> list[OcrRegion]:
        from PIL import Image

        ocr = self._get_ocr()
        img = Image.open(image_path)
        iw, ih = img.size
        results = ocr.predict(str(image_path))
        regions: list[OcrRegion] = []
        for page in results or []:
            data = getattr(page, "json", None)
            data = data() if callable(data) else data
            if not data:
                data = dict(page)
            # paddleocr 3.7+ nests the payload under a 'res' key
            if isinstance(data, dict):
                if "res" in data and isinstance(data["res"], dict):
                    data = data["res"]
                texts = data.get("rec_texts") or []
                scores = data.get("rec_scores") or []
                boxes = data.get("rec_boxes") or data.get("rec_polys") or []
            else:
                texts, scores, boxes = [], [], []
            for text, conf, box in zip(texts, scores, boxes):
                if not str(text).strip():
                    continue
                if isinstance(box, list) and len(box) == 4 and isinstance(box[0], (int, float)):
                    # rec_boxes: [x0, y0, x1, y1] in pixels
                    x0, y0, x1, y1 = (float(v) for v in box)
                else:
                    # rec_polys: list of [x, y] corner points
                    xs = [float(p[0]) for p in box]
                    ys = [float(p[1]) for p in box]
                    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
                regions.append(
                    OcrRegion(
                        text=str(text),
                        confidence=float(conf),
                        x=round(x0 / iw, 4),
                        y=round(y0 / ih, 4),
                        w=round((x1 - x0) / iw, 4),
                        h=round((y1 - y0) / ih, 4),
                    )
                )
        return regions


_ENGINES: dict[str, BaseOcrEngine] = {
    "demo": DemoOcrEngine(),
    "tesseract": TesseractEngine(),
    "paddle": PaddleEngine(),
}

# Engine priority when none is explicitly requested / when one must be replaced.
# PaddleOCR is the PRIMARY engine; Tesseract is the fallback; the demo engine is the
# last-resort so the app keeps running offline (and, in demo mode, is the "simulated"
# primary with a PaddleOCR label so the UI stays consistent with the real design).
_PRIORITY: list[str] = ["paddle", "tesseract", "demo"]

# Display labels — demo mode is labelled as simulated PaddleOCR, never as Tesseract.
_ENGINE_LABELS: dict[str, str] = {
    "paddle": "PaddleOCR",
    "tesseract": "Tesseract",
    "demo": "PaddleOCR (simulated)",
}

# Minimum text regions an engine must return to be considered successful. If an engine
# returns fewer (e.g. Paddle silently produced nothing on a label with visible text),
# we treat it as a failure and move to the next engine in priority.
MIN_TEXT_REGIONS: int = 1

# Tesseract confidence adjustment (see normalize_confidence).
TESS_CONF_FACTOR: float = 0.95
TESS_CONF_FLOOR: float = 0.02
TESS_CONF_CAP: float = 0.99


@dataclass
class OcrEngineResult:
    """Outcome of a run with primary/fallback resolution, plus audit trail."""
    regions: list[OcrRegion]
    engine_code: str            # paddle | tesseract | demo
    engine_label: str           # human label incl. "(simulated)" in demo mode
    fallback_used: bool
    chain: list[str]            # engine codes tried, in order
    note: str = ""             # reasons for each skipped engine

    def to_dict(self) -> dict:
        return {
            "engine": self.engine_code,
            "engine_label": self.engine_label,
            "fallback_used": self.fallback_used,
            "chain": self.chain,
            "note": self.note,
        }


def normalize_confidence(conf: float, engine_code: str) -> float:
    """Map engine-specific confidence onto the common 0..1 scale the pipeline uses.

    * paddle / demo: identity — Paddle emits probability-style confidences and the
      demo engine replays ground truth.
    * tesseract: tesseract's per-word confidence is optimistic relative to Paddle's;
      we apply a documented adjustment (TESS_CONF_FACTOR + floor, capped at
      TESS_CONF_CAP) so a tesseract read can still reach the HIGH_CONF band but
      never reports as exact (1.0). Tune the constants above per corpus.
    """
    conf = float(conf)
    if engine_code == "tesseract":
        return round(min(TESS_CONF_CAP, max(0.0, conf * TESS_CONF_FACTOR + TESS_CONF_FLOOR)), 4)
    return round(max(0.0, min(1.0, conf)), 4)


def _ordered_candidates(requested: str | None) -> list[str]:
    """Build the try-order: requested (or configured, or 'paddle') first, then the
    remaining engines in priority order, demo last as the offline last resort."""
    start = (requested or settings.OCR_ENGINE or "paddle").strip().lower()
    if start not in _ENGINES:
        start = "paddle"
    order = [start]
    for code in _PRIORITY:
        if code not in order:
            order.append(code)
    return order


def run_ocr_with_fallback(image_path: Path, ground_truth: list[dict] | None = None,
                          requested: str | None = None,
                          min_regions: int = MIN_TEXT_REGIONS) -> OcrEngineResult:
    """Run OCR with Paddle-first, Tesseract-fallback semantics.

    An engine is skipped (and the next one tried) when it:
      * is not installed / not reachable (available() == False), or
      * raises while running, or
      * returns fewer than `min_regions` text regions.
    The chain, per-engine reasons and the fallback flag are all returned so they can
    be logged and surfaced in the UI — engines are never swapped silently.
    """
    order = _ordered_candidates(requested)
    chain: list[str] = []
    failures: list[str] = []
    for code in order:
        engine = _ENGINES[code]
        chain.append(code)
        if not engine.available():
            failures.append(f"{code}: unavailable (not installed / not reachable)")
            continue
        try:
            regions = engine.run(image_path, ground_truth=ground_truth) or []
        except Exception as exc:  # noqa: BLE001 - any engine crash triggers fallback
            failures.append(f"{code}: error {exc.__class__.__name__}: {str(exc)[:80]}")
            continue
        if len(regions) >= min_regions:
            return OcrEngineResult(
                regions=regions,
                engine_code=code,
                engine_label=_ENGINE_LABELS.get(code, code),
                fallback_used=len(chain) > 1,
                chain=list(chain),
                note="; ".join(failures),
            )
        failures.append(f"{code}: only {len(regions)} region(s) detected (< {min_regions})")
    # unreachable in practice (demo always available), but keep a safe final state
    last = order[-1]
    return OcrEngineResult(regions=[], engine_code=last, engine_label=_ENGINE_LABELS.get(last, last),
                           fallback_used=len(order) > 1, chain=list(order), note="; ".join(failures))


def get_ocr_engine(name: str | None = None) -> tuple[BaseOcrEngine, str]:
    """Legacy single-engine lookup (kept for compatibility). New code should use
    run_ocr_with_fallback which implements the Paddle-first/Tesseract-fallback chain."""
    requested = (name or settings.OCR_ENGINE or "demo").lower()
    if requested in _ENGINES:
        engine = _ENGINES[requested]
        if engine.available():
            return engine, requested
        return _ENGINES["demo"], f"demo (requested '{requested}' not available)"
    return _ENGINES["demo"], "demo (unknown engine name)"
