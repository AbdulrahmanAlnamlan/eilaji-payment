"""Generate synthetic footage with *known* ground truth.

Each vehicle follows a world-plane trajectory we choose. We project it back
into the image with the inverse calibration homography and draw it there — so
the same homography, inverted by the pipeline, must recover the true world
position, hence the true speed. That closes the loop and lets us assert the
whole detect -> track -> speed -> analytics chain against numbers we set.

Beyond constant-speed traffic this module can script **incidents** (see
:mod:`speeddet.tools.scenarios`): a rear-end collision with real deceleration
profiles, a vehicle stopping in a live lane, a wrong-way driver, an object
thrown from a window. Those are what the kinematic analyzers are tested on.

Vehicles can also be drawn with a **cabin**: an occupant, a seatbelt sash and
a phone cue, so the occupant-analytics chain has something to read.

Outputs:
    <out>.mp4                    the footage
    <out>.calibration.json       calibration used (feed this to the pipeline)
    <out>.ground_truth.json      per-vehicle truth (speeds, plates, incidents)

Run:
    python -m speeddet.tools.generate_synthetic_video --out demo/highway.mp4
"""

from __future__ import annotations

import argparse
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import numpy as np

from ..calibration import Calibrator, build_ground_plane_calibration
from ..plates import render_qatar_plate

Motion = Callable[[float], Optional[Tuple[float, float]]]


@dataclass
class Vehicle:
    lane_center_x_m: float     # world X (metres across the road)
    speed_kmh: float           # constant ground-truth speed (default motion)
    start_time_s: float        # when it enters at the far end
    color_bgr: Tuple[int, int, int]
    start_y_m: float = 58.0    # enters far from the camera
    end_y_m: float = 3.0       # exits near the camera (moving toward camera)
    plate_number: str = ""     # Qatar-style plate ("" = no plate drawn)
    # --- cabin cues for occupant analytics --------------------------------- #
    draw_cabin: bool = False
    belt_worn: bool = True
    phone_in_use: bool = False
    # --- scripted motion --------------------------------------------------- #
    #: ``motion(elapsed_s) -> (x_m, y_m)`` overrides the constant-speed path.
    #: Return ``None`` to hide the vehicle at that instant.
    motion: Optional[Motion] = None
    label: str = ""

    def position_at(self, t: float) -> Optional[Tuple[float, float]]:
        elapsed = t - self.start_time_s
        if elapsed < 0:
            return None
        if self.motion is not None:
            return self.motion(elapsed)
        y = self.start_y_m - (self.speed_kmh / 3.6) * elapsed
        if y < self.end_y_m or y > self.start_y_m:
            return None
        return (self.lane_center_x_m, y)


@dataclass
class LitterObject:
    """A small object ejected from a vehicle at a given time."""

    source_index: int          # index into the vehicle list
    eject_time_s: float
    #: Sideways offset (m) from the vehicle at ejection.
    lateral_offset_m: float = 1.2
    #: How fast the object sheds the vehicle's forward speed (m/s²).
    decel_mps2: float = 9.0
    color_bgr: Tuple[int, int, int] = (40, 240, 240)
    size_m: float = 0.35
    lifetime_s: float = 3.0


DEFAULT_VEHICLES = [
    Vehicle(lane_center_x_m=1.8, speed_kmh=52.0, start_time_s=0.0,
            color_bgr=(60, 220, 60), plate_number="Q 358",
            draw_cabin=True, belt_worn=True, phone_in_use=False),
    Vehicle(lane_center_x_m=5.5, speed_kmh=78.0, start_time_s=0.6,
            color_bgr=(40, 40, 230), plate_number="TX 42781",
            draw_cabin=True, belt_worn=False, phone_in_use=False),
    Vehicle(lane_center_x_m=9.2, speed_kmh=96.0, start_time_s=1.1,
            color_bgr=(230, 60, 40), plate_number="PR 9021",
            draw_cabin=True, belt_worn=True, phone_in_use=True),
    Vehicle(lane_center_x_m=5.5, speed_kmh=124.0, start_time_s=2.4,
            color_bgr=(200, 120, 20), plate_number="LI 674",
            draw_cabin=True, belt_worn=True, phone_in_use=False),
]


# ---------------------------------------------------------------------- #
# Motion helpers for scripted incidents
# ---------------------------------------------------------------------- #
def constant(x_m: float, y0_m: float, speed_kmh: float,
             y_min: float = 2.0) -> Motion:
    v = speed_kmh / 3.6

    def f(t: float) -> Optional[Tuple[float, float]]:
        y = y0_m - v * t
        return None if y < y_min else (x_m, y)

    return f


def brake_to_stop(x_m: float, y0_m: float, speed_kmh: float,
                  brake_at_s: float, decel_mps2: float,
                  y_min: float = 1.0) -> Motion:
    """Cruise, then brake at ``decel_mps2`` to a full stop and hold."""
    v0 = speed_kmh / 3.6

    def f(t: float) -> Optional[Tuple[float, float]]:
        if t <= brake_at_s:
            y = y0_m - v0 * t
        else:
            dt = t - brake_at_s
            t_stop = v0 / decel_mps2
            if dt < t_stop:
                travelled = v0 * dt - 0.5 * decel_mps2 * dt * dt
            else:
                travelled = v0 * t_stop - 0.5 * decel_mps2 * t_stop * t_stop
            y = y0_m - v0 * brake_at_s - travelled
        return None if y < y_min else (x_m, y)

    return f


def reverse_direction(x_m: float, y0_m: float, speed_kmh: float,
                      y_max: float = 55.0) -> Motion:
    """Wrong-way: travels *away* from the camera (increasing world Y)."""
    v = speed_kmh / 3.6

    def f(t: float) -> Optional[Tuple[float, float]]:
        y = y0_m + v * t
        return None if y > y_max else (x_m, y)

    return f


def swerve(x_m: float, y0_m: float, speed_kmh: float, swerve_at_s: float,
           lateral_m: float = 3.4, duration_s: float = 0.6,
           y_min: float = 2.0) -> Motion:
    """Straight, then a rapid lane change, then straight again."""
    v = speed_kmh / 3.6

    def f(t: float) -> Optional[Tuple[float, float]]:
        y = y0_m - v * t
        if y < y_min:
            return None
        if t <= swerve_at_s:
            x = x_m
        elif t >= swerve_at_s + duration_s:
            x = x_m + lateral_m
        else:
            frac = (t - swerve_at_s) / duration_s
            x = x_m + lateral_m * frac
        return (x, y)

    return f


# ---------------------------------------------------------------------- #
# Rendering
# ---------------------------------------------------------------------- #
def _draw_road(frame: np.ndarray, calib: Calibrator) -> None:
    import cv2

    h, w = frame.shape[:2]
    frame[:] = (60, 60, 60)
    frame[: int(h * 0.33)] = (120, 105, 90)
    road_w = float(calib.world_points[:, 0].max())
    far_y = float(calib.world_points[:, 1].max())
    for lane_x in np.arange(0.0, road_w + 0.1, road_w / 3.0):
        for y in np.arange(4.0, far_y - 2.0, 4.0):
            p0 = calib.world_to_image([(lane_x, y)])[0]
            p1 = calib.world_to_image([(lane_x, y + 2.0)])[0]
            cv2.line(frame, (int(p0[0]), int(p0[1])), (int(p1[0]), int(p1[1])),
                     (200, 200, 200), 1, cv2.LINE_AA)


def _car_pixel_size(calib: Calibrator, img_pt: Tuple[float, float]) -> Tuple[int, int]:
    """Drawn size of a vehicle at an image point.

    Uses the calibration's mean local scale, which blends the lateral and
    depth scales. Under perspective those differ substantially, so drawn
    vehicles are narrower than a true 1.8 m projection — a cosmetic
    approximation of the renderer, not of the measurement path (speed uses
    the ground-contact point, which is exact). It does mean world-space
    lateral offsets in this generator do not map 1:1 onto the drawn vehicle
    width; scenario offsets are chosen in image terms accordingly.
    """
    m_per_px = max(calib.metres_per_pixel_at(img_pt), 1e-6)
    px_per_m = 1.0 / m_per_px
    return (int(max(8, round(1.8 * px_per_m))), int(max(8, round(2.6 * px_per_m))))


def _draw_cabin(frame: np.ndarray, v: Vehicle, x1: int, y1: int,
                x2: int, y2: int) -> None:
    """Draw the windshield band with occupant / belt / phone cues.

    Matches :class:`~speeddet.analytics.occupant.WindshieldROI` defaults so the
    analyzer's crop lands on exactly this content.
    """
    import cv2

    w, h = x2 - x1, y2 - y1
    if w < 18 or h < 24:
        return
    cy1 = y1 + int(0.10 * h)
    cy2 = y1 + int(0.52 * h)
    cx1 = x1 + int(0.08 * w)
    cx2 = x1 + int(0.92 * w)
    if cy2 - cy1 < 8 or cx2 - cx1 < 12:
        return

    cv2.rectangle(frame, (cx1, cy1), (cx2, cy2), (46, 42, 38), -1)  # dark glass
    cw, ch = cx2 - cx1, cy2 - cy1

    # Occupant torso/head, driver side (right in a LHD-facing-camera view).
    ox1 = cx1 + int(cw * 0.52)
    ox2 = cx1 + int(cw * 0.92)
    oy1 = cy1 + int(ch * 0.22)
    cv2.rectangle(frame, (ox1, oy1), (ox2, cy2), (28, 26, 24), -1)

    if v.belt_worn:
        # Bright diagonal sash across the occupant — the cue the demo
        # classifier reads as "belt worn".
        thickness = max(2, int(ch * 0.12))
        cv2.line(frame, (ox1 + int((ox2 - ox1) * 0.15), cy2 - 1),
                 (ox2 - int((ox2 - ox1) * 0.15), oy1 + int(ch * 0.10)),
                 (245, 245, 245), thickness, cv2.LINE_AA)

    if v.phone_in_use:
        # Cyan glow beside the head — the "phone in hand" cue.
        px1 = cx1 + int(cw * 0.36)
        px2 = px1 + max(3, int(cw * 0.13))
        py1 = cy1 + int(ch * 0.26)
        py2 = py1 + max(3, int(ch * 0.34))
        cv2.rectangle(frame, (px1, py1), (px2, py2), (240, 220, 40), -1)


def _draw_vehicle(frame: np.ndarray, calib: Calibrator, v: Vehicle,
                  pos: Tuple[float, float], width: int, height: int) -> None:
    import cv2

    img = calib.world_to_image([pos])[0]
    cx, cy = float(img[0]), float(img[1])
    if not (0 <= cx < width and 0 <= cy < height):
        return
    w_px, h_px = _car_pixel_size(calib, (cx, cy))
    x1 = int(round(cx - w_px / 2))
    x2 = int(round(cx + w_px / 2))
    y1 = int(round(cy - h_px))
    y2 = int(round(cy))
    cv2.rectangle(frame, (x1, y1), (x2, y2), v.color_bgr, -1)

    if v.draw_cabin:
        _draw_cabin(frame, v, x1, y1, x2, y2)
    else:
        roof = tuple(int(c * 0.7) for c in v.color_bgr)
        cv2.rectangle(frame, (x1, y1), (x2, y1 + max(2, h_px // 3)), roof, -1)

    if v.plate_number:
        plate_w = int(w_px * 0.62)
        if plate_w >= 24:
            plate = render_qatar_plate(v.plate_number, plate_w)
            ph, pw = plate.shape[:2]
            px1 = int(round(cx - pw / 2))
            py1 = y2 - int(h_px * 0.12) - ph
            if 0 <= px1 and px1 + pw <= width and 0 <= py1 and py1 + ph <= height:
                frame[py1:py1 + ph, px1:px1 + pw] = plate


def _draw_litter(frame: np.ndarray, calib: Calibrator, pos: Tuple[float, float],
                 size_m: float, color, width: int, height: int) -> None:
    import cv2

    img = calib.world_to_image([pos])[0]
    cx, cy = float(img[0]), float(img[1])
    if not (0 <= cx < width and 0 <= cy < height):
        return
    m_per_px = max(calib.metres_per_pixel_at((cx, cy)), 1e-6)
    s = max(4, int(round(size_m / m_per_px)))
    cv2.rectangle(frame, (int(cx - s / 2), int(cy - s)),
                  (int(cx + s / 2), int(cy)), color, -1)


# ---------------------------------------------------------------------- #
def generate(
    out_path: str | Path,
    width: int = 1280,
    height: int = 720,
    fps: float = 25.0,
    duration_s: float = 5.0,
    speed_limit_kmh: float = 60.0,
    far_road_y_m: float = 60.0,
    vehicles: Optional[List[Vehicle]] = None,
    litter: Optional[List[LitterObject]] = None,
    scenario: str = "traffic",
) -> dict:
    """``far_road_y_m`` sets how much road the camera covers. A long span
    (60 m) is the speed-measurement view; a tighter span (~30 m) at 1080p+
    mimics the zoomed ALPR/occupant camera, making plates and cabins readable."""
    import cv2

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vehicles = copy.deepcopy(vehicles if vehicles is not None else DEFAULT_VEHICLES)
    litter = list(litter or [])
    for v in vehicles:
        if v.motion is None:
            v.start_y_m = min(v.start_y_m, far_road_y_m - 2.0)

    calib = build_ground_plane_calibration(
        (width, height), speed_limit_kmh=speed_limit_kmh, far_road_y_m=far_road_y_m
    )

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Could not open video writer for {out_path}")

    n_frames = int(round(duration_s * fps))
    for i in range(n_frames):
        t = i / fps
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        _draw_road(frame, calib)

        positions: List[Optional[Tuple[float, float]]] = []
        for v in vehicles:
            pos = v.position_at(t)
            positions.append(pos)
            if pos is not None:
                _draw_vehicle(frame, calib, v, pos, width, height)

        for obj in litter:
            src = vehicles[obj.source_index]
            if t < obj.eject_time_s or t > obj.eject_time_s + obj.lifetime_s:
                continue
            eject_pos = src.position_at(obj.eject_time_s)
            if eject_pos is None:
                continue
            dt = t - obj.eject_time_s
            v0 = src.speed_kmh / 3.6
            # Clamp *time*, not distance: past dt = v0/a the kinematic
            # parabola turns over and the object would appear to roll
            # backwards up the road.
            dt = min(dt, v0 / obj.decel_mps2)
            travelled = max(0.0, v0 * dt - 0.5 * obj.decel_mps2 * dt * dt)
            pos = (eject_pos[0] + obj.lateral_offset_m, eject_pos[1] - travelled)
            _draw_litter(frame, calib, pos, obj.size_m, obj.color_bgr, width, height)

        writer.write(frame)
    writer.release()

    calib_path = out_path.with_suffix(".calibration.json")
    calib.save(calib_path)

    gt = {
        "scenario": scenario,
        "fps": fps,
        "width": width,
        "height": height,
        "duration_s": duration_s,
        "speed_limit_kmh": speed_limit_kmh,
        "far_road_y_m": far_road_y_m,
        "vehicles": [
            {
                "index": idx,
                "label": v.label,
                "lane_center_x_m": v.lane_center_x_m,
                "speed_kmh": v.speed_kmh,
                "start_time_s": v.start_time_s,
                "is_violation": v.motion is None and v.speed_kmh > speed_limit_kmh,
                "plate_number": v.plate_number,
                "belt_worn": v.belt_worn,
                "phone_in_use": v.phone_in_use,
                "scripted": v.motion is not None,
            }
            for idx, v in enumerate(vehicles)
        ],
        "litter": [
            {"source_index": o.source_index, "eject_time_s": o.eject_time_s}
            for o in litter
        ],
    }
    gt_path = out_path.with_suffix(".ground_truth.json")
    with open(gt_path, "w", encoding="utf-8") as fh:
        json.dump(gt, fh, indent=2)

    return {
        "video": str(out_path),
        "calibration": str(calib_path),
        "ground_truth": str(gt_path),
        "frames": n_frames,
        "scenario": scenario,
        "speeds_kmh": [v.speed_kmh for v in vehicles],
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic speed-test footage.")
    ap.add_argument("--out", default="demo/highway.mp4", help="output .mp4 path")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=float, default=25.0)
    ap.add_argument("--duration", type=float, default=5.0)
    ap.add_argument("--speed-limit", type=float, default=60.0)
    ap.add_argument("--scenario", default="traffic",
                    help="traffic | collision | stopped | wrong_way | litter | swerve")
    args = ap.parse_args(argv)

    if args.scenario != "traffic":
        from .scenarios import build_scenario

        info = build_scenario(args.scenario, out_path=args.out,
                              speed_limit_kmh=args.speed_limit)
    else:
        info = generate(
            out_path=args.out, width=args.width, height=args.height,
            fps=args.fps, duration_s=args.duration,
            speed_limit_kmh=args.speed_limit,
        )
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
