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
from typing import Any, Callable, Dict, List, Optional, Protocol

import numpy as np

from .annotate import (
    draw_alerts,
    draw_calibration_region,
    draw_hud,
    draw_tracked_object,
)
from .calibration import Calibrator
from .events import Event, EventBus, EventType, Evidence, Severity
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
    # analytics
    tower_id: str = "tower-000"
    #: Publish speeding violations onto the event bus as well as the log.
    publish_speeding_events: bool = True
    #: Attempt a plate read every N frames for vehicles whose plate is not yet
    #: known. Plates must be read for *every* vehicle, not only speeders —
    #: a littering or seatbelt event needs the plate just as much, and those
    #: vehicles are often not speeding. Reading stops per track as soon as a
    #: plate resolves, so the cost is bounded.
    plate_read_interval: int = 2


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
        analyzers: Optional[List[Any]] = None,
        bus: Optional[EventBus] = None,
    ) -> None:
        self.detector = detector
        self.calib = calibrator
        self.cfg = config or PipelineConfig()
        self.plate_reader = plate_reader
        self.analyzers = list(analyzers or [])
        self.bus = bus or EventBus()
        #: Per-track world-space motion state, shared by every analyzer.
        self.track_states: Dict[int, Any] = {}
        self.tracker = IouTracker(
            iou_threshold=self.cfg.iou_threshold,
            max_misses=self.cfg.max_misses,
            min_hits=self.cfg.min_hits,
        )
        self.speed = SpeedEstimator(window_seconds=self.cfg.speed_window_seconds)
        self.max_speed_by_track: Dict[int, float] = {}
        self._plate_by_track: Dict[int, str] = {}
        #: (expiry_timestamp, severity_name, message) shown as alert banners.
        self._active_alerts: List[tuple] = []

    # ------------------------------------------------------------------ #
    def run_video(
        self,
        source: str | int | Path,
        live: Optional[bool] = None,
        max_frames: Optional[int] = None,
        max_seconds: Optional[float] = None,
    ) -> PipelineResult:
        """Run the pipeline over a video file OR a live camera/stream.

        ``source`` accepts a file path, an RTSP/HTTP URL, or a camera index
        (``0`` / ``"0"`` for the first USB/CSI camera).

        Live sources need different handling than files:
          * **Timestamps** come from the wall clock, not ``frame_index / fps``
            — IP cameras frequently report a bogus FPS (0, 90000, …), and
            trusting it would silently corrupt every speed reading.
          * **Dropped frames** trigger reconnect attempts instead of ending
            the run.
        ``live`` is auto-detected from the source (camera index or stream URL)
        but can be forced either way. ``max_frames``/``max_seconds`` bound a
        live run (otherwise it runs until the stream dies or Ctrl-C).
        """
        import time

        import cv2

        src, is_live = _normalise_source(source, live)
        cap = cv2.VideoCapture(src)
        if not cap.isOpened():
            raise FileNotFoundError(f"Could not open video source: {source}")
        meta_fps = cap.get(cv2.CAP_PROP_FPS)
        fps_valid = meta_fps is not None and 1.0 <= meta_fps <= 240.0
        # For files an invalid FPS is rare; fall back to 25. For live sources
        # the nominal fps is only used to size the ring buffer and clip/video
        # writers — speed math uses wall-clock timestamps instead.
        fps = meta_fps if fps_valid else 25.0
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
        t0 = time.monotonic()
        read_failures = 0
        # Violations whose plate could not be read yet: retry on later frames,
        # where the vehicle is closer/larger (tracked per track_id).
        pending_plates: Dict[int, Violation] = {}
        while True:
            if max_frames is not None and frame_index >= max_frames:
                break
            if max_seconds is not None and (time.monotonic() - t0) >= max_seconds:
                break
            ok, frame = cap.read()
            if not ok:
                if not is_live:
                    break  # end of file
                # Live stream hiccup: retry, then attempt one reconnect cycle.
                read_failures += 1
                if read_failures <= 5:
                    time.sleep(0.2)
                    continue
                cap.release()
                time.sleep(1.0)
                cap = cv2.VideoCapture(src)
                if not cap.isOpened() or read_failures > 30:
                    break
                continue
            read_failures = 0
            ring.push(frame_index, frame)
            timestamp = (time.monotonic() - t0) if is_live else frame_index / fps
            objects = self._process_frame(frame, frame_index, timestamp)
            self._read_plates(frame, objects, frame_index)
            self._handle_violations(frame, objects, frame_index, timestamp, ring, vlog,
                                    pending_plates)
            self._retry_pending_plates(frame, objects, pending_plates)
            self._run_analyzers(frame, objects, frame_index, timestamp, fps)

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
            obj.plate_text = self._plate_by_track.get(track_id)
            objects.append(obj)
        return objects

    def _handle_violations(
        self, frame, objects, frame_index, timestamp, ring, vlog,
        pending_plates: Optional[Dict[int, Violation]] = None,
    ) -> None:
        for obj in objects:
            if obj.speed_kmh is None:
                continue
            if not vlog.should_fire(obj.track_id, obj.speed_kmh, timestamp):
                continue
            # Plates are resolved for every vehicle by _read_plates; this may
            # still be None if the vehicle is too far away to read yet, which
            # the pending-plate backfill below resolves on a closer frame.
            plate = obj.plate_text or self._plate_by_track.get(obj.track_id)
            obj.plate_text = plate
            violation = vlog.record(
                track_id=obj.track_id,
                speed_kmh=obj.speed_kmh,
                frame_index=frame_index,
                timestamp=timestamp,
                bbox=obj.bbox,
                world_xy=obj.world_xy,
                ring=ring,
                plate_text=plate,
            )
            self._publish_speeding(violation, frame_index, timestamp)
            plate_incomplete = plate is None or plate.replace(" ", "").isdigit()
            if plate_incomplete and self.plate_reader is not None and pending_plates is not None:
                pending_plates[obj.track_id] = violation

    def _retry_pending_plates(
        self, frame, objects, pending_plates: Dict[int, Violation]
    ) -> None:
        """Violations often fire while the car is still far away and its plate
        unreadable. Keep trying on later frames — the vehicle gets closer and
        larger — and backfill the violation record with the best read.

        Qatar plates carry a category letter code above the digits; the small
        letters resolve later than the digits, so a digits-only read is kept
        as provisional and upgraded to the full "CODE digits" form when a
        closer frame resolves the letters (only if the digits agree)."""
        if not pending_plates or self.plate_reader is None:
            return
        for obj in objects:
            violation = pending_plates.get(obj.track_id)
            if violation is None:
                continue
            plate = self._plate_by_track.get(obj.track_id)
            if not plate:
                continue
            current = violation.plate_text
            has_code = not plate.replace(" ", "").isdigit()
            if current is None:
                violation.plate_text = plate
            elif has_code and plate.split()[-1] == current:
                violation.plate_text = plate  # upgrade digits-only -> full
            else:
                continue
            obj.plate_text = violation.plate_text
            self._plate_by_track[obj.track_id] = violation.plate_text
            if has_code:
                del pending_plates[obj.track_id]  # nothing left to improve

    # ------------------------------------------------------------------ #
    def _record_plate(self, track_id: int, plate: Optional[str]) -> Optional[str]:
        """Store a plate read, upgrading a digits-only read to the full form.

        Qatar plates carry a category code above the digits; the small letters
        resolve later than the digits, so a bare-digits read is provisional and
        is replaced once the letters appear — but only if the digits agree.
        """
        if not plate:
            return self._plate_by_track.get(track_id)
        current = self._plate_by_track.get(track_id)
        if current is None:
            self._plate_by_track[track_id] = plate
            return plate
        has_code = not plate.replace(" ", "").isdigit()
        current_digits_only = current.replace(" ", "").isdigit()
        if has_code and current_digits_only and plate.split()[-1] == current:
            self._plate_by_track[track_id] = plate
            return plate
        return current

    def _read_plates(self, frame, objects, frame_index: int) -> None:
        """Opportunistically read the plate of any vehicle we cannot yet name."""
        if self.plate_reader is None:
            return
        interval = max(1, self.cfg.plate_read_interval)
        if frame_index % interval:
            # Still propagate what we already know to this frame's objects.
            for obj in objects:
                known = self._plate_by_track.get(obj.track_id)
                if known:
                    obj.plate_text = known
            return
        for obj in objects:
            known = self._plate_by_track.get(obj.track_id)
            # Keep trying while the read is still digits-only, so the category
            # code can be filled in from a closer frame.
            if known and not known.replace(" ", "").isdigit():
                obj.plate_text = known
                continue
            try:
                plate = self.plate_reader(frame, obj)
            except Exception:
                plate = None
            obj.plate_text = self._record_plate(obj.track_id, plate) or known

    # ------------------------------------------------------------------ #
    def _run_analyzers(self, frame, objects, frame_index, timestamp, fps) -> None:
        """Update shared track state, then run every analyzer on this frame."""
        if not self.analyzers:
            return
        from .analytics.base import FrameContext, TrackState

        for obj in objects:
            state = self.track_states.get(obj.track_id)
            if state is None:
                state = TrackState(obj.track_id)
                self.track_states[obj.track_id] = state
            state.update(obj, timestamp)

        ctx = FrameContext(
            frame_index=frame_index,
            timestamp=timestamp,
            objects=objects,
            frame=frame,
            fps=fps,
            speed_limit_kmh=self.calib.speed_limit_kmh,
            tower_id=self.cfg.tower_id,
            states=self.track_states,
        )
        for analyzer in self.analyzers:
            try:
                for event in analyzer.analyze(ctx):
                    if event.evidence is None:
                        event.evidence = Evidence(frame_index=frame_index,
                                                  timestamp=timestamp)
                    if self.bus.publish(event) and event.severity >= Severity.MEDIUM:
                        self._active_alerts.append(
                            (timestamp + 4.0, event.severity.name, event.message))
            except Exception:
                # One misbehaving analyzer must not stop the others or the
                # speed pipeline, which is the instrument-grade path.
                continue

    def _publish_speeding(self, violation: Violation, frame_index: int,
                          timestamp: float) -> None:
        if not self.cfg.publish_speeding_events:
            return
        over = violation.over_by_kmh
        severity = (Severity.HIGH if over >= 40 else
                    Severity.MEDIUM if over >= 20 else Severity.LOW)
        self.bus.publish(Event(
            type=EventType.SPEEDING,
            severity=severity,
            timestamp=timestamp,
            tower_id=self.cfg.tower_id,
            confidence=1.0,
            track_ids=[violation.track_id],
            plate_text=violation.plate_text,
            speed_kmh=violation.speed_kmh,
            speed_limit_kmh=violation.speed_limit_kmh,
            world_xy=violation.world_xy,
            bbox=violation.bbox,
            message=(f"{violation.speed_kmh:.0f} km/h in a "
                     f"{violation.speed_limit_kmh:.0f} zone (+{over:.0f})"),
            evidence=Evidence(frame_index=frame_index, timestamp=timestamp,
                              clip_path=violation.clip_path),
        ))

    # ------------------------------------------------------------------ #
    def _annotate(self, frame, objects, frame_index, timestamp, n_tracks, n_viol):
        annotated = frame.copy()
        if self.cfg.draw_calibration:
            draw_calibration_region(annotated, self.calib.image_points)
        for obj in objects:
            draw_tracked_object(annotated, obj)
        draw_hud(annotated, frame_index, timestamp,
                 self.calib.speed_limit_kmh, n_tracks, n_viol)
        self._active_alerts = [a for a in self._active_alerts if a[0] > timestamp]
        if self._active_alerts:
            draw_alerts(annotated, [(sev, msg) for _, sev, msg in self._active_alerts])
        return annotated


STREAM_SCHEMES = ("rtsp://", "rtmp://", "http://", "https://", "udp://", "tcp://")


def _normalise_source(source, live):
    """Return ``(opencv_source, is_live)``.

    A bare integer (or digit string) is a local camera index; a URL with a
    streaming scheme is a network stream. Both are live. Anything else is
    treated as a file path unless ``live`` overrides the guess.
    """
    if isinstance(source, int):
        return source, True if live is None else live
    s = str(source)
    if s.isdigit():
        return int(s), True if live is None else live
    is_stream = s.lower().startswith(STREAM_SCHEMES)
    return s, is_stream if live is None else live
