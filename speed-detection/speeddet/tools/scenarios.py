"""Scripted incident scenarios — the ground truth the analyzers are tested on.

Each builder returns footage plus a ground-truth JSON stating what happened and
when, so a test can assert "the collision analyzer fired, once, within N
seconds of the scripted impact". That is the difference between a demo and a
verified detector.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .generate_synthetic_video import (
    LitterObject,
    Vehicle,
    brake_to_stop,
    constant,
    generate,
    reverse_direction,
    swerve,
)

# Camera geometry for incident footage. Kinematic scenarios need a long road
# span so a braking manoeuvre fits inside the field of view — at 80 km/h a
# vehicle crosses 40 m in under two seconds, which is not enough road to brake,
# stop and be observed. Occupant scenarios override this with a tight span.
_W, _H, _FPS, _FAR = 1920, 1080, 25.0, 75.0


def collision(out_path: str | Path, speed_limit_kmh: float = 60.0) -> dict:
    """Rear-end shunt: the lead brakes to a stop, the follower runs into it.

    The lead brakes normally (5 m/s²) and stops around y≈30 m. The follower
    arrives later and decelerates at 25 m/s² — three times harder than any
    real brake, which is what an impact looks like — coming to rest a car
    length behind. Both then sit still. That triple (harsh decel + proximity
    + post-impact immobility) is the signature the analyzer confirms on.
    """
    lead = Vehicle(
        lane_center_x_m=5.5, speed_kmh=55.0, start_time_s=0.0,
        color_bgr=(60, 200, 60), plate_number="Q 4471", label="lead",
        motion=brake_to_stop(x_m=5.5, y0_m=62.0, speed_kmh=55.0,
                             brake_at_s=0.6, decel_mps2=5.0, y_min=0.5),
    )
    follower = Vehicle(
        lane_center_x_m=5.5, speed_kmh=78.0, start_time_s=2.0,
        color_bgr=(40, 40, 230), plate_number="PR 8823", label="follower",
        motion=brake_to_stop(x_m=5.5, y0_m=70.0, speed_kmh=78.0,
                             brake_at_s=1.2, decel_mps2=25.0, y_min=0.5),
    )
    bystander = Vehicle(
        lane_center_x_m=9.2, speed_kmh=64.0, start_time_s=0.4,
        color_bgr=(200, 140, 30), plate_number="TX 1902", label="bystander",
        motion=constant(x_m=9.2, y0_m=70.0, speed_kmh=64.0),
    )
    info = generate(
        out_path=out_path, width=_W, height=_H, fps=_FPS, duration_s=9.0,
        speed_limit_kmh=speed_limit_kmh, far_road_y_m=_FAR,
        vehicles=[lead, follower, bystander], scenario="collision",
    )
    _annotate_truth(info, {
        "expected_events": ["collision"],
        "impact_time_s": 4.1,
        "impact_tolerance_s": 3.0,
        "vehicles_involved": ["lead", "follower"],
    })
    return info


def stopped_vehicle(out_path: str | Path, speed_limit_kmh: float = 60.0) -> dict:
    """A vehicle comes to rest in a live lane and stays there (breakdown)."""
    # Braking distance must fit inside the calibrated span or the vehicle
    # simply leaves frame: 60 km/h at 6 m/s² needs 23 m of road plus the
    # reaction distance, so it starts far back and comes to rest around 29 m.
    broken = Vehicle(
        lane_center_x_m=5.5, speed_kmh=60.0, start_time_s=0.0,
        color_bgr=(50, 50, 220), plate_number="Q 7788", label="broken_down",
        motion=brake_to_stop(x_m=5.5, y0_m=60.0, speed_kmh=60.0,
                             brake_at_s=0.5, decel_mps2=6.0, y_min=0.5),
    )
    passing = Vehicle(
        lane_center_x_m=9.2, speed_kmh=70.0, start_time_s=2.0,
        color_bgr=(60, 200, 60), plate_number="TX 3310", label="passing",
        motion=constant(x_m=9.2, y0_m=70.0, speed_kmh=70.0),
    )
    info = generate(
        out_path=out_path, width=_W, height=_H, fps=_FPS, duration_s=14.0,
        speed_limit_kmh=speed_limit_kmh, far_road_y_m=_FAR,
        vehicles=[broken, passing], scenario="stopped",
    )
    _annotate_truth(info, {
        "expected_events": ["stopped_vehicle"],
        "stop_time_s": 6.1,
        "vehicles_involved": ["broken_down"],
    })
    return info


def wrong_way(out_path: str | Path, speed_limit_kmh: float = 60.0) -> dict:
    """A vehicle driving against the flow — the highest-severity live hazard."""
    ghost = Vehicle(
        lane_center_x_m=1.8, speed_kmh=55.0, start_time_s=0.0,
        color_bgr=(40, 40, 235), plate_number="Q 1313", label="wrong_way",
        motion=reverse_direction(x_m=1.8, y0_m=6.0, speed_kmh=55.0, y_max=_FAR - 3),
    )
    normal = Vehicle(
        lane_center_x_m=9.2, speed_kmh=68.0, start_time_s=0.0,
        color_bgr=(60, 200, 60), plate_number="PR 5150", label="normal",
        motion=constant(x_m=9.2, y0_m=36.0, speed_kmh=68.0),
    )
    info = generate(
        out_path=out_path, width=_W, height=_H, fps=_FPS, duration_s=8.0,
        speed_limit_kmh=speed_limit_kmh, far_road_y_m=_FAR,
        vehicles=[ghost, normal], scenario="wrong_way",
    )
    _annotate_truth(info, {
        "expected_events": ["wrong_way"],
        "vehicles_involved": ["wrong_way"],
    })
    return info


def littering(out_path: str | Path, speed_limit_kmh: float = 60.0) -> dict:
    """An object is thrown from the window of a moving car at t = 2.0 s."""
    # A thrown object is ~0.3 m across. On the wide speed-camera view that is
    # 4-5 px and undetectable — littering enforcement needs the tighter camera,
    # so this scenario uses a 32 m span.
    thrower = Vehicle(
        lane_center_x_m=5.5, speed_kmh=50.0, start_time_s=0.0,
        color_bgr=(200, 60, 40), plate_number="TX 6642", label="thrower",
        motion=constant(x_m=5.5, y0_m=28.0, speed_kmh=50.0, y_min=1.5),
    )
    info = generate(
        out_path=out_path, width=_W, height=_H, fps=_FPS, duration_s=7.0,
        speed_limit_kmh=speed_limit_kmh, far_road_y_m=32.0,
        vehicles=[thrower],
        # Small lateral offset: the object must leave the window *adjacent* to
        # the car in image space for the analyzer to attribute it to that
        # vehicle, and perspective magnifies lateral offsets near the camera.
        litter=[LitterObject(source_index=0, eject_time_s=0.8,
                             lateral_offset_m=0.55, decel_mps2=7.0,
                             size_m=0.5, lifetime_s=4.0)],
        scenario="litter",
    )
    _annotate_truth(info, {
        "expected_events": ["littering"],
        "eject_time_s": 2.0,
        "vehicles_involved": ["thrower"],
    })
    return info


def erratic(out_path: str | Path, speed_limit_kmh: float = 60.0) -> dict:
    """A violent lane change — the weaving/erratic-driving signature."""
    # Start far back: at 88 km/h the vehicle crosses 34 m in 1.4 s, which is
    # less than the swerve takes — it would leave frame mid-manoeuvre.
    weaver = Vehicle(
        lane_center_x_m=2.0, speed_kmh=88.0, start_time_s=0.0,
        color_bgr=(30, 180, 240), plate_number="Q 9095", label="weaver",
        motion=swerve(x_m=2.0, y0_m=70.0, speed_kmh=88.0, swerve_at_s=1.5,
                      lateral_m=3.6, duration_s=0.5, y_min=2.0),
    )
    info = generate(
        out_path=out_path, width=_W, height=_H, fps=_FPS, duration_s=6.0,
        speed_limit_kmh=speed_limit_kmh, far_road_y_m=_FAR,
        vehicles=[weaver], scenario="swerve",
    )
    _annotate_truth(info, {
        "expected_events": ["erratic_driving"],
        "swerve_time_s": 1.2,
        "vehicles_involved": ["weaver"],
    })
    return info


def occupant(out_path: str | Path, speed_limit_kmh: float = 60.0) -> dict:
    """Two cars driven slowly past the camera with known cabin state.

    Slow so the cabin stays large in frame long enough for the vote window —
    this is the occupant-analytics camera's job, not the speed camera's.
    """
    unbelted = Vehicle(
        lane_center_x_m=3.6, speed_kmh=32.0, start_time_s=0.0,
        color_bgr=(70, 70, 200), plate_number="Q 2024", label="unbelted",
        draw_cabin=True, belt_worn=False, phone_in_use=False,
        motion=constant(x_m=3.6, y0_m=22.0, speed_kmh=32.0, y_min=2.0),
    )
    phoning = Vehicle(
        lane_center_x_m=7.4, speed_kmh=30.0, start_time_s=0.3,
        color_bgr=(60, 170, 70), plate_number="PR 3080", label="phoning",
        draw_cabin=True, belt_worn=True, phone_in_use=True,
        motion=constant(x_m=7.4, y0_m=22.0, speed_kmh=30.0, y_min=2.0),
    )
    info = generate(
        out_path=out_path, width=_W, height=_H, fps=_FPS, duration_s=6.0,
        speed_limit_kmh=speed_limit_kmh, far_road_y_m=26.0,
        vehicles=[unbelted, phoning], scenario="occupant",
    )
    _annotate_truth(info, {
        "expected_events": ["no_seatbelt", "phone_use"],
        "vehicles_involved": ["unbelted", "phoning"],
    })
    return info


SCENARIOS = {
    "collision": collision,
    "stopped": stopped_vehicle,
    "wrong_way": wrong_way,
    "litter": littering,
    "swerve": erratic,
    "occupant": occupant,
}


def build_scenario(name: str, out_path: str | Path,
                   speed_limit_kmh: float = 60.0) -> dict:
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario '{name}'; "
                         f"choose from {sorted(SCENARIOS)}")
    return SCENARIOS[name](out_path, speed_limit_kmh)


def _annotate_truth(info: dict, extra: Dict) -> None:
    """Merge scenario expectations into the ground-truth file."""
    import json

    path = Path(info["ground_truth"])
    with open(path, "r", encoding="utf-8") as fh:
        gt = json.load(fh)
    gt["incident"] = extra
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(gt, fh, indent=2)
    info["incident"] = extra
