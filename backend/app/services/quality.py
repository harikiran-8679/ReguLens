"""Image quality engine (OpenCV).

Evaluates a captured/uploaded package image and returns per-check verdicts with
specific, actionable guidance (never a bare "invalid image"). Checks mirror the
smart-camera spec: blur, lighting, glare/reflection, sharpness, framing/package
detection, orientation and a derived text-visibility estimate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Calibration constants — tuned 2026-09 against four real packaged-product
# photographs (cereal box, ration package, chips bag, glossy drink cartons;
# /tmp/lm_photos). Values are heuristics for typical phone-camera photos of
# packaging (glossy surfaces, small print); a larger labelled set of field
# photos is recommended before relying on them for enforcement.
# ---------------------------------------------------------------------------
# Blur: Laplacian variance of the full frame (blur_score = 1 - lap_var/700)
BLUR_FAIL_BLURNESS = 0.82      # lap_var < ~126  -> fail (too blurry)
BLUR_WARN_BLURNESS = 0.55      # lap_var < ~315  -> warn
# Focus: Laplacian variance of the central label ROI (score = lap_var/600)
FOCUS_FAIL_SCORE = 0.18        # lap_var < ~108  -> fail (out of focus)
FOCUS_WARN_SCORE = 0.40        # lap_var < ~240  -> warn
# Lighting: mean brightness + overbright ratio
LIGHTING_DARK_FAIL = 45.0      # mean below -> fail (underexposed)
LIGHTING_DARK_WARN = 75.0      # mean below -> warn
LIGHTING_OVERBRIGHT_FAIL = 0.55
LIGHTING_OVERBRIGHT_WARN = 0.30
# Glare: % of pixels above the specular threshold (245)
GLARE_FAIL_PCT = 0.12
GLARE_WARN_PCT = 0.04
# Framing / package detection
PACKAGE_DETECT_MIN_EDGE_DENSITY = 0.004
FRAMING_MIN_SCORE = 0.55
FRAMING_MIN_CENTER_DENSITY = 0.006
# Distance / cut-off (heuristics on the border-vs-center edge distribution;
# calibrated so photos with context around the product do NOT fire "too close")
CUTOFF_CENTER_DENSITY = 0.012   # product must have real edge content in the centre
CUTOFF_BORDER_RATIO = 1.4       # border band edge density relative to centre
DIST_CLOSE_CENTER_DENSITY = 0.0015
DIST_CLOSE_BORDER_RATIO = 0.5   # product reaching the frame borders
DIST_FAR_CENTER_DENSITY = 0.0010  # almost no edge content in the centre -> too far
# Derived text-visibility blend
TEXT_VIS_BLUR_WEIGHT = 0.55
TEXT_VIS_GLARE_WEIGHT = 0.9


@dataclass
class QualityCheck:
    metric: str
    status: str        # good | warn | fail
    score: float
    message: str


@dataclass
class QualityReport:
    overall: str                       # good | acceptable | poor
    ocr_suitability: str               # good | acceptable | poor | pending
    checks: list[QualityCheck] = field(default_factory=list)
    scores: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "overall": self.overall,
            "ocr_suitability": self.ocr_suitability,
            "scores": self.scores,
            "checks": [
                {"metric": c.metric, "status": c.status, "score": round(c.score, 4), "message": c.message}
                for c in self.checks
            ],
        }


def _to_gray(image: np.ndarray) -> np.ndarray:
    import cv2

    if image.ndim == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def analyse(image_path: Path | str, width: int | None = None, height: int | None = None) -> QualityReport:
    """Run the full quality battery against an image file."""
    import cv2

    image = cv2.imread(str(image_path))
    if image is None:
        report = QualityReport(overall="poor", ocr_suitability="poor")
        report.checks.append(QualityCheck("image_load", "fail", 0.0, "Image could not be read. Use a valid JPG/PNG file."))
        return report

    gray = _to_gray(image)
    h, w = gray.shape[:2]
    checks: list[QualityCheck] = []
    scores: dict = {}

    # ---- Blur / sharpness (variance of Laplacian) ---------------------------
    # blur_score is a *blurriness* 0..1 (1 = very blurred). Lower is sharper.
    # Thresholds are heuristic and calibrated for phone photos; real-photo
    # calibration is recommended before relying on them for enforcement.
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    lap_var = float(lap.var())
    sharpness = min(lap_var / 700.0, 1.0)
    blur_score = round(max(0.0, 1.0 - sharpness), 4)
    scores["blur_score"] = blur_score
    scores["sharpness_raw"] = round(lap_var, 2)
    if blur_score > BLUR_FAIL_BLURNESS:
        checks.append(QualityCheck("blur", "fail", blur_score,
                                   "Image is too blurry for reliable OCR. Hold the device steady and recapture."))
    elif blur_score > BLUR_WARN_BLURNESS:
        checks.append(QualityCheck("blur", "warn", blur_score,
                                   "Some softness detected. A sharper capture will improve text recognition."))
    else:
        checks.append(QualityCheck("blur", "good", blur_score, "Image appears sharp."))

    # ---- Focus (central-region Laplacian, reported as its own metric) ---------
    # Physically the same signal family as blur, but measured on the central
    # label area and surfaced as a distinct check so the capture UI can give
    # explicit "refocus" guidance instead of only a generic blur message.
    focus_roi = gray[int(h * 0.15):int(h * 0.85), int(w * 0.15):int(w * 0.85)]
    focus_lap = cv2.Laplacian(focus_roi, cv2.CV_64F)
    focus_var = float(focus_lap.var())
    focus_score = round(max(0.0, min(focus_var / 600.0, 1.0)), 4)
    scores["focus_score"] = focus_score
    if focus_score < FOCUS_FAIL_SCORE:
        checks.append(QualityCheck("focus", "fail", focus_score,
                                   "Label area is out of focus — tap to refocus on the declarations before capturing."))
    elif focus_score < FOCUS_WARN_SCORE:
        checks.append(QualityCheck("focus", "warn", focus_score,
                                   "Focus is soft on the central label area — refocus for a crisper capture."))
    else:
        checks.append(QualityCheck("focus", "good", focus_score, "Label area is in focus."))

    # ---- Lighting ------------------------------------------------------------
    mean_brightness = float(gray.mean())
    overbright = float((gray > 245).mean())
    dark = float((gray < 40).mean())
    scores["lighting_mean"] = round(mean_brightness, 1)
    if mean_brightness < LIGHTING_DARK_FAIL or overbright > LIGHTING_OVERBRIGHT_FAIL:
        checks.append(QualityCheck("lighting", "fail", min(mean_brightness / 255, 1.0),
                                   "Lighting is unsuitable for OCR. Move to a better-lit area and avoid direct flash."))
    elif mean_brightness < LIGHTING_DARK_WARN or overbright > LIGHTING_OVERBRIGHT_WARN:
        checks.append(QualityCheck("lighting", "warn", min(mean_brightness / 255, 1.0),
                                   "Lighting is uneven. Reposition the package for even illumination."))
    else:
        checks.append(QualityCheck("lighting", "good", min(mean_brightness / 255, 1.0),
                                   "Adequate lighting."))

    # ---- Glare / reflection ----------------------------------------------------
    glare_pct = float(overbright)
    # Glare *region* mask: connected components of the overbright pixels, each
    # returned as a normalized bounding box — not just a boolean / percentage.
    glare_regions: list[dict] = []
    if glare_pct > 0.0:
        _, glare_mask = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY)
        num, labels, stats, _ = cv2.connectedComponentsWithStats(glare_mask, connectivity=8)
        min_area = max(int(w * h * 0.002), 16)  # ignore single-pixel specks
        comps = []
        for i in range(1, num):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area >= min_area:
                x, y, cw, ch = (int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP]),
                                int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT]))
                comps.append({
                    "x": round(x / w, 4), "y": round(y / h, 4),
                    "width": round(cw / w, 4), "height": round(ch / h, 4),
                    "area_pct": round(area / (w * h), 4),
                })
        comps.sort(key=lambda c: c["area_pct"], reverse=True)
        glare_regions = comps[:6]
    scores["glare_pct"] = round(glare_pct, 4)
    scores["glare_regions"] = glare_regions
    if dark < 0.02 and glare_pct > GLARE_FAIL_PCT:
        checks.append(QualityCheck("glare", "fail", min(glare_pct, 1.0),
                                   f"Strong reflection is covering part of the text ({len(glare_regions)} glare region(s) detected). Tilt the package slightly or change the light source."))
    elif glare_pct > GLARE_WARN_PCT:
        checks.append(QualityCheck("glare", "warn", min(glare_pct, 1.0),
                                   "Glare/reflection detected — it may affect text recognition near the bright area."))
    else:
        checks.append(QualityCheck("glare", "good", min(glare_pct, 1.0), "No significant glare."))

    # ---- Framing / package detection + distance / cut-off heuristics -----------
    # Edge density concentrated in the central frame => product is framed.
    edges = cv2.Canny(gray, 60, 160)
    cy0, cy1 = int(h * 0.12), int(h * 0.88)
    cx0, cx1 = int(w * 0.08), int(w * 0.92)
    center = edges[cy0:cy1, cx0:cx1]
    center_density = float((center > 0).mean())
    total_density = float((edges > 0).mean())
    scores["edge_density"] = round(total_density, 4)
    framing = min(center_density / max(total_density, 1e-6) if total_density > 0 else 0.0, 1.0)
    scores["framing_score"] = round(framing, 4)
    coverage_pct = round(min(center_density * 260.0, 1.0), 4)  # heuristic fullness of the frame
    scores["coverage_pct"] = coverage_pct
    if total_density < PACKAGE_DETECT_MIN_EDGE_DENSITY:
        checks.append(QualityCheck("package_detection", "fail", total_density,
                                   "Package not detected. Place the packaged commodity inside the highlighted frame."))
    else:
        # Edge density along the frame borders vs the inner area -> "cut off" hint.
        # Calibrated on real package photos: photos with context around the
        # product (shelf, background) have a LOW border_ratio and must NOT fire
        # "too close"; only a product actually reaching the frame borders does.
        b = int(min(w, h) * 0.06)
        border_mask = np.zeros_like(edges, dtype=bool)
        border_mask[:b, :] = True
        border_mask[h - b:, :] = True
        border_mask[:, :b] = True
        border_mask[:, w - b:] = True
        border_density = float((edges[border_mask] > 0).mean())
        border_ratio = border_density / max(center_density, 1e-6)
        scores["border_density"] = round(border_density, 4)
        scores["border_ratio"] = round(border_ratio, 4)
        cut_off = center_density > CUTOFF_CENTER_DENSITY and border_ratio > CUTOFF_BORDER_RATIO
        too_close = center_density > DIST_CLOSE_CENTER_DENSITY and border_ratio > DIST_CLOSE_BORDER_RATIO
        too_far = center_density < DIST_FAR_CENTER_DENSITY
        if cut_off:
            checks.append(QualityCheck("product_cut_off", "fail", min(border_ratio / 3.0, 1.0),
                                       "Product appears cut off at the frame edge. Move back slightly so the whole label is inside the frame."))
        elif too_close:
            checks.append(QualityCheck("distance", "warn", min(border_ratio, 1.0),
                                       "Package too close — part of the label may be out of frame. Move back slightly."))
        elif too_far:
            checks.append(QualityCheck("distance", "warn", max(0.0, 1.0 - center_density * 400),
                                       "Package appears too far — move closer so the label text is readable."))
        else:
            checks.append(QualityCheck("distance", "good", coverage_pct, "Capture distance looks appropriate."))
        if framing < FRAMING_MIN_SCORE or center_density < FRAMING_MIN_CENTER_DENSITY:
            checks.append(QualityCheck("framing", "warn", framing,
                                       "Package is not well centred. Move closer or reposition the package inside the frame."))
        else:
            checks.append(QualityCheck("framing", "good", framing, "Package detected and well framed."))

    # ---- Orientation (text skew) -------------------------------------------------
    # Cheap heuristic: standard deviation of the strongest edge angle bins.
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)
    angles = np.arctan2(gy, gx + 1e-9)
    strong = mag > (mag.mean() + mag.std())
    if strong.sum() > 100:
        dominant = float(np.median(angles[strong]))
        tilt = abs(dominant) if abs(dominant) < np.pi / 2 else abs(dominant) - np.pi
        tilt_deg = abs(np.degrees(tilt))
        scores["orientation_tilt_deg"] = round(tilt_deg, 2)
        if tilt_deg > 12:
            checks.append(QualityCheck("orientation", "warn", min(tilt_deg / 30.0, 1.0),
                                       "Package appears tilted. Align it squarely before capture."))
        else:
            checks.append(QualityCheck("orientation", "good", 1 - min(tilt_deg / 30.0, 1.0), "Orientation acceptable."))
    else:
        checks.append(QualityCheck("orientation", "good", 1.0, "Orientation acceptable."))

    # ---- Text visibility (derived) ------------------------------------------------
    tv = 1.0 - max(blur_score * 0.55, glare_pct * 0.9, 0.0)
    tv = max(0.0, min(tv, 1.0))
    scores["text_visibility"] = round(tv, 4)
    if tv < 0.45:
        checks.append(QualityCheck("text_visibility", "fail", tv,
                                   "Text may not be recognisable in this capture. Move closer for a higher-resolution shot of the declarations."))
    elif tv < 0.75:
        checks.append(QualityCheck("text_visibility", "warn", tv,
                                   "Some text may be hard to read — consider capturing the declaration area separately."))
    else:
        checks.append(QualityCheck("text_visibility", "good", tv, "Text appears visible."))

    # ---- Aggregate --------------------------------------------------------------
    statuses = {c.status for c in checks}
    if "fail" in statuses:
        overall = "poor"
        ocr_suitability = "poor"
    elif len([c for c in checks if c.status == "warn"]) > 2:
        overall = "acceptable"
        ocr_suitability = "acceptable"
    elif "warn" in statuses:
        overall = "acceptable"
        ocr_suitability = "acceptable"
    else:
        overall = "good"
        ocr_suitability = "good"
    return QualityReport(overall=overall, ocr_suitability=ocr_suitability, checks=checks, scores=scores)


def quick_assess_bytes(image_bytes: bytes) -> dict:
    """Assess from raw bytes without touching disk (used at upload time)."""
    import cv2
    import numpy as np

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        return QualityReport(overall="poor", ocr_suitability="poor",
                             checks=[QualityCheck("image_load", "fail", 0.0,
                                                  "Uploaded file is not a readable image.")]).as_dict()
    tmp = Path("/tmp") / "lm_upload_assess.png"
    cv2.imwrite(str(tmp), image)
    return analyse(tmp).as_dict()
