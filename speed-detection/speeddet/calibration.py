"""Camera calibration: mapping image pixels to real-world ground coordinates.

We use a planar homography. The road surface is (approximately) a plane, so a
3x3 homography H maps image points to a metric world plane:

    [X_w, Y_w, 1]^T  ~  H . [x_px, y_px, 1]^T

You calibrate by clicking 4+ points in the image whose real-world positions on
the ground you know (lane markings at known spacing, a measured rectangle on
the tarmac, survey points, etc.). World units are **metres**.

This is the single most accuracy-critical part of the whole system — the post
calls it out, and it is what makes speed figures legally defensible. Garbage
calibration in, garbage speeds out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import numpy as np

try:  # pragma: no cover - exercised indirectly
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


Point = Tuple[float, float]


@dataclass
class Calibrator:
    """Homography between image pixels and the metric ground plane."""

    image_points: np.ndarray  # (N, 2) pixel coords
    world_points: np.ndarray  # (N, 2) metres on the ground plane
    speed_limit_kmh: float = 60.0
    notes: str = ""

    H: np.ndarray = None  # image -> world  (filled in __post_init__)
    H_inv: np.ndarray = None  # world -> image

    def __post_init__(self) -> None:
        self.image_points = np.asarray(self.image_points, dtype=np.float64).reshape(-1, 2)
        self.world_points = np.asarray(self.world_points, dtype=np.float64).reshape(-1, 2)
        if len(self.image_points) < 4 or len(self.world_points) < 4:
            raise ValueError("Need at least 4 image/world correspondences for a homography.")
        if len(self.image_points) != len(self.world_points):
            raise ValueError("image_points and world_points must have equal length.")
        self.H = _find_homography(self.image_points, self.world_points)
        self.H_inv = np.linalg.inv(self.H)

    # ------------------------------------------------------------------ #
    # Projection helpers
    # ------------------------------------------------------------------ #
    def image_to_world(self, pts: Sequence[Point]) -> np.ndarray:
        """Project image pixel points onto the world ground plane (metres)."""
        return _apply_homography(self.H, pts)

    def world_to_image(self, pts: Sequence[Point]) -> np.ndarray:
        """Project world ground-plane points back into the image (pixels)."""
        return _apply_homography(self.H_inv, pts)

    def image_point_to_world(self, pt: Point) -> Point:
        out = self.image_to_world([pt])[0]
        return (float(out[0]), float(out[1]))

    def reprojection_error(self) -> float:
        """Mean pixel error when the world points are projected back to image.

        A quick health check on the calibration — large values mean the clicked
        correspondences or measurements are inconsistent.
        """
        proj = self.world_to_image(self.world_points)
        return float(np.mean(np.linalg.norm(proj - self.image_points, axis=1)))

    def metres_per_pixel_at(self, pt: Point) -> float:
        """Approximate local ground scale (m/px) near an image point.

        Perspective means scale varies across the frame; this samples it locally
        by projecting the pixel and a 1-px neighbour to the world plane.
        """
        p0 = self.image_to_world([pt])[0]
        px = self.image_to_world([(pt[0] + 1.0, pt[1])])[0]
        py = self.image_to_world([(pt[0], pt[1] + 1.0)])[0]
        sx = np.linalg.norm(px - p0)
        sy = np.linalg.norm(py - p0)
        return float(0.5 * (sx + sy))

    # ------------------------------------------------------------------ #
    # (de)serialisation
    # ------------------------------------------------------------------ #
    @classmethod
    def from_dict(cls, data: dict) -> "Calibrator":
        return cls(
            image_points=data["image_points"],
            world_points=data["world_points"],
            speed_limit_kmh=float(data.get("speed_limit_kmh", 60.0)),
            notes=str(data.get("notes", "")),
        )

    @classmethod
    def load(cls, path: str | Path) -> "Calibrator":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def to_dict(self) -> dict:
        return {
            "image_points": self.image_points.tolist(),
            "world_points": self.world_points.tolist(),
            "speed_limit_kmh": self.speed_limit_kmh,
            "notes": self.notes,
        }

    def save(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2)


# ---------------------------------------------------------------------- #
# Low-level homography math (numpy fallback if OpenCV is unavailable).
# ---------------------------------------------------------------------- #
def _find_homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Least-squares homography src -> dst using the DLT algorithm.

    Uses cv2.findHomography when available (adds RANSAC robustness); otherwise
    falls back to a pure-numpy Direct Linear Transform so the module has no hard
    OpenCV dependency for the math itself.
    """
    src = np.asarray(src, dtype=np.float64).reshape(-1, 2)
    dst = np.asarray(dst, dtype=np.float64).reshape(-1, 2)
    if cv2 is not None and len(src) >= 4:
        method = cv2.RANSAC if len(src) > 4 else 0
        H, _ = cv2.findHomography(src, dst, method, 3.0)
        if H is not None:
            return H.astype(np.float64)
    return _dlt_homography(src, dst)


def _dlt_homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Pure-numpy Direct Linear Transform homography estimation."""
    n = len(src)
    A = np.zeros((2 * n, 9), dtype=np.float64)
    for i in range(n):
        x, y = src[i]
        u, v = dst[i]
        A[2 * i] = [-x, -y, -1, 0, 0, 0, u * x, u * y, u]
        A[2 * i + 1] = [0, 0, 0, -x, -y, -1, v * x, v * y, v]
    _, _, vt = np.linalg.svd(A)
    H = vt[-1].reshape(3, 3)
    if abs(H[2, 2]) > 1e-12:
        H = H / H[2, 2]
    return H


def _apply_homography(H: np.ndarray, pts: Iterable[Point]) -> np.ndarray:
    pts = np.asarray(list(pts), dtype=np.float64).reshape(-1, 2)
    ones = np.ones((len(pts), 1), dtype=np.float64)
    hom = np.hstack([pts, ones])  # (N, 3)
    out = (H @ hom.T).T  # (N, 3)
    w = out[:, 2:3]
    w = np.where(np.abs(w) < 1e-12, 1e-12, w)
    return out[:, :2] / w


def build_ground_plane_calibration(
    image_size: Tuple[int, int],
    lane_width_m: float = 3.65,
    num_lanes: int = 3,
    near_road_y_m: float = 0.0,
    far_road_y_m: float = 60.0,
    top_frac: float = 0.35,
    bottom_frac: float = 0.98,
    side_frac: float = 0.18,
    speed_limit_kmh: float = 60.0,
) -> Calibrator:
    """Construct a plausible calibration from a road trapezoid in the frame.

    Handy for demos/tests: assumes the camera looks down a straight road. The
    road occupies a trapezoid in the image (wide at the bottom/near, narrow at
    the top/far) mapping to a metric rectangle ``[0, width] x [near, far]``.
    Real deployments should replace this with surveyed correspondences.
    """
    w, h = image_size
    road_w = lane_width_m * num_lanes

    top_y = h * top_frac
    bot_y = h * bottom_frac
    cx = w * 0.5
    half_bottom = w * (0.5 - side_frac * 0.4)
    half_top = w * (0.5 - side_frac)

    image_points = [
        (cx - half_bottom, bot_y),  # near-left
        (cx + half_bottom, bot_y),  # near-right
        (cx + half_top, top_y),     # far-right
        (cx - half_top, top_y),     # far-left
    ]
    world_points = [
        (0.0, near_road_y_m),
        (road_w, near_road_y_m),
        (road_w, far_road_y_m),
        (0.0, far_road_y_m),
    ]
    return Calibrator(
        image_points=image_points,
        world_points=world_points,
        speed_limit_kmh=speed_limit_kmh,
        notes=(
            f"synthetic ground-plane calib: {num_lanes} lanes x {lane_width_m} m, "
            f"road span {far_road_y_m - near_road_y_m} m"
        ),
    )
