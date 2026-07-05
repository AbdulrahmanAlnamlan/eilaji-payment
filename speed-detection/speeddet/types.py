"""Small dataclasses shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass
class Detection:
    """A single object detection in image (pixel) coordinates.

    bbox is ``(x1, y1, x2, y2)`` with the origin at the top-left of the frame.
    """

    bbox: Tuple[float, float, float, float]
    confidence: float = 1.0
    class_id: int = 0
    class_name: str = "vehicle"

    @property
    def cx(self) -> float:
        return 0.5 * (self.bbox[0] + self.bbox[2])

    @property
    def cy(self) -> float:
        return 0.5 * (self.bbox[1] + self.bbox[3])

    @property
    def ground_point(self) -> Tuple[float, float]:
        """Bottom-centre of the box — the vehicle's contact point with the road.

        This is the point we project to world coordinates, because it lies on
        the ground plane the homography is calibrated for.
        """
        x1, _, x2, y2 = self.bbox
        return (0.5 * (x1 + x2), y2)

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)


@dataclass
class TrackedObject:
    """A detection that has been associated with a persistent track id."""

    track_id: int
    detection: Detection
    frame_index: int
    timestamp: float
    # Filled in by the pipeline once world mapping + speed are available.
    world_xy: Optional[Tuple[float, float]] = None
    speed_kmh: Optional[float] = None
    is_violation: bool = False
    plate_text: Optional[str] = None
    history_len: int = 1

    # Convenience passthroughs.
    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        return self.detection.bbox

    @property
    def ground_point(self) -> Tuple[float, float]:
        return self.detection.ground_point
