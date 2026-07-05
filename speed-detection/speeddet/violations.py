"""Violation records and the in-memory ring buffer for evidence clips.

Per the post, evidence is a short **video clip** around the violation (a few
seconds before and after) rather than a single still — clips are much harder to
dispute. We keep the most recent frames in a fixed-size ring buffer in memory;
when a violation fires we flush that window to an .mp4.

The ``ViolationLogger`` also enforces a per-track cooldown so one speeding car
does not generate dozens of duplicate violations while it is in frame.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class Violation:
    track_id: int
    speed_kmh: float
    speed_limit_kmh: float
    frame_index: int
    timestamp: float
    bbox: Tuple[float, float, float, float]
    world_xy: Tuple[float, float]
    plate_text: Optional[str] = None
    clip_path: Optional[str] = None

    @property
    def over_by_kmh(self) -> float:
        return self.speed_kmh - self.speed_limit_kmh

    def to_dict(self) -> dict:
        return asdict(self)


class RingBuffer:
    """Fixed-size ring buffer of recent (frame_index, BGR frame) pairs."""

    def __init__(self, capacity: int) -> None:
        self.capacity = max(1, capacity)
        self._buf: Deque[Tuple[int, np.ndarray]] = deque(maxlen=self.capacity)

    def push(self, frame_index: int, frame: np.ndarray) -> None:
        self._buf.append((frame_index, frame.copy()))

    def snapshot(self) -> List[Tuple[int, np.ndarray]]:
        return list(self._buf)

    def __len__(self) -> int:
        return len(self._buf)


class ViolationLogger:
    """Collects violations, dedupes per track, and writes clips + a JSON log."""

    def __init__(
        self,
        output_dir: str | Path,
        speed_limit_kmh: float,
        fps: float,
        cooldown_seconds: float = 5.0,
        clip_enabled: bool = True,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.clips_dir = self.output_dir / "clips"
        self.speed_limit_kmh = speed_limit_kmh
        self.fps = fps
        self.cooldown_seconds = cooldown_seconds
        self.clip_enabled = clip_enabled
        self._last_fire: Dict[int, float] = {}
        self.violations: List[Violation] = []
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if clip_enabled:
            self.clips_dir.mkdir(parents=True, exist_ok=True)

    def should_fire(self, track_id: int, speed_kmh: float, timestamp: float) -> bool:
        if speed_kmh <= self.speed_limit_kmh:
            return False
        last = self._last_fire.get(track_id)
        if last is not None and (timestamp - last) < self.cooldown_seconds:
            return False
        return True

    def record(
        self,
        track_id: int,
        speed_kmh: float,
        frame_index: int,
        timestamp: float,
        bbox: Tuple[float, float, float, float],
        world_xy: Tuple[float, float],
        ring: Optional[RingBuffer] = None,
        plate_text: Optional[str] = None,
    ) -> Violation:
        self._last_fire[track_id] = timestamp
        clip_path: Optional[str] = None
        if self.clip_enabled and ring is not None and len(ring) > 0:
            clip_path = self._write_clip(track_id, frame_index, ring)
        v = Violation(
            track_id=track_id,
            speed_kmh=round(speed_kmh, 2),
            speed_limit_kmh=self.speed_limit_kmh,
            frame_index=frame_index,
            timestamp=round(timestamp, 3),
            bbox=tuple(round(float(c), 1) for c in bbox),
            world_xy=(round(float(world_xy[0]), 2), round(float(world_xy[1]), 2)),
            plate_text=plate_text,
            clip_path=clip_path,
        )
        self.violations.append(v)
        return v

    def _write_clip(self, track_id: int, frame_index: int, ring: RingBuffer) -> Optional[str]:
        import cv2

        frames = ring.snapshot()
        if not frames:
            return None
        h, w = frames[0][1].shape[:2]
        path = self.clips_dir / f"violation_track{track_id:04d}_frame{frame_index:06d}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(path), fourcc, self.fps, (w, h))
        if not writer.isOpened():
            return None
        for _, fr in frames:
            writer.write(fr)
        writer.release()
        return str(path)

    def save_log(self, filename: str = "violations.json") -> Path:
        path = self.output_dir / filename
        payload = {
            "speed_limit_kmh": self.speed_limit_kmh,
            "count": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        return path
