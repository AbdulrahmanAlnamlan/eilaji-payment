"""Qatar licence-plate support: format rules, rendering, and a demo OCR.

Qatar plates are digit-only (no letters): 1–6 digits, shown large in Western
numerals with the Eastern-Arabic form (٠١٢٣٤٥٦٧٨٩) written smaller above, plus
the "QATAR / قطر" legend. Private plates are black-on-white; other categories
(transport, taxi, limousine, ...) differ mainly by colour. That makes the
recognition problem *easier* than alphanumeric plates: normalise digits,
validate 1–6 of them, done.

Three pieces live here:

* format helpers   — ``normalize_digits`` / ``validate_qatar_plate``. Use these
                     on the output of ANY OCR backend (fast-alpr, PaddleOCR, a
                     fine-tuned model) to reject misreads cheaply.
* plate renderer   — draws a synthetic Qatar-style plate, used by the demo
                     footage generator and to build OCR digit templates.
* QatarPlateReader — a dependency-free OCR (contour digit segmentation +
                     template correlation) good enough to read the rendered
                     plates off demo footage through the real pipeline. It
                     proves the ALPR plumbing end-to-end; for real footage swap
                     in ``alpr.FastAlprReader`` (same callable interface) —
                     ideally fine-tuned on real Qatari plates.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from .types import TrackedObject

# Eastern Arabic-Indic digits as used on Qatari plates.
EASTERN_ARABIC = "٠١٢٣٤٥٦٧٨٩"
_E2W = {ord(e): ord(w) for e, w in zip(EASTERN_ARABIC, "0123456789")}

MAROON_BGR = (28, 26, 138)  # Qatar maroon, approximately


def normalize_digits(text: str) -> str:
    """Map Eastern Arabic-Indic digits to Western and drop everything else."""
    western = text.translate(_E2W)
    return "".join(ch for ch in western if ch.isdigit())


def validate_qatar_plate(text: Optional[str]) -> Optional[str]:
    """Return the normalised plate number if it is a plausible Qatar plate.

    Qatar plates carry 1–6 digits and no letters. Returns ``None`` for empty /
    over-long / letter-bearing reads so callers can retry on a better frame.
    """
    if not text:
        return None
    digits = normalize_digits(text)
    if not (1 <= len(digits) <= 6):
        return None
    return digits


def to_eastern(digits: str) -> str:
    return "".join(EASTERN_ARABIC[int(d)] for d in digits if d.isdigit())


# ---------------------------------------------------------------------- #
# Synthetic plate rendering (demo + OCR templates)
# ---------------------------------------------------------------------- #
# Geometry constants shared by the renderer and the reader so templates match.
_PLATE_AR = 24.0 / 11.0          # width / height, roughly Qatar's long plate
_DIGIT_BAND = (0.42, 0.94)       # vertical span of the big digit row
_FONT_SCALE_PER_PX = 1.0 / 26.0  # cv2 Hershey scale per pixel of digit height


def render_qatar_plate(number: str, width_px: int = 240) -> np.ndarray:
    """Draw a synthetic Qatar-style private plate (BGR image).

    White base, big black Western digits, smaller Eastern-Arabic digits above,
    maroon 'QATAR' legend. Stylised — for demo footage and OCR templates, not
    a replica.
    """
    import cv2

    number = validate_qatar_plate(number) or "0"
    w = int(width_px)
    h = max(8, int(round(w / _PLATE_AR)))
    img = np.full((h, w, 3), 250, dtype=np.uint8)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (90, 90, 90), max(1, w // 120))

    # Maroon legend band (top-left): "QATAR".
    legend_h = int(h * 0.30)
    if legend_h >= 7:
        cv2.putText(img, "QATAR", (int(w * 0.04), int(h * 0.26)),
                    cv2.FONT_HERSHEY_SIMPLEX, legend_h * 0.032,
                    MAROON_BGR, max(1, w // 240), cv2.LINE_AA)

    # Small Eastern-Arabic digits (top-right). Hershey fonts lack Arabic
    # glyphs, so approximate with small dots/strokes only when big enough to
    # matter visually; skipped below 60 px width.
    if w >= 60:
        east = to_eastern(number)
        cv2.putText(img, east, (int(w * 0.62), int(h * 0.26)),
                    cv2.FONT_HERSHEY_SIMPLEX, legend_h * 0.022,
                    (40, 40, 40), 1, cv2.LINE_AA)

    # Big Western digits, centred in the lower band. Drawn one glyph per cell
    # with explicit spacing (like the real plate) so digits never touch —
    # merged glyphs are what break contour-based OCR segmentation.
    band_top, band_bot = (int(h * f) for f in _DIGIT_BAND)
    digit_h = band_bot - band_top
    n = len(number)
    usable_w = int(w * 0.86)
    cell_w = usable_w // n
    scale = digit_h * _FONT_SCALE_PER_PX
    thick = max(1, int(round(digit_h / 9)))
    (cw, th), _ = cv2.getTextSize("8", cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    if cw > cell_w * 0.72:  # shrink to keep a gap between neighbouring digits
        scale *= (cell_w * 0.72) / cw
        thick = max(1, int(round(thick * (cell_w * 0.72) / cw)))
        (cw, th), _ = cv2.getTextSize("8", cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    x0 = (w - cell_w * n) // 2
    y_base = band_top + (digit_h + th) // 2
    for i, d in enumerate(number):
        org = (x0 + i * cell_w + (cell_w - cw) // 2, y_base)
        cv2.putText(img, d, org, cv2.FONT_HERSHEY_SIMPLEX, scale,
                    (10, 10, 10), thick, cv2.LINE_AA)
    return img


# ---------------------------------------------------------------------- #
# Demo OCR: digit segmentation + template correlation
# ---------------------------------------------------------------------- #
_TPL_SIZE = (20, 32)  # (w, h) each digit is normalised to before matching


class QatarPlateReader:
    """Read a synthetic Qatar plate from a vehicle crop. Pipeline-compatible:
    ``reader(frame_bgr, TrackedObject) -> Optional[str]``.

    Steps: crop bbox -> find the bright plate rectangle -> binarise -> segment
    digit contours left-to-right -> correlate each against 0-9 templates
    rendered with the same font -> validate the result as a Qatar number.
    Returns ``None`` when the plate is too small/unreadable, so the pipeline
    retries on a later (closer, larger) frame.
    """

    def __init__(self, min_digit_px: int = 6, min_score: float = 0.55,
                 min_plate_height_px: int = 18) -> None:
        import cv2

        self.min_digit_px = min_digit_px
        self.min_score = min_score
        self.min_plate_height_px = min_plate_height_px
        self._templates: Dict[str, np.ndarray] = {}
        for d in "0123456789":
            # Render each digit large and clean, then normalise like a segment.
            scale = 64 * _FONT_SCALE_PER_PX
            thick = max(1, int(round(64 / 9)))
            (tw, th), _ = cv2.getTextSize(d, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
            canvas = np.full((th + 16, tw + 16), 255, dtype=np.uint8)
            cv2.putText(canvas, d, (8, th + 8), cv2.FONT_HERSHEY_SIMPLEX,
                        scale, 0, thick, cv2.LINE_AA)
            ink = 255 - canvas
            # Tight-crop to the glyph so templates align with the tight
            # bounding boxes produced by contour segmentation.
            ys, xs = np.nonzero(ink > 32)
            ink = ink[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
            self._templates[d] = self._normalise(ink)

    # -- pipeline hook -------------------------------------------------- #
    def __call__(self, frame: np.ndarray, obj: TrackedObject) -> Optional[str]:
        x1, y1, x2, y2 = (int(round(v)) for v in obj.bbox)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
        if x2 - x1 < 12 or y2 - y1 < 12:
            return None
        return self.read_crop(frame[y1:y2, x1:x2])

    # -- core ------------------------------------------------------------ #
    def read_crop(self, crop: np.ndarray) -> Optional[str]:
        import cv2

        if crop.size == 0:
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # The plate is the brightest region on the (dark-ish) car body.
        _, bright = cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if w < 16 or h < 7:
                continue
            ar = w / h
            if not (1.2 <= ar <= 4.5):
                continue
            if best is None or w * h > best[2] * best[3]:
                best = (x, y, w, h)
        if best is None:
            return None
        x, y, w, h = best
        if h < self.min_plate_height_px:
            # Too far away to read reliably — a wrong-but-plausible partial
            # read is worse than no read, so wait for a closer frame.
            return None
        plate = gray[y : y + h, x : x + w]

        # Upscale small plates so digit contours survive segmentation.
        target_h = 64
        f = target_h / plate.shape[0]
        plate = cv2.resize(plate, (max(1, int(plate.shape[1] * f)), target_h),
                           interpolation=cv2.INTER_CUBIC)

        # Keep only the big-digit band and binarise (digits dark -> ink=255).
        band = plate[int(target_h * _DIGIT_BAND[0]) : int(target_h * _DIGIT_BAND[1])]
        _, ink = cv2.threshold(band, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        segs = self._segment(ink)
        if not segs:
            return None
        out: List[str] = []
        for seg in segs:
            digit, score = self._match(seg)
            if score < self.min_score:
                return None  # unreadable frame; let the pipeline retry later
            out.append(digit)
        return validate_qatar_plate("".join(out))

    def _segment(self, ink: np.ndarray) -> List[np.ndarray]:
        import cv2

        contours, _ = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if h < self.min_digit_px or w < 2:
                continue
            if h < ink.shape[0] * 0.4:  # noise / legend remnants
                continue
            boxes.append((x, y, w, h))
        boxes.sort(key=lambda b: b[0])  # left-to-right
        if len(boxes) >= 2:
            # A segment much wider than its peers is two merged digits;
            # reading it as one digit would return a wrong plate number.
            widths = sorted(b[2] for b in boxes)
            median_w = widths[len(widths) // 2]
            if any(b[2] > 1.8 * median_w for b in boxes):
                return []
        return [self._normalise(ink[y : y + h, x : x + w]) for x, y, w, h in boxes]

    @staticmethod
    def _normalise(seg: np.ndarray) -> np.ndarray:
        import cv2

        return cv2.resize(seg, _TPL_SIZE, interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0

    def _match(self, seg: np.ndarray) -> Tuple[str, float]:
        best_d, best_s = "?", -1.0
        for d, tpl in self._templates.items():
            num = float((seg * tpl).sum())
            den = float(np.sqrt((seg ** 2).sum() * (tpl ** 2).sum())) + 1e-9
            score = num / den  # normalised cross-correlation
            if score > best_s:
                best_d, best_s = d, score
        return best_d, best_s
