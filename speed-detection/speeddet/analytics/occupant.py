"""In-cabin behaviour analytics: seatbelt and mobile-phone use.

Pipeline per vehicle:

    vehicle bbox -> windshield ROI -> (optional) enhancement -> classifier
                 -> {belt: worn|missing|unclear, phone: in_use|none|unclear}

**Honest statement of what is and isn't proven here.** The ROI extraction,
temporal voting, event emission and review routing are real and tested. The
*classifier itself* is a pluggable interface: ship it with a model trained on
real windshield crops from your own camera geometry. This module provides

* :class:`OnnxOccupantClassifier` — production path, loads a trained model;
* :class:`CueOccupantClassifier`  — deterministic reader of the synthetic
  demo cabins, so the whole chain is runnable/verifiable without a model;
* :class:`NullOccupantClassifier` — always "unclear" (analytics disabled).

Nothing here auto-issues anything. Seatbelt and phone events are
classifier-class: they are emitted with ``requires_review`` set so a human
confirms the crop before enforcement. That is both the legal posture in every
jurisdiction that runs these cameras and the honest engineering position —
windshield glare, sun visors, dark tint and arm position make single-frame
calls unreliable, which is why we vote over frames and still hand it to a
person.

Optics note for the real build: this needs the telephoto head with a circular
polariser to kill windshield reflection, plus near-IR illumination for night
(IR passes tinted glass far better than visible light).
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Protocol, Tuple

import numpy as np

from ..events import Event, EventType, Severity
from ..types import TrackedObject
from .base import FrameContext

BELT_WORN = "belt_worn"
BELT_MISSING = "belt_missing"
PHONE_IN_USE = "phone_in_use"
PHONE_NONE = "phone_none"
UNCLEAR = "unclear"


@dataclass
class OccupantReading:
    belt: str = UNCLEAR
    phone: str = UNCLEAR
    belt_confidence: float = 0.0
    phone_confidence: float = 0.0


class OccupantClassifier(Protocol):
    def classify(self, roi: np.ndarray) -> OccupantReading:
        ...


@dataclass
class WindshieldROI:
    """Geometry of the windshield crop inside a vehicle bounding box.

    Fractions are of the vehicle box, measured from its top-left. Defaults suit
    a rear-facing view of a car approaching the camera; tune per site with the
    calibration tool once you see real crops.
    """

    top: float = 0.10
    bottom: float = 0.52
    left: float = 0.08
    right: float = 0.92
    #: Minimum crop size (px) below which we refuse to classify — a tiny,
    #: far-away windshield produces confident nonsense.
    min_width_px: int = 40
    min_height_px: int = 24

    def crop(self, frame: np.ndarray, obj: TrackedObject) -> Optional[np.ndarray]:
        x1, y1, x2, y2 = obj.bbox
        w, h = x2 - x1, y2 - y1
        if w <= 0 or h <= 0:
            return None
        cx1 = int(round(x1 + self.left * w))
        cx2 = int(round(x1 + self.right * w))
        cy1 = int(round(y1 + self.top * h))
        cy2 = int(round(y1 + self.bottom * h))
        cx1, cy1 = max(0, cx1), max(0, cy1)
        cx2 = min(frame.shape[1], cx2)
        cy2 = min(frame.shape[0], cy2)
        if (cx2 - cx1) < self.min_width_px or (cy2 - cy1) < self.min_height_px:
            return None
        return frame[cy1:cy2, cx1:cx2]


@dataclass
class OccupantConfig:
    roi: WindshieldROI = field(default_factory=WindshieldROI)
    #: Consecutive agreeing readings required before an event is raised.
    #: Temporal voting is what makes this usable: one frame is noise, six
    #: frames of agreement through changing glare is a real observation.
    votes_required: int = 5
    vote_window: int = 12
    #: Minimum mean confidence across the winning votes.
    min_confidence: float = 0.6
    enabled_belt: bool = True
    enabled_phone: bool = True


class NullOccupantClassifier:
    def classify(self, roi: np.ndarray) -> OccupantReading:  # noqa: ARG002
        return OccupantReading()


class OnnxOccupantClassifier:
    """Production path: a small CNN over the windshield crop.

    Expects an ONNX model taking NCHW float input and returning two heads —
    belt logits ``[worn, missing, unclear]`` and phone logits
    ``[none, in_use, unclear]``. Train on crops from your own camera; models
    trained on another country's geometry transfer poorly.
    """

    def __init__(self, model_path: str, input_size: Tuple[int, int] = (128, 128),
                 providers: Optional[List[str]] = None) -> None:
        try:
            import onnxruntime  # noqa: WPS433
        except Exception as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "onnxruntime is required for OnnxOccupantClassifier "
                "(`pip install onnxruntime`)."
            ) from exc
        self._sess = onnxruntime.InferenceSession(
            model_path, providers=providers or ["CPUExecutionProvider"]
        )
        self._input_name = self._sess.get_inputs()[0].name
        self.input_size = input_size

    def classify(self, roi: np.ndarray) -> OccupantReading:
        import cv2

        img = cv2.resize(roi, self.input_size, interpolation=cv2.INTER_AREA)
        img = img.astype(np.float32) / 255.0
        blob = np.transpose(img, (2, 0, 1))[None, ...]
        outputs = self._sess.run(None, {self._input_name: blob})
        belt_logits = np.asarray(outputs[0]).reshape(-1)
        phone_logits = np.asarray(outputs[1]).reshape(-1) if len(outputs) > 1 \
            else np.array([1.0, 0.0, 0.0])
        belt_labels = [BELT_WORN, BELT_MISSING, UNCLEAR]
        phone_labels = [PHONE_NONE, PHONE_IN_USE, UNCLEAR]
        bi = int(np.argmax(belt_logits))
        pi = int(np.argmax(phone_logits))
        return OccupantReading(
            belt=belt_labels[min(bi, 2)],
            phone=phone_labels[min(pi, 2)],
            belt_confidence=float(_softmax(belt_logits)[bi]),
            phone_confidence=float(_softmax(phone_logits)[pi]),
        )


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / (e.sum() + 1e-9)


class CueOccupantClassifier:
    """Reads the synthetic demo cabins (no trained model involved).

    The demo generator draws a cabin containing a dark occupant, a bright
    diagonal sash when the belt is worn, and a bright rectangle beside the
    head when a phone is held. This classifier recovers those cues with plain
    image ops so the full ROI -> vote -> event -> review chain is exercised
    end-to-end. It is a test fixture, not a traffic-enforcement model.
    """

    def __init__(self, sash_min_pixels: int = 12, phone_min_pixels: int = 6,
                 min_cabin_dark_fraction: float = 0.12) -> None:
        self.sash_min_pixels = sash_min_pixels
        self.phone_min_pixels = phone_min_pixels
        self.min_cabin_dark_fraction = min_cabin_dark_fraction

    def classify(self, roi: np.ndarray) -> OccupantReading:
        import cv2

        if roi.size == 0:
            return OccupantReading()
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        area = max(1, roi.shape[0] * roi.shape[1])

        # Gate on finding a cabin at all. Without positive evidence of glass
        # and an occupant behind it, the honest answer is "unclear" — an
        # absent seatbelt and an absent *view of* a seatbelt look identical,
        # and calling the second one a violation is how these systems earn
        # their false-positive reputation.
        dark_fraction = float((v < 90).sum()) / area
        if area <= 400 or dark_fraction < self.min_cabin_dark_fraction:
            return OccupantReading()

        # Seatbelt sash: near-white, high value, low saturation.
        sash_px = int(((v > 200) & (s < 60)).sum())
        # Phone: saturated cyan-ish glow (demo cue), distinct from the sash.
        phone_px = int(((h > 80) & (h < 105) & (s > 120) & (v > 150)).sum())
        sash_frac = sash_px / area
        phone_frac = phone_px / area

        if sash_px >= self.sash_min_pixels:
            belt, belt_conf = BELT_WORN, min(1.0, 0.6 + sash_frac * 12)
        else:
            belt, belt_conf = BELT_MISSING, min(
                1.0, 0.65 + (0.02 - min(sash_frac, 0.02)) * 10)

        if phone_px >= self.phone_min_pixels:
            phone_state, phone_conf = PHONE_IN_USE, min(1.0, 0.6 + phone_frac * 20)
        else:
            phone_state, phone_conf = PHONE_NONE, 0.8

        return OccupantReading(belt=belt, phone=phone_state,
                               belt_confidence=belt_conf,
                               phone_confidence=phone_conf)


class OccupantAnalyzer:
    """Votes classifier readings over time and emits review-class events."""

    def __init__(self, classifier: Optional[OccupantClassifier] = None,
                 config: Optional[OccupantConfig] = None) -> None:
        self.classifier = classifier or NullOccupantClassifier()
        self.cfg = config or OccupantConfig()
        self._belt_votes: Dict[int, Deque[Tuple[str, float]]] = defaultdict(
            lambda: deque(maxlen=self.cfg.vote_window))
        self._phone_votes: Dict[int, Deque[Tuple[str, float]]] = defaultdict(
            lambda: deque(maxlen=self.cfg.vote_window))
        self._reported: set = set()
        self.readings: Dict[int, OccupantReading] = {}

    def analyze(self, ctx: FrameContext) -> List[Event]:
        if ctx.frame is None:
            return []
        events: List[Event] = []
        for obj in ctx.objects:
            roi = self.cfg.roi.crop(ctx.frame, obj)
            if roi is None:
                continue
            reading = self.classifier.classify(roi)
            self.readings[obj.track_id] = reading

            if self.cfg.enabled_belt and reading.belt != UNCLEAR:
                self._belt_votes[obj.track_id].append(
                    (reading.belt, reading.belt_confidence))
                ev = self._maybe_fire(
                    ctx, obj, self._belt_votes[obj.track_id], BELT_MISSING,
                    EventType.NO_SEATBELT, "Driver appears unbelted",
                )
                if ev:
                    events.append(ev)

            if self.cfg.enabled_phone and reading.phone != UNCLEAR:
                self._phone_votes[obj.track_id].append(
                    (reading.phone, reading.phone_confidence))
                ev = self._maybe_fire(
                    ctx, obj, self._phone_votes[obj.track_id], PHONE_IN_USE,
                    EventType.PHONE_USE, "Driver appears to be holding a phone",
                )
                if ev:
                    events.append(ev)
        return events

    def _maybe_fire(self, ctx: FrameContext, obj: TrackedObject,
                    votes: Deque[Tuple[str, float]], target: str,
                    event_type: EventType, message: str) -> Optional[Event]:
        key = (event_type.value, obj.track_id)
        if key in self._reported:
            return None
        agreeing = [c for label, c in votes if label == target]
        if len(agreeing) < self.cfg.votes_required:
            return None
        mean_conf = sum(agreeing) / len(agreeing)
        if mean_conf < self.cfg.min_confidence:
            return None
        self._reported.add(key)
        return Event(
            type=event_type,
            severity=Severity.MEDIUM,
            timestamp=ctx.timestamp,
            tower_id=ctx.tower_id,
            confidence=round(mean_conf, 3),
            track_ids=[obj.track_id],
            plate_text=obj.plate_text,
            speed_kmh=obj.speed_kmh,
            world_xy=obj.world_xy,
            bbox=obj.bbox,
            message=f"{message} (proposal — needs operator confirmation)",
            metadata={"votes": len(agreeing), "window": len(votes),
                      "classifier": type(self.classifier).__name__},
        )
