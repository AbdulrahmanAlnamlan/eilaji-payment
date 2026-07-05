"""Drawing helpers for the annotated output video / debug frames."""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from .types import TrackedObject

GREEN = (0, 200, 0)
RED = (0, 0, 235)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


def draw_tracked_object(frame: np.ndarray, obj: TrackedObject) -> None:
    import cv2

    x1, y1, x2, y2 = (int(v) for v in obj.bbox)
    color = RED if obj.is_violation else GREEN
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    label = f"#{obj.track_id}"
    if obj.speed_kmh is not None:
        label += f" {obj.speed_kmh:5.1f} km/h"
    if obj.plate_text:
        label += f" [{obj.plate_text}]"

    _label(frame, label, (x1, y1), color)

    # Mark the ground-contact point that gets projected to world coords.
    gx, gy = obj.ground_point
    cv2.circle(frame, (int(gx), int(gy)), 3, color, -1)


def _label(frame: np.ndarray, text: str, org: Tuple[int, int], color) -> None:
    import cv2

    x, y = org
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thick = 0.5, 1
    (tw, th), base = cv2.getTextSize(text, font, scale, thick)
    y_top = max(0, y - th - base - 2)
    cv2.rectangle(frame, (x, y_top), (x + tw + 4, y_top + th + base + 2), color, -1)
    cv2.putText(frame, text, (x + 2, y_top + th + 1), font, scale, WHITE, thick, cv2.LINE_AA)


def draw_hud(frame: np.ndarray, frame_index: int, timestamp: float,
             speed_limit_kmh: float, n_tracks: int, n_violations: int) -> None:
    import cv2

    lines = [
        f"frame {frame_index}  t={timestamp:6.2f}s",
        f"limit {speed_limit_kmh:.0f} km/h",
        f"tracks {n_tracks}  violations {n_violations}",
    ]
    y = 22
    for ln in lines:
        _label(frame, ln, (10, y), BLACK)
        y += 24


def draw_calibration_region(frame: np.ndarray, image_points) -> None:
    """Outline the calibrated ground quadrilateral (sanity-check overlay)."""
    import cv2

    pts = np.asarray(image_points, dtype=np.int32).reshape(-1, 1, 2)
    cv2.polylines(frame, [pts], isClosed=True, color=(255, 180, 0), thickness=1)
