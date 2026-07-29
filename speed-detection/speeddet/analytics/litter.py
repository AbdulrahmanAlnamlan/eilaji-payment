"""Littering detection: objects ejected from a vehicle window.

Signature we look for — a small track that

1. **appears next to a moving vehicle** (its first sighting overlaps or nearly
   touches that vehicle's box),
2. is **much smaller** than the vehicle,
3. **separates** from the vehicle afterwards (the vehicle drives on, the
   object decelerates and falls behind), and
4. **persists** for a few frames, so a compression artefact or a bird crossing
   the frame does not qualify.

Attribution matters more than detection here: the point is not "an object was
thrown" but "*this* vehicle threw it". Condition 1 is what binds the object to
a plate, and we record both so a reviewer can check the association.

Like the occupant analytics this is classifier-class — it produces a proposal
with the evidence clip attached, never an automatic citation. Detecting the
small object at all needs a detector trained to spot low-contrast debris; the
association logic below is what turns detections into an attributable event.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..events import Event, EventType, Severity
from ..types import TrackedObject
from .base import FrameContext

Bbox = Tuple[float, float, float, float]

#: Detector class names that can never be "litter" — vehicles and people.
NON_LITTER_CLASSES = {"car", "truck", "bus", "motorcycle", "vehicle",
                      "person", "pedestrian"}


def _area(b: Bbox) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _center(b: Bbox) -> Tuple[float, float]:
    return (0.5 * (b[0] + b[2]), 0.5 * (b[1] + b[3]))


def _gap(a: Bbox, b: Bbox) -> float:
    """Pixel gap between two boxes (0 if they overlap)."""
    dx = max(0.0, max(a[0] - b[2], b[0] - a[2]))
    dy = max(0.0, max(a[1] - b[3], b[1] - a[3]))
    return math.hypot(dx, dy)


@dataclass
class LitterConfig:
    #: Ejected object must be at most this fraction of the source vehicle's area.
    max_area_ratio: float = 0.15
    #: Pixel gap at first sighting for the object to be bound to a vehicle.
    spawn_gap_px: float = 30.0
    #: Frames the object must survive before we believe it.
    min_persistence_frames: int = 4
    #: Pixel separation growth that confirms it left the vehicle.
    min_separation_px: float = 25.0
    #: Give up on an unconfirmed candidate after this many seconds.
    candidate_ttl_s: float = 4.0
    #: Once the throw is confirmed, wait up to this long for the source
    #: vehicle's plate to become readable before emitting. An ejection event
    #: with no plate is nearly useless — the vehicle is the whole point — and
    #: the throw is typically detected while the car is still far away, so
    #: emitting instantly loses the attribution that justifies the detector.
    attribution_grace_s: float = 3.0


class LitterAnalyzer:
    def __init__(self, config: Optional[LitterConfig] = None) -> None:
        self.cfg = config or LitterConfig()
        self._candidates: Dict[int, Dict] = {}
        self._seen_tracks: set = set()
        self._reported: set = set()

    def analyze(self, ctx: FrameContext) -> List[Event]:
        cfg = self.cfg
        events: List[Event] = []

        vehicles = [o for o in ctx.objects
                    if o.detection.class_name not in ("person", "pedestrian")
                    and _area(o.bbox) > 0]
        by_id = {o.track_id: o for o in ctx.objects}

        # 1. Bind newly-appeared small objects to a nearby vehicle.
        for obj in ctx.objects:
            if obj.track_id in self._seen_tracks:
                continue
            self._seen_tracks.add(obj.track_id)
            if obj.detection.class_name in NON_LITTER_CLASSES:
                continue
            obj_area = _area(obj.bbox)
            if obj_area <= 0:
                continue
            source: Optional[TrackedObject] = None
            best_gap = float("inf")
            for veh in vehicles:
                if veh.track_id == obj.track_id:
                    continue
                if obj_area > cfg.max_area_ratio * _area(veh.bbox):
                    continue
                gap = _gap(obj.bbox, veh.bbox)
                if gap <= cfg.spawn_gap_px and gap < best_gap:
                    source, best_gap = veh, gap
            if source is not None:
                self._candidates[obj.track_id] = {
                    "t0": ctx.timestamp,
                    "frame0": ctx.frame_index,
                    "source_track": source.track_id,
                    "source_plate": source.plate_text,
                    "source_speed": source.speed_kmh,
                    "origin_center": _center(obj.bbox),
                    "frames": 0,
                    "max_separation": best_gap,
                }

        # 2. Follow candidates: they must persist and separate from the source.
        for tid, cand in list(self._candidates.items()):
            if ctx.timestamp - cand["t0"] > cfg.candidate_ttl_s:
                self._candidates.pop(tid, None)
                continue
            obj = by_id.get(tid)
            if obj is None:
                continue
            cand["frames"] += 1
            source = by_id.get(cand["source_track"])
            if source is not None:
                cand["max_separation"] = max(cand["max_separation"],
                                             _gap(obj.bbox, source.bbox))

            if (tid, "litter") in self._reported:
                continue
            if cand["frames"] < cfg.min_persistence_frames:
                continue
            if cand["max_separation"] < cfg.min_separation_px:
                continue

            # Confirmed. Hold briefly for the plate, which usually resolves a
            # second or two later as the vehicle closes on the camera.
            cand.setdefault("ready_at", ctx.timestamp)
            plate = cand["source_plate"]
            if source is not None and source.plate_text:
                plate = source.plate_text
                cand["source_plate"] = plate
            waited = ctx.timestamp - cand["ready_at"]
            if not plate and waited < cfg.attribution_grace_s:
                continue

            self._reported.add((tid, "litter"))
            events.append(Event(
                type=EventType.LITTERING,
                severity=Severity.MEDIUM,
                timestamp=ctx.timestamp,
                tower_id=ctx.tower_id,
                confidence=round(min(0.95, 0.5 + 0.05 * cand["frames"]), 3),
                track_ids=[cand["source_track"], tid],
                plate_text=cand["source_plate"],
                speed_kmh=cand["source_speed"],
                world_xy=obj.world_xy,
                bbox=obj.bbox,
                message=("Object ejected from vehicle "
                         "(proposal — needs operator confirmation)"),
                metadata={
                    "object_track": tid,
                    "source_track": cand["source_track"],
                    "persistence_frames": cand["frames"],
                    "separation_px": round(cand["max_separation"], 1),
                    "eject_frame": cand["frame0"],
                },
            ))
        return events
