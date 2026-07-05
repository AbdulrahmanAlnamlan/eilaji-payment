"""Generate synthetic highway footage with *known* ground-truth speeds.

Each vehicle follows a straight world-plane trajectory at a constant, known
speed. We project its ground centre back into the image with the inverse
calibration homography and draw a vivid rectangle there — so the exact same
homography, when inverted by the pipeline, must recover the true world position
and hence the true speed. That closes the loop and lets us assert the whole
detect -> track -> speed chain is correct, no YOLO weights or GPU required.

Outputs:
    <out>.mp4                    the footage
    <out>.calibration.json       calibration used (feed this to the pipeline)
    <out>.ground_truth.json      per-vehicle constant speeds (km/h)

Run:
    python -m speeddet.tools.generate_synthetic_video --out demo/highway.mp4
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import numpy as np

from ..calibration import Calibrator, build_ground_plane_calibration
from ..plates import render_qatar_plate


@dataclass
class Vehicle:
    lane_center_x_m: float     # world X (metres across the road)
    speed_kmh: float           # constant ground-truth speed
    start_time_s: float        # when it enters at the far end
    color_bgr: Tuple[int, int, int]
    start_y_m: float = 58.0    # enters far from the camera
    end_y_m: float = 3.0       # exits near the camera (moving toward camera)
    plate_number: str = ""     # Qatar-style digit plate ("" = no plate drawn)


DEFAULT_VEHICLES = [
    Vehicle(lane_center_x_m=1.8, speed_kmh=52.0, start_time_s=0.0, color_bgr=(60, 220, 60), plate_number="358"),
    Vehicle(lane_center_x_m=5.5, speed_kmh=78.0, start_time_s=0.6, color_bgr=(40, 40, 230), plate_number="42781"),
    Vehicle(lane_center_x_m=9.2, speed_kmh=96.0, start_time_s=1.1, color_bgr=(230, 60, 40), plate_number="9021"),
    Vehicle(lane_center_x_m=5.5, speed_kmh=124.0, start_time_s=2.4, color_bgr=(200, 120, 20), plate_number="674"),
]


def _draw_road(frame: np.ndarray, calib: Calibrator) -> None:
    import cv2

    h, w = frame.shape[:2]
    frame[:] = (60, 60, 60)  # asphalt grey (low saturation -> not a "vehicle")
    # sky-ish band up top
    frame[: int(h * 0.33)] = (120, 105, 90)
    # lane markings: dashed lines along the road at lane boundaries
    road_w = float(calib.world_points[:, 0].max())
    far_y = float(calib.world_points[:, 1].max())
    for lane_x in np.arange(0.0, road_w + 0.1, road_w / 3.0):
        for y in np.arange(4.0, far_y - 2.0, 4.0):
            p0 = calib.world_to_image([(lane_x, y)])[0]
            p1 = calib.world_to_image([(lane_x, y + 2.0)])[0]
            cv2.line(frame, (int(p0[0]), int(p0[1])), (int(p1[0]), int(p1[1])),
                     (200, 200, 200), 1, cv2.LINE_AA)


def _car_pixel_size(calib: Calibrator, img_pt: Tuple[float, float]) -> Tuple[int, int]:
    m_per_px = max(calib.metres_per_pixel_at(img_pt), 1e-6)
    px_per_m = 1.0 / m_per_px
    w_px = int(max(8, round(1.8 * px_per_m)))   # ~1.8 m wide
    h_px = int(max(8, round(2.6 * px_per_m)))   # visual height
    return w_px, h_px


def generate(
    out_path: str | Path,
    width: int = 1280,
    height: int = 720,
    fps: float = 25.0,
    duration_s: float = 5.0,
    speed_limit_kmh: float = 60.0,
    far_road_y_m: float = 60.0,
    vehicles: List[Vehicle] = None,
) -> dict:
    """``far_road_y_m`` sets how much road the camera covers. A long span
    (60 m) is the speed-measurement view; a tighter span (~35 m) at 1080p+
    mimics the zoomed ALPR camera real deployments use, making plates large
    enough to read."""
    import copy

    import cv2

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vehicles = copy.deepcopy(vehicles if vehicles is not None else DEFAULT_VEHICLES)
    for v in vehicles:  # keep trajectories inside the calibrated span
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
        for v in vehicles:
            elapsed = t - v.start_time_s
            if elapsed < 0:
                continue
            speed_mps = v.speed_kmh / 3.6
            # moving toward the camera: world Y decreases from start to end
            y = v.start_y_m - speed_mps * elapsed
            if y < v.end_y_m or y > v.start_y_m:
                continue
            img = calib.world_to_image([(v.lane_center_x_m, y)])[0]
            cx, cy = float(img[0]), float(img[1])
            if not (0 <= cx < width and 0 <= cy < height):
                continue
            w_px, h_px = _car_pixel_size(calib, (cx, cy))
            x1 = int(round(cx - w_px / 2))
            x2 = int(round(cx + w_px / 2))
            y1 = int(round(cy - h_px))
            y2 = int(round(cy))  # bottom edge == ground contact point
            cv2.rectangle(frame, (x1, y1), (x2, y2), v.color_bgr, -1)
            # a darker roof so it reads as a car, still same hue family
            roof = tuple(int(c * 0.7) for c in v.color_bgr)
            cv2.rectangle(frame, (x1, y1), (x2, y1 + max(2, h_px // 3)), roof, -1)
            # Qatar-style rear plate, centred low on the back of the car.
            if v.plate_number:
                plate_w = int(w_px * 0.62)
                if plate_w >= 24:
                    plate = render_qatar_plate(v.plate_number, plate_w)
                    ph, pw = plate.shape[:2]
                    px1 = int(round(cx - pw / 2))
                    py1 = y2 - int(h_px * 0.12) - ph
                    px2, py2p = px1 + pw, py1 + ph
                    if 0 <= px1 and px2 <= width and 0 <= py1 and py2p <= height:
                        frame[py1:py2p, px1:px2] = plate
        writer.write(frame)
    writer.release()

    calib_path = out_path.with_suffix(".calibration.json")
    calib.save(calib_path)

    gt = {
        "fps": fps,
        "width": width,
        "height": height,
        "duration_s": duration_s,
        "speed_limit_kmh": speed_limit_kmh,
        "vehicles": [
            {
                "index": idx,
                "lane_center_x_m": v.lane_center_x_m,
                "speed_kmh": v.speed_kmh,
                "start_time_s": v.start_time_s,
                "is_violation": v.speed_kmh > speed_limit_kmh,
                "plate_number": v.plate_number,
            }
            for idx, v in enumerate(vehicles)
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
    args = ap.parse_args(argv)

    info = generate(
        out_path=args.out,
        width=args.width,
        height=args.height,
        fps=args.fps,
        duration_s=args.duration,
        speed_limit_kmh=args.speed_limit,
    )
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
