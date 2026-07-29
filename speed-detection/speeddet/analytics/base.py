"""Shared context and per-track state for all analyzers."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Protocol, Tuple

import numpy as np

from ..events import Event
from ..types import TrackedObject


@dataclass
class FrameContext:
    """Everything an analyzer may look at for one frame."""

    frame_index: int
    timestamp: float
    objects: List[TrackedObject]
    frame: Optional[np.ndarray] = None
    fps: float = 25.0
    speed_limit_kmh: float = 60.0
    tower_id: str = "tower-000"
    #: Per-track motion state, maintained by the pipeline and shared by all
    #: analyzers so the world-space kinematics are computed exactly once.
    states: Dict[int, "TrackState"] = field(default_factory=dict)


class Analyzer(Protocol):
    def analyze(self, ctx: FrameContext) -> List[Event]:
        ...


@dataclass
class Sample:
    t: float
    x: float
    y: float
    speed_kmh: Optional[float]


class TrackState:
    """Rolling world-space motion history for one tracked object.

    Speed comes from the pipeline's :class:`~speeddet.speed.SpeedEstimator`
    (least-squares, already smoothed). Heading and acceleration are derived
    here over a short window so that anomaly detection sees stable numbers
    rather than per-frame jitter.
    """

    MAXLEN = 128

    def __init__(self, track_id: int, history_seconds: float = 4.0) -> None:
        self.track_id = track_id
        self.history_seconds = history_seconds
        self.samples: Deque[Sample] = deque(maxlen=self.MAXLEN)
        self.first_seen: Optional[float] = None
        self.last_seen: Optional[float] = None
        self.plate_text: Optional[str] = None
        self.class_name: str = "vehicle"
        self.max_speed_kmh: float = 0.0
        #: Set once an analyzer has raised a terminal event for this track
        #: (e.g. collision) so downstream detectors do not double-report.
        self.flags: Dict[str, float] = {}

    # -- ingestion ------------------------------------------------------- #
    def update(self, obj: TrackedObject, timestamp: float) -> None:
        if obj.world_xy is None:
            return
        if self.first_seen is None:
            self.first_seen = timestamp
        self.last_seen = timestamp
        self.class_name = obj.detection.class_name
        if obj.plate_text:
            self.plate_text = obj.plate_text
        if obj.speed_kmh is not None:
            self.max_speed_kmh = max(self.max_speed_kmh, obj.speed_kmh)
        self.samples.append(
            Sample(t=timestamp, x=float(obj.world_xy[0]),
                   y=float(obj.world_xy[1]), speed_kmh=obj.speed_kmh)
        )
        # Drop anything older than the history window.
        cutoff = timestamp - self.history_seconds
        while self.samples and self.samples[0].t < cutoff:
            self.samples.popleft()

    # -- derived quantities ---------------------------------------------- #
    @property
    def age(self) -> float:
        if self.first_seen is None or self.last_seen is None:
            return 0.0
        return self.last_seen - self.first_seen

    @property
    def position(self) -> Optional[Tuple[float, float]]:
        if not self.samples:
            return None
        s = self.samples[-1]
        return (s.x, s.y)

    @property
    def speed_kmh(self) -> Optional[float]:
        for s in reversed(self.samples):
            if s.speed_kmh is not None:
                return s.speed_kmh
        return None

    def speed_at(self, seconds_ago: float) -> Optional[float]:
        """Most recent speed sample at least ``seconds_ago`` in the past."""
        if not self.samples:
            return None
        target = self.samples[-1].t - seconds_ago
        best = None
        for s in self.samples:
            if s.t <= target and s.speed_kmh is not None:
                best = s.speed_kmh
        return best

    def velocity(self, window: float = 0.5) -> Optional[Tuple[float, float]]:
        """Least-squares world velocity (m/s) over the trailing window."""
        pts = [s for s in self.samples if s.t >= self.samples[-1].t - window] \
            if self.samples else []
        if len(pts) < 3:
            return None
        t = np.array([p.t for p in pts])
        if float(t.max() - t.min()) < 1e-3:
            return None
        t = t - t.mean()
        denom = float(np.dot(t, t))
        if denom < 1e-9:
            return None
        vx = float(np.dot(t, np.array([p.x for p in pts]) - np.mean([p.x for p in pts])) / denom)
        vy = float(np.dot(t, np.array([p.y for p in pts]) - np.mean([p.y for p in pts])) / denom)
        return (vx, vy)

    def heading_deg(self, window: float = 0.5) -> Optional[float]:
        v = self.velocity(window)
        if v is None:
            return None
        vx, vy = v
        if abs(vx) < 1e-6 and abs(vy) < 1e-6:
            return None
        return math.degrees(math.atan2(vy, vx))

    def acceleration_mps2(self, window: float = 0.6) -> Optional[float]:
        """Signed longitudinal acceleration over the window (negative = braking)."""
        now = self.speed_kmh
        then = self.speed_at(window)
        if now is None or then is None:
            return None
        dt = window
        return ((now - then) / 3.6) / dt

    def displacement(self, window: float = 2.0) -> Optional[float]:
        """Straight-line world distance covered in the trailing window (m)."""
        if len(self.samples) < 2:
            return None
        t_end = self.samples[-1].t
        older = [s for s in self.samples if s.t <= t_end - window]
        if not older:
            return None
        a, b = older[-1], self.samples[-1]
        return float(math.hypot(b.x - a.x, b.y - a.y))


def heading_delta(a: float, b: float) -> float:
    """Smallest absolute angle between two headings, in degrees (0..180)."""
    d = abs((a - b) % 360.0)
    return d if d <= 180.0 else 360.0 - d
