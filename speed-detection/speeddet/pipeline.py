"""The speed-detection pipeline: glue that runs the whole thing on a video.

Per frame:
    detect -> track -> project ground point to world -> estimate speed ->
    check/record violation (+ evidence clip) -> annotate -> write output.

The detector is injected, so the exact same pipeline runs on real footage with
``YoloDetector`` or on the synthetic demo with ``ColorBlobDetector``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol

import numpy as np

from .annotate import draw_calibration_region, draw_hud, draw_tracked_object
from .calibration import Calibrator
from .speed import SpeedEstimator
from .tracking import IouTracker
from .types import Detection, TrackedObject
from .violations import RingBuffer, Violation, ViolationLogger


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> List[Detection]:
        ...


@dataclass
class PipelineConfig:
    output_dir: str = "output"
    write_annotated_video: bool = True
    annotated_video_name: str = "annotated.mp4"
    save_clips: bool = True
    clip_seconds: float = 8.0          # ring-buffer length for evidence clips
    violation_cooldown_seconds: float = 5.0
    speed_window_seconds: float = 0.6
    draw_calibration: bool = True
    # tracker knobs
    iou_threshold: float = 0.2
    max_misses: int = 15
    min_hits: int = 2


@dataclass
class PipelineResult:
    frames_processed: int
    fps: float
    violations: List[Violation]
    max_speed_by_track: Dict[int, float]
    annotated_video: Optional[str]
    violations_log: Optional[str]


class SpeedPipeline:
    def __init__(
        self,
        detector: Detector,
        calibrator: Calibrator,
        config: Optional[PipelineConfig] = None,
        plate_reader: Optional[Callable[[np.ndarray, TrackedObject], Optional[str]]] = None,
    ) -> None:
        self.detector = detector
        self.calib = calibrator
        self.cfg = config or PipelineConfig()
        self.plate_reader = plate_reader
        self.tracker = IouTracker(
            iou_threshold=self.cfg.iou_threshold,
            max_misses=self.cfg.max_misses,
            min_hits=self.cfg.min_hits,
        )
        self.speed = SpeedEstimator(window_seconds=self.cfg.speed_window_seconds)
        self.max_speed_by_track: Dict[int, float] = {}

    # ------------------------------------------------------------------ #
    def run_video(self, video_path: str | Path) -> PipelineResult:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise FileNotFoundError(f"Could not open video: {video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        out_dir = Path(self.cfg.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        writer = None
        annotated_path: Optional[str] = None
        if self.cfg.write_annotated_video:
            annotated_path = str(out_dir / self.cfg.annotated_video_name)
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(annotated_path, fourcc, fps, (w, h))

        ring = RingBuffer(capacity=max(1, int(self.cfg.clip_seconds * fps)))
        vlog = ViolationLogger(
            output_dir=out_dir,
            speed_limit_kmh=self.calib.speed_limit_kmh,
            fps=fps,
            cooldown_seconds=self.cfg.violation_cooldown_seconds,
            clip_enabled=self.cfg.save_clips,
        )

        frame_index = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            ring.push(frame_index, frame)
            timestamp = frame_index / fps
            objects = self._process_frame(frame, frame_index, timestamp)
            self._handle_violations(frame, objects, frame_index, timestamp, ring, vlog)

            if writer is not None:
                annotated = self._annotate(frame, objects, frame_index, timestamp,
                                           len(objects), len(vlog.violations))
                writer.write(annotated)
            frame_index += 1

        cap.release()
        if writer is not None:
            writer.release()

        log_path = str(vlog.save_log())
        return PipelineResult(
            frames_processed=frame_index,
            fps=fps,
            violations=vlog.violations,
            max_speed_by_track=dict(self.max_speed_by_track),
            annotated_video=annotated_path,
            violations_log=log_path,
        )

    # ------------------------------------------------------------------ #
    def _process_frame(
        self, frame: np.ndarray, frame_index: int, timestamp: float
    ) -> List[TrackedObject]:
        detections = self.detector.detect(frame)
        tracked = self.tracker.update(detections)
        objects: List[TrackedObject] = []
        for track_id, det in tracked:
            world_xy = self.calib.image_point_to_world(det.ground_point)
            speed_kmh = self.speed.update(track_id, timestamp, world_xy)
            obj = TrackedObject(
                track_id=track_id,
                detection=det,
                frame_index=frame_index,
                timestamp=timestamp,
                world_xy=world_xy,
                speed_kmh=speed_kmh,
            )
            if speed_kmh is not None:
                prev = self.max_speed_by_track.get(track_id, 0.0)
                self.max_speed_by_track[track_id] = max(prev, speed_kmh)
                obj.is_violation = speed_kmh > self.calib.speed_limit_kmh
            objects.append(obj)
        return objects

    def _handle_violations(
        self, frame, objects, frame_index, timestamp, ring, vlog
    ) -> None:
        for obj in objects:
            if obj.speed_kmh is None:
                continue
            if not vlog.should_fire(obj.track_id, obj.speed_kmh, timestamp):
                continue
            plate = None
            if self.plate_reader is not None:
                try:
                    plate = self.plate_reader(frame, obj)
                except Exception:
                    plate = None
            obj.plate_text = plate
            vlog.record(
                track_id=obj.track_id,
                speed_kmh=obj.speed_kmh,
                frame_index=frame_index,
                timestamp=timestamp,
                bbox=obj.bbox,
                world_xy=obj.world_xy,
                ring=ring,
                plate_text=plate,
            )

    def _annotate(self, frame, objects, frame_index, timestamp, n_tracks, n_viol):
        annotated = frame.copy()
        if self.cfg.draw_calibration:
            draw_calibration_region(annotated, self.calib.image_points)
        for obj in objects:
            draw_tracked_object(annotated, obj)
        draw_hud(annotated, frame_index, timestamp,
                 self.calib.speed_limit_kmh, n_tracks, n_viol)
        return annotated
