"""Lightweight multi-object tracker (greedy IoU association).

Assigns a persistent ``track_id`` to each vehicle across frames so the speed
estimator can accumulate a per-vehicle trajectory. It uses IoU matching with a
constant-velocity position hint and a small "coast" window so a track survives
a few missed detections.

For production with real YOLO you can swap this for ByteTrack/DeepSORT (e.g.
ultralytics' built-in ``model.track(..., tracker="bytetrack.yaml")``). This
in-house tracker keeps the prototype dependency-light and fully deterministic,
which is exactly what we want for verifying the speed math.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .types import Detection

Bbox = Tuple[float, float, float, float]


def iou(a: Bbox, b: Bbox) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _center(b: Bbox) -> Tuple[float, float]:
    return (0.5 * (b[0] + b[2]), 0.5 * (b[1] + b[3]))


@dataclass
class _Track:
    track_id: int
    bbox: Bbox
    velocity: Tuple[float, float] = (0.0, 0.0)  # centre px/frame
    age: int = 0            # frames since created
    hits: int = 1           # total matched detections
    misses: int = 0         # consecutive frames without a match
    last_detection: Detection = None

    def predict(self) -> Bbox:
        """Constant-velocity guess for where the box will be next frame."""
        vx, vy = self.velocity
        x1, y1, x2, y2 = self.bbox
        return (x1 + vx, y1 + vy, x2 + vx, y2 + vy)


class IouTracker:
    def __init__(
        self,
        iou_threshold: float = 0.2,
        max_misses: int = 15,
        min_hits: int = 2,
    ) -> None:
        self.iou_threshold = iou_threshold
        self.max_misses = max_misses
        self.min_hits = min_hits
        self._tracks: Dict[int, _Track] = {}
        self._next_id = 1

    @property
    def tracks(self) -> Dict[int, _Track]:
        return self._tracks

    def update(self, detections: List[Detection]) -> List[Tuple[int, Detection]]:
        """Associate detections with tracks; return ``(track_id, detection)``.

        Only confirmed tracks (``hits >= min_hits``) are returned so the very
        first, unreliable frame of a new object does not produce a speed sample.
        """
        # 1. Score all (track, detection) pairs by IoU against the predicted box.
        track_ids = list(self._tracks.keys())
        candidates: List[Tuple[float, int, int]] = []
        for tid in track_ids:
            pred = self._tracks[tid].predict()
            for di, det in enumerate(detections):
                score = iou(pred, det.bbox)
                if score >= self.iou_threshold:
                    candidates.append((score, tid, di))

        # 2. Greedy matching, highest IoU first.
        candidates.sort(reverse=True)
        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        matches: List[Tuple[int, int]] = []
        for score, tid, di in candidates:
            if tid in matched_tracks or di in matched_dets:
                continue
            matched_tracks.add(tid)
            matched_dets.add(di)
            matches.append((tid, di))

        # 3. Update matched tracks (refresh velocity from centre displacement).
        for tid, di in matches:
            tr = self._tracks[tid]
            det = detections[di]
            ox, oy = _center(tr.bbox)
            nx, ny = _center(det.bbox)
            tr.velocity = (nx - ox, ny - oy)
            tr.bbox = det.bbox
            tr.last_detection = det
            tr.hits += 1
            tr.age += 1
            tr.misses = 0

        # 4. Age / coast unmatched tracks; drop the stale ones.
        for tid in track_ids:
            if tid in matched_tracks:
                continue
            tr = self._tracks[tid]
            tr.misses += 1
            tr.age += 1
            tr.bbox = tr.predict()  # coast forward on the velocity estimate
            if tr.misses > self.max_misses:
                del self._tracks[tid]

        # 5. Spawn tracks for unmatched detections.
        new_tracks: List[Tuple[int, int]] = []  # (track_id, detection_index)
        for di, det in enumerate(detections):
            if di in matched_dets:
                continue
            tid = self._next_id
            self._next_id += 1
            self._tracks[tid] = _Track(
                track_id=tid, bbox=det.bbox, last_detection=det
            )
            new_tracks.append((tid, di))

        # 6. Report confirmed, currently-visible tracks. Both re-matched tracks
        #    and freshly-spawned ones qualify once they meet ``min_hits`` (a
        #    brand-new track has hits==1, so it only shows immediately when
        #    min_hits <= 1).
        out: List[Tuple[int, Detection]] = []
        for tid, di in matches + new_tracks:
            tr = self._tracks[tid]
            if tr.hits >= self.min_hits:
                out.append((tid, detections[di]))
        return out
