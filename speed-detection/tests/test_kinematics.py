"""Kinematic analyzers driven by fabricated trajectories.

These are the fast, deterministic tests: we synthesise world-space motion
directly, so a detector's behaviour is checked against exact physics without
rendering or decoding video.
"""

import pytest

from speeddet.analytics.base import FrameContext, TrackState
from speeddet.analytics.kinematics import KinematicAnalyzer, KinematicConfig
from speeddet.events import EventType
from speeddet.types import Detection, TrackedObject


def _obj(track_id, x, y, speed_kmh, t, frame_index, class_name="vehicle"):
    det = Detection(bbox=(100.0, 100.0, 140.0, 160.0), class_name=class_name)
    return TrackedObject(track_id=track_id, detection=det, frame_index=frame_index,
                         timestamp=t, world_xy=(x, y), speed_kmh=speed_kmh)


def _run(tracks_fn, duration_s=8.0, fps=25.0, config=None, limit=60.0):
    """Drive the analyzer over a scripted world trajectory.

    ``tracks_fn(t)`` returns a list of ``(track_id, x, y, speed_kmh)``.
    """
    analyzer = KinematicAnalyzer(config)
    states = {}
    events = []
    n = int(duration_s * fps)
    for i in range(n):
        t = i / fps
        objs = []
        for (tid, x, y, spd) in tracks_fn(t):
            o = _obj(tid, x, y, spd, t, i)
            objs.append(o)
            st = states.setdefault(tid, TrackState(tid))
            st.update(o, t)
        ctx = FrameContext(frame_index=i, timestamp=t, objects=objs, fps=fps,
                           speed_limit_kmh=limit, states=states)
        events += analyzer.analyze(ctx)
    return events


# ---------------------------------------------------------------------- #
def test_normal_traffic_produces_no_anomalies():
    def tracks(t):
        return [(1, 5.5, 60.0 - 16.6 * t, 60.0)] if 60.0 - 16.6 * t > 2 else []

    events = _run(tracks, duration_s=3.0)
    assert events == [], f"clean traffic raised {[e.type for e in events]}"


def test_collision_detected_from_harsh_decel_and_immobility():
    """Vehicle at 80 km/h decelerates at ~25 m/s² to a stop and stays."""
    impact_t = 2.0
    v0 = 80 / 3.6

    def tracks(t):
        if t < impact_t:
            y = 60.0 - v0 * t
            return [(1, 5.5, y, 80.0)]
        dt = t - impact_t
        t_stop = v0 / 25.0
        if dt < t_stop:
            travelled = v0 * dt - 0.5 * 25.0 * dt * dt
            speed = max(0.0, (v0 - 25.0 * dt) * 3.6)
        else:
            travelled = v0 * t_stop - 0.5 * 25.0 * t_stop ** 2
            speed = 0.0
        return [(1, 5.5, 60.0 - v0 * impact_t - travelled, speed)]

    events = _run(tracks, duration_s=6.0)
    collisions = [e for e in events if e.type is EventType.COLLISION]
    assert len(collisions) == 1, f"got {[e.type.value for e in events]}"
    c = collisions[0]
    assert c.confidence >= 0.6
    assert "harsh_decel" in c.metadata["signals"]
    assert c.metadata["signals"].get("post_impact_immobile") == 1.0
    # Fires shortly after the scripted impact, not minutes later.
    assert impact_t <= c.timestamp <= impact_t + 3.0


def test_gentle_braking_to_a_halt_is_not_a_collision():
    """A normal stop (2.5 m/s²) must not be reported as a crash."""
    v0 = 50 / 3.6

    def tracks(t):
        t_stop = v0 / 2.5
        if t < t_stop:
            travelled = v0 * t - 0.5 * 2.5 * t * t
            speed = (v0 - 2.5 * t) * 3.6
        else:
            travelled = v0 * t_stop - 0.5 * 2.5 * t_stop ** 2
            speed = 0.0
        return [(1, 5.5, 60.0 - travelled, max(0.0, speed))]

    events = _run(tracks, duration_s=5.0)
    assert not [e for e in events if e.type is EventType.COLLISION]


def _gentle_stop(v_kmh=30.0, decel=2.5, y0=40.0):
    """A normal, non-violent stop — a breakdown, not a crash."""
    v0 = v_kmh / 3.6
    t_stop = v0 / decel

    def tracks(t):
        if t < t_stop:
            travelled = v0 * t - 0.5 * decel * t * t
            speed = (v0 - decel * t) * 3.6
        else:
            travelled = v0 * t_stop - 0.5 * decel * t_stop ** 2
            speed = 0.0
        return [(1, 5.5, y0 - travelled, max(0.0, speed))]

    return tracks, t_stop


def test_stopped_vehicle_detected_after_dwell():
    tracks, t_stop = _gentle_stop()
    events = _run(tracks, duration_s=14.0)
    # A gradual stop is a breakdown, not a crash.
    assert not [e for e in events if e.type is EventType.COLLISION]
    stopped = [e for e in events if e.type is EventType.STOPPED_VEHICLE]
    assert len(stopped) == 1
    # Must wait out the configured dwell before crying hazard.
    assert stopped[0].timestamp >= t_stop + KinematicConfig().stopped_duration_s - 0.5


def test_briefly_stopped_vehicle_is_not_reported():
    """Stopping for two seconds (traffic) must not raise a hazard."""
    def tracks(t):
        if t < 1.0:
            return [(1, 5.5, 40.0 - 16.6 * t, 60.0)]
        if t < 3.0:
            return [(1, 5.5, 23.4, 0.0)]
        return [(1, 5.5, 23.4 - 10.0 * (t - 3.0), 36.0)]

    events = _run(tracks, duration_s=6.0)
    assert not [e for e in events if e.type is EventType.STOPPED_VEHICLE]


def test_wrong_way_detected():
    """Traffic normally approaches (Y decreasing); this one recedes."""
    def tracks(t):
        return [(1, 1.8, 5.0 + 15.0 * t, 54.0)]

    events = _run(tracks, duration_s=4.0)
    ww = [e for e in events if e.type is EventType.WRONG_WAY]
    assert len(ww) == 1
    assert ww[0].severity >= 40  # CRITICAL


def test_correct_direction_is_not_wrong_way():
    def tracks(t):
        y = 60.0 - 15.0 * t
        return [(1, 1.8, y, 54.0)] if y > 2 else []

    events = _run(tracks, duration_s=3.5)
    assert not [e for e in events if e.type is EventType.WRONG_WAY]


def test_pedestrian_on_roadway_detected():
    def tracks(t):
        return [(9, 5.0 + 0.5 * t, 20.0, 5.0)]

    analyzer = KinematicAnalyzer()
    states, events = {}, []
    for i in range(40):
        t = i / 25.0
        objs = []
        for (tid, x, y, spd) in tracks(t):
            o = _obj(tid, x, y, spd, t, i, class_name="person")
            objs.append(o)
            states.setdefault(tid, TrackState(tid)).update(o, t)
        events += analyzer.analyze(FrameContext(
            frame_index=i, timestamp=t, objects=objs, states=states))
    peds = [e for e in events if e.type is EventType.PEDESTRIAN_ON_ROADWAY]
    assert len(peds) == 1


def test_each_incident_reported_once():
    """A stopped vehicle sitting for half a minute is one event, not sixty."""
    tracks, _ = _gentle_stop()
    events = _run(tracks, duration_s=40.0)
    assert len([e for e in events if e.type is EventType.STOPPED_VEHICLE]) == 1


def test_collision_suppresses_redundant_stopped_event():
    """A crashed vehicle is reported as a collision, not also as 'stopped'."""
    v0 = 80 / 3.6

    def tracks(t):
        if t < 1.0:
            return [(1, 5.5, 60.0 - v0 * t, 80.0)]
        dt = t - 1.0
        t_stop = v0 / 25.0
        if dt < t_stop:
            travelled = v0 * dt - 0.5 * 25.0 * dt * dt
            speed = max(0.0, (v0 - 25.0 * dt) * 3.6)
        else:
            travelled = v0 * t_stop - 0.5 * 25.0 * t_stop ** 2
            speed = 0.0
        return [(1, 5.5, 60.0 - v0 - travelled, speed)]

    events = _run(tracks, duration_s=20.0)
    assert len([e for e in events if e.type is EventType.COLLISION]) == 1
    assert not [e for e in events if e.type is EventType.STOPPED_VEHICLE]


def test_congestion_requires_sustained_low_speed():
    def tracks(t):
        return [(i, 2.0 + i * 1.5, 40.0 - 2.0 * t, 12.0) for i in range(1, 8)]

    events = _run(tracks, duration_s=16.0)
    cong = [e for e in events if e.type is EventType.CONGESTION]
    assert len(cong) == 1
    assert cong[0].metadata["vehicle_count"] >= 6
