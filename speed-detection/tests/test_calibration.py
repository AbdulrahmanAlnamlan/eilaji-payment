"""Homography / calibration correctness."""

import numpy as np

from speeddet.calibration import Calibrator, build_ground_plane_calibration


def _square_calib():
    # Image square maps to a 10m x 20m world rectangle.
    return Calibrator(
        image_points=[(100, 600), (500, 600), (500, 100), (100, 100)],
        world_points=[(0, 0), (10, 0), (10, 20), (0, 20)],
        speed_limit_kmh=60,
    )


def test_corners_roundtrip():
    c = _square_calib()
    world = c.image_to_world([(100, 600), (500, 600), (500, 100), (100, 100)])
    expected = np.array([(0, 0), (10, 0), (10, 20), (0, 20)], dtype=float)
    assert np.allclose(world, expected, atol=1e-6)


def test_inverse_roundtrip():
    c = _square_calib()
    pts = [(123.0, 321.0), (450.0, 200.0), (280.0, 555.0)]
    world = c.image_to_world(pts)
    back = c.world_to_image(world)
    assert np.allclose(back, np.array(pts), atol=1e-6)


def test_center_maps_to_center():
    c = _square_calib()
    # Pixel centre of the square should land near the world-rect centre.
    world = c.image_point_to_world((300, 350))
    assert abs(world[0] - 5.0) < 0.5
    assert abs(world[1] - 10.0) < 1.5  # perspective pulls it, but same ballpark


def test_reprojection_error_small():
    c = _square_calib()
    assert c.reprojection_error() < 1e-3


def test_ground_plane_builder_reasonable():
    c = build_ground_plane_calibration((1280, 720), speed_limit_kmh=80)
    assert c.speed_limit_kmh == 80
    assert c.reprojection_error() < 1.0
    # Near the bottom of the frame the scale is larger (m/px) than up top? No —
    # near the camera 1px covers *fewer* metres than far away.
    near = c.metres_per_pixel_at((640, 700))
    far = c.metres_per_pixel_at((640, 260))
    assert far > near
