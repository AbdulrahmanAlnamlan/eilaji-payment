"""Qatar licence-plate support: format rules, rendering, and a demo OCR.

Current Qatari metal plates carry a **category letter code** (1–2 Latin
letters, shown top-right) plus up to 6 digits, with the "QATAR / قطر" legend
and emblem on the left/top. Category codes (per the MOI plate taxonomy):

    Q   private car / rental / electric      PR  private passenger transport
    TK  private truck                        BS  private bus
    BN  private transport (flatbed/بركدون)   PT  public bus (tourism)
    MH  mobile home                          FD  flatbed private transport
    LI  limousine                            MO  motorcycle
    TR  trailer / semi-trailer               TX  taxi
    TE  temporary exit                       EN  temporary entry
    EX  export                               UE  under-test
    EV  machinery / equipment                NV  off-road-only vehicles
    AQ  antique vehicles                     DP  disability
    CV  commercial                           GV  government
    UN  United Nations                       CD  diplomatic corps
    AP  Amiri protocol

Police, Lekhwiya (ISF), armed forces (QAF) and Amiri Guard plates use
non-standard Arabic layouts and are out of scope for this demo reader.

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

# Eastern Arabic-Indic digits (older plates / handwritten records).
EASTERN_ARABIC = "٠١٢٣٤٥٦٧٨٩"
_E2W = {ord(e): ord(w) for e, w in zip(EASTERN_ARABIC, "0123456789")}

MAROON_BGR = (28, 26, 138)  # Qatar maroon, approximately

#: Valid category codes on current Qatari metal plates (see module docstring).
CATEGORY_CODES = {
    "Q", "PR", "TK", "BS", "BN", "PT", "MH", "FD", "LI", "MO", "TR", "TX",
    "TE", "EN", "EX", "UE", "EV", "NV", "AQ", "DP", "CV", "GV", "UN", "CD",
    "AP",
}
#: Every letter that appears in some category code (the OCR letter alphabet).
CATEGORY_LETTERS = sorted({ch for code in CATEGORY_CODES for ch in code})


def normalize_digits(text: str) -> str:
    """Map Eastern Arabic-Indic digits to Western and drop everything else."""
    western = text.translate(_E2W)
    return "".join(ch for ch in western if ch.isdigit())


def parse_qatar_plate(text: Optional[str]) -> Optional[Tuple[str, str]]:
    """Split a raw read into ``(category_code, digits)``.

    Accepts "TX 42781", "tx42781", "٤٢٧٨١ TX", or bare digits "42781"
    (category unknown -> ""). Returns ``None`` when the letters are not a
    valid category code or the digit count is not 1–6.
    """
    if not text:
        return None
    letters = "".join(ch for ch in str(text).upper() if "A" <= ch <= "Z")
    digits = normalize_digits(str(text))
    if letters and letters not in CATEGORY_CODES:
        return None
    if not (1 <= len(digits) <= 6):
        return None
    return (letters, digits)


def validate_qatar_plate(text: Optional[str]) -> Optional[str]:
    """Return the normalised plate string ("TX 42781" or "42781"), else None."""
    parsed = parse_qatar_plate(text)
    if parsed is None:
        return None
    code, digits = parsed
    return f"{code} {digits}" if code else digits


def to_eastern(digits: str) -> str:
    return "".join(EASTERN_ARABIC[int(d)] for d in digits if d.isdigit())


# ---------------------------------------------------------------------- #
# Synthetic plate rendering (demo + OCR templates)
# ---------------------------------------------------------------------- #
# Geometry constants shared by the renderer and the reader so templates match.
_PLATE_AR = 24.0 / 11.0          # width / height, roughly Qatar's long plate
_LETTER_BAND = (0.08, 0.38)      # vertical span of the category-letter row
_DIGIT_BAND = (0.44, 0.94)       # vertical span of the big digit row
_LETTER_X_MIN = 0.45             # letters sit in the right part of the plate
_FONT_SCALE_PER_PX = 1.0 / 26.0  # cv2 Hershey scale per pixel of digit height


def render_qatar_plate(number: str, width_px: int = 240) -> np.ndarray:
    """Draw a synthetic Qatar-style plate (BGR image).

    Mirrors the current metal-plate layout: maroon 'QATAR' legend top-left,
    the category letter code large at top-right, and the digits across the
    lower row. Stylised — for demo footage and OCR templates, not a replica.
    """
    import cv2

    parsed = parse_qatar_plate(number) or ("", "0")
    code, number = parsed
    w = int(width_px)
    h = max(8, int(round(w / _PLATE_AR)))
    img = np.full((h, w, 3), 250, dtype=np.uint8)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (90, 90, 90), max(1, w // 120))

    # Maroon legend (top-left): "QATAR".
    legend_h = int(h * 0.30)
    if legend_h >= 7:
        cv2.putText(img, "QATAR", (int(w * 0.04), int(h * 0.30)),
                    cv2.FONT_HERSHEY_SIMPLEX, legend_h * 0.030,
                    MAROON_BGR, max(1, w // 240), cv2.LINE_AA)

    # Category letters, large at top-right (like the real plates).
    if code:
        band_top, band_bot = (int(h * f) for f in _LETTER_BAND)
        letter_h = band_bot - band_top
        scale = letter_h * _FONT_SCALE_PER_PX
        thick = max(1, int(round(letter_h / 9)))
        (cw, th), _ = cv2.getTextSize("M", cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
        gap = max(2, cw // 4)
        total = len(code) * cw + (len(code) - 1) * gap
        x = w - int(w * 0.06) - total
        y_base = band_top + (letter_h + th) // 2
        for ch in code:
            cv2.putText(img, ch, (x, y_base), cv2.FONT_HERSHEY_SIMPLEX,
                        scale, (10, 10, 10), thick, cv2.LINE_AA)
            x += cw + gap

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
        self.min_digit_px = min_digit_px
        self.min_score = min_score
        self.min_plate_height_px = min_plate_height_px
        self._digit_templates = {d: self._make_template(d) for d in "0123456789"}
        self._letter_templates = {c: self._make_template(c) for c in CATEGORY_LETTERS}

    @staticmethod
    def _make_template(ch: str) -> np.ndarray:
        import cv2

        # Render the glyph large and clean, then normalise like a segment.
        scale = 64 * _FONT_SCALE_PER_PX
        thick = max(1, int(round(64 / 9)))
        (tw, th), _ = cv2.getTextSize(ch, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
        canvas = np.full((th + 16, tw + 16), 255, dtype=np.uint8)
        cv2.putText(canvas, ch, (8, th + 8), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, 0, thick, cv2.LINE_AA)
        ink = 255 - canvas
        # Tight-crop to the glyph so templates align with the tight
        # bounding boxes produced by contour segmentation.
        ys, xs = np.nonzero(ink > 32)
        ink = ink[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
        return QatarPlateReader._normalise(ink)

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

        # --- digits row -------------------------------------------------- #
        band = plate[int(target_h * _DIGIT_BAND[0]) : int(target_h * _DIGIT_BAND[1])]
        _, ink = cv2.threshold(band, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        segs = self._segment(ink)
        if not segs:
            return None
        digits: List[str] = []
        for seg in segs:
            digit, score = self._match(seg, self._digit_templates)
            if score < self.min_score:
                return None  # unreadable frame; let the pipeline retry later
            digits.append(digit)

        # --- category letters row (top-right) ----------------------------- #
        # Optional: a digits-only read is still returned if the (smaller)
        # letters cannot be resolved on this frame.
        code = self._read_category(plate, target_h)

        text = f"{code} {''.join(digits)}" if code else "".join(digits)
        return validate_qatar_plate(text)

    def _read_category(self, plate: np.ndarray, target_h: int) -> Optional[str]:
        import cv2

        # Crop slightly beyond the nominal letter band so descenders (the
        # tail of 'Q') survive — clipping it makes Q collapse into O.
        top = int(target_h * max(0.0, _LETTER_BAND[0] - 0.04))
        bot = int(target_h * (_DIGIT_BAND[0] - 0.01))
        x0 = int(plate.shape[1] * _LETTER_X_MIN)  # skip the QATAR legend
        band = plate[top:bot, x0:]
        if band.size == 0:
            return None
        _, ink = cv2.threshold(band, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        segs = self._segment(ink)
        if not (1 <= len(segs) <= 2):
            return None
        letters = []
        for seg in segs:
            ch, score = self._match(seg, self._letter_templates)
            if score < self.min_score:
                return None
            letters.append(ch)
        code = "".join(letters)
        return code if code in CATEGORY_CODES else None

    def _segment(self, ink: np.ndarray) -> List[np.ndarray]:
        import cv2

        contours, _ = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        band_w = ink.shape[1]
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if h < self.min_digit_px or w < 2:
                continue
            if h < ink.shape[0] * 0.4:  # noise / legend remnants
                continue
            if x <= 1 or x + w >= band_w - 1:
                continue  # plate border frame leaking into the band crop
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

    @staticmethod
    def _match(seg: np.ndarray, templates: Dict[str, np.ndarray]) -> Tuple[str, float]:
        best_c, best_s = "?", -1.0
        for c, tpl in templates.items():
            num = float((seg * tpl).sum())
            den = float(np.sqrt((seg ** 2).sum() * (tpl ** 2).sum())) + 1e-9
            score = num / den  # normalised cross-correlation
            if score > best_s:
                best_c, best_s = c, score
        return best_c, best_s
