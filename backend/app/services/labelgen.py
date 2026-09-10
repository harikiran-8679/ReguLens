"""Generate realistic packaged-commodity label images for the seeded demo data.

Each generated image returns a ground-truth region list [{text, x, y, w, h,
conf}] in *normalised* coordinates. The demo OCR engine replays these regions,
so bounding boxes, confidence and downstream geometry analysis are all real
pipeline inputs even though the text is never "read" from pixels.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from typing import Any, cast

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------------------
# Font loading (best-effort: real TTFs when present, PIL default otherwise)
# ---------------------------------------------------------------------------
_FONT_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
_BOLD_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
_cached: dict[tuple[bool, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = (bold, size)
    if key in _cached:
        return _cached[key]
    for path in (_BOLD_CANDIDATES if bold else _FONT_CANDIDATES):
        try:
            f = ImageFont.truetype(path, size)
            _cached[key] = f
            return f
        except Exception:
            continue
    try:
        f = ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        f = ImageFont.load_default()
    _cached[key] = f
    return f


@dataclass
class LabelItem:
    """A piece of text laid out on the label. box is normalised (0..1)."""
    text: str
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 (fractions of canvas)
    conf: float = 0.97
    size_pt: int | None = None       # preferred font px (auto-fit when None)
    bold: bool = False
    color: str = "#111111"
    align: str = "center"            # center | left | right


@dataclass
class LabelSpec:
    canvas: tuple[int, int] = (1000, 1300)
    background: str = "#fbfbf7"
    accent: str = "#1a3a5c"
    items: list[LabelItem] = field(default_factory=list)
    divider_lines: list[tuple[float, float, float, float, str]] = field(default_factory=list)
    glare_band: bool = False
    blur: float = 0.0
    brightness_boost: float = 0.0


def _fit_font(draw: ImageDraw.ImageDraw, text: str, box_w: int, box_h: int, bold: bool, size: int) -> Any:
    size = size or max(10, int(box_h * 0.72))
    while size > 6:
        f = _font(bold, size)
        w = draw.textlength(text, font=f)
        if w <= box_w * 0.96:
            return f
        size = int(size * 0.92)
    return _font(bold, size)


def build_label(spec: LabelSpec) -> tuple[Image.Image, list[dict]]:
    """Render a label from a spec and return (image, ground-truth regions)."""
    W, H = spec.canvas
    img = Image.new("RGB", (W, H), spec.background)
    draw = ImageDraw.Draw(img)

    # Top accent band
    draw.rectangle([0, 0, W, int(H * 0.045)], fill=spec.accent)

    regions: list[dict] = []
    for item in spec.items:
        x0, y0, x1, y1 = item.box
        bx0, by0, bx1, by1 = int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)
        bw, bh = bx1 - bx0, by1 - by0
        font = _fit_font(draw, item.text, bw, bh, item.bold, item.size_pt or int(bh * 0.72))
        tw = draw.textlength(item.text, font=font)
        asc, desc = font.getmetrics()
        th = asc + desc
        if item.align == "center":
            tx = bx0 + (bw - tw) / 2
        elif item.align == "right":
            tx = bx1 - tw
        else:
            tx = bx0
        ty = by0 + (bh - th) / 2
        draw.text((tx, ty), item.text, font=font, fill=item.color)

        # Use the measured text extents for the ground-truth box (keeps overlays tight)
        pad = 0
        gt = {
            "text": item.text,
            "x": round((tx - pad) / W, 4),
            "y": round((ty - pad) / H, 4),
            "w": round(min((tw + pad * 2) / W, 1.0), 4),
            "h": round(min((th + pad * 2) / H, 1.0), 4),
            "conf": item.conf,
        }
        regions.append(gt)

    for x0, y0, x1, y1, color in spec.divider_lines:
        draw.line([int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)], fill=color, width=3)

    if spec.glare_band:
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        # Diagonal white glare band crossing the label
        pts = [(int(W * 0.05), H), (int(W * 0.42), 0), (int(W * 0.62), 0), (int(W * 0.25), H)]
        od.polygon(pts, fill=(255, 255, 255, 205))
        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=24))
        img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"), (0, 0))

    if spec.blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=spec.blur))

    if spec.brightness_boost:
        img = cast(Any, img).point(lambda p: min(255, int(p * (1 + spec.brightness_boost))))

    return img, regions
