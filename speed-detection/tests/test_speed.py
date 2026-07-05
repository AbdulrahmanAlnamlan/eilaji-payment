"""Speed estimator math against analytically-known trajectories."""

import numpy as np

from speeddet.speed import SpeedEstimator, _lstsq_slope


def test_lstsq_slope_exact_line():
    t = np.linspace(0, 2, 20)
    v = 3.0 + 7.0 * t
    assert abs(_lstsq_slope(t, v) - 7.0) < 1e-9


def test_constant_velocity_recovered():
    # Vehicle moving at 25 m/s (== 90 km/h) straight along world Y.
    est = SpeedEstimator(window_seconds=1.0, min_samples=4)
    fps = 25.0
    speed_mps = 25.0
    last = None
    for i in range(40):
        t = i / fps
        world = (5.0, speed_mps * t)
        last = est.update(track_id=1, timestamp=t, world_xy=world)
    assert last is not None
    assert abs(last - 90.0) < 1.0  # km/h


def test_diagonal_velocity_magnitude():
    # Moving at (3, 4) m/s -> 5 m/s -> 18 km/h.
    est = SpeedEstimator(window_seconds=1.0, min_samples=4)
    fps = 20.0
    last = None
    for i in range(40):
        t = i / fps
        world = (3.0 * t, 4.0 * t)
        last = est.update(2, t, world)
    assert abs(last - 18.0) < 0.5


def test_returns_none_before_enough_samples():
    est = SpeedEstimator(min_samples=5, min_span_seconds=0.3)
    assert est.update(1, 0.0, (0.0, 0.0)) is None
    assert est.update(1, 0.04, (0.0, 1.0)) is None


def test_ignores_teleport_spike():
    est = SpeedEstimator(window_seconds=1.0, min_samples=4, max_plausible_kmh=200)
    fps = 25.0
    # Build a stable ~72 km/h (20 m/s) history.
    for i in range(20):
        t = i / fps
        est.update(9, t, (0.0, 20.0 * t))
    stable = est.update(9, 20 / fps, (0.0, 20.0 * (20 / fps)))
    # A single absurd jump (ID swap) must not blow up the reported speed.
    spiked = est.update(9, 21 / fps, (0.0, 999.0))
    assert spiked is not None
    assert spiked < 200
