"""Speed estimation from per-track world trajectories.

For each track we keep a short, time-stamped history of world-plane positions
(metres). Instantaneous speed is the magnitude of the velocity vector fitted to
that window by least squares:

    X(t) = ax + bx * t
    Y(t) = ay + by * t
    speed = sqrt(bx^2 + by^2)   [m/s]  ->  * 3.6  [km/h]

A least-squares fit over a sliding window is far more robust to per-frame
detection jitter than a naive "distance between last two points / dt", which
amplifies pixel noise. We also require a minimum time span before reporting a
number, so a car that just appeared does not get a wild reading.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple

import numpy as np

MPS_TO_KMH = 3.6


@dataclass
class _History:
    times: Deque[float] = field(default_factory=lambda: deque(maxlen=64))
    xs: Deque[float] = field(default_factory=lambda: deque(maxlen=64))
    ys: Deque[float] = field(default_factory=lambda: deque(maxlen=64))
    last_speed: Optional[float] = None


class SpeedEstimator:
    """Windowed least-squares velocity estimator, one history per track id."""

    def __init__(
        self,
        window_seconds: float = 0.6,
        min_span_seconds: float = 0.25,
        min_samples: int = 4,
        smoothing: float = 0.5,
        max_plausible_kmh: float = 300.0,
    ) -> None:
        self.window_seconds = window_seconds
        self.min_span_seconds = min_span_seconds
        self.min_samples = min_samples
        self.smoothing = smoothing  # EMA factor for the reported value (0=frozen)
        self.max_plausible_kmh = max_plausible_kmh
        self._hist: Dict[int, _History] = {}

    def reset(self, track_id: int) -> None:
        self._hist.pop(track_id, None)

    def update(
        self, track_id: int, timestamp: float, world_xy: Tuple[float, float]
    ) -> Optional[float]:
        """Add a world-position sample and return the current speed in km/h.

        Returns ``None`` until there is enough time span / samples to be
        meaningful.
        """
        h = self._hist.setdefault(track_id, _History())
        h.times.append(float(timestamp))
        h.xs.append(float(world_xy[0]))
        h.ys.append(float(world_xy[1]))

        t = np.fromiter(h.times, dtype=np.float64)
        x = np.fromiter(h.xs, dtype=np.float64)
        y = np.fromiter(h.ys, dtype=np.float64)

        # Keep only the trailing window.
        t_now = t[-1]
        keep = t >= (t_now - self.window_seconds)
        t, x, y = t[keep], x[keep], y[keep]

        if len(t) < self.min_samples:
            return h.last_speed
        span = t[-1] - t[0]
        if span < self.min_span_seconds:
            return h.last_speed

        vx = _lstsq_slope(t, x)
        vy = _lstsq_slope(t, y)
        speed_kmh = float(np.hypot(vx, vy) * MPS_TO_KMH)

        if speed_kmh > self.max_plausible_kmh:
            # Almost certainly an ID swap / bad detection; ignore this sample.
            return h.last_speed

        if h.last_speed is None:
            h.last_speed = speed_kmh
        else:
            a = self.smoothing
            h.last_speed = a * speed_kmh + (1.0 - a) * h.last_speed
        return h.last_speed


def _lstsq_slope(t: np.ndarray, v: np.ndarray) -> float:
    """Slope of the least-squares line v = a + b*t (returns b)."""
    t = t - t.mean()
    denom = float(np.dot(t, t))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(t, v - v.mean()) / denom)
