"""ALPR (Automatic Licence Plate Recognition) hook — extension point.

Speed detection is phase 1. The full "smart radar" reads the plate off the
violating vehicle and matches it to an owner record. This module defines the
plug point the pipeline already supports via ``SpeedPipeline(plate_reader=...)``.

A plate reader is any callable ``(frame_bgr, TrackedObject) -> Optional[str]``.
It is only invoked on the frame where a violation fires, on the violating
vehicle's crop — so it runs rarely and can afford a heavier model.

``FastAlprReader`` / ``PaddleOcrReader`` below are thin, lazily-imported
wrappers; neither is required to run the speed core. For Qatar/GCC plates
you would fine-tune the recogniser on local plate fonts and layouts.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .types import TrackedObject


def crop_plate_region(frame: np.ndarray, obj: TrackedObject) -> np.ndarray:
    """Crop the lower portion of the bbox, where the plate usually sits."""
    x1, y1, x2, y2 = (int(v) for v in obj.bbox)
    h = y2 - y1
    y_plate = y1 + int(0.55 * h)  # plates are on the lower half
    y1c, y2c = max(0, y_plate), min(frame.shape[0], y2)
    x1c, x2c = max(0, x1), min(frame.shape[1], x2)
    if y2c <= y1c or x2c <= x1c:
        return frame[0:0, 0:0]
    return frame[y1c:y2c, x1c:x2c]


class FastAlprReader:
    """Wrapper around the ``fast-alpr`` package (detector + OCR)."""

    def __init__(self, **kwargs) -> None:
        try:
            from fast_alpr import ALPR  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "fast-alpr not installed. `pip install fast-alpr` to enable, "
                "or pass your own plate_reader callable."
            ) from exc
        self._alpr = ALPR(**kwargs)

    def __call__(self, frame: np.ndarray, obj: TrackedObject) -> Optional[str]:
        results = self._alpr.predict(frame)
        best, best_conf = None, -1.0
        for r in results or []:
            ocr = getattr(r, "ocr", None)
            if ocr and getattr(ocr, "confidence", 0) > best_conf:
                best, best_conf = ocr.text, ocr.confidence
        return best


class PaddleOcrReader:
    """Wrapper around PaddleOCR applied to the plate crop."""

    def __init__(self, lang: str = "en", **kwargs) -> None:
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "paddleocr not installed. `pip install paddleocr` to enable, "
                "or pass your own plate_reader callable."
            ) from exc
        self._ocr = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False, **kwargs)

    def __call__(self, frame: np.ndarray, obj: TrackedObject) -> Optional[str]:
        crop = crop_plate_region(frame, obj)
        if crop.size == 0:
            return None
        result = self._ocr.ocr(crop, cls=True)
        texts = []
        for line in result or []:
            for _, (text, conf) in line or []:
                if conf > 0.5:
                    texts.append(text)
        return "".join(texts) if texts else None
