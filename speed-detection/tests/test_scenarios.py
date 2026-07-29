"""End-to-end incident tests: rendered footage -> full pipeline -> events.

These render video and run the whole chain, so they are slow. Marked ``slow``;
run the fast suite with ``pytest -m "not slow"``.

Each scenario's ground-truth file states which events *should* fire, and the
tests assert both directions: the expected event appears, and the scenario
does not produce unrelated alarms.
"""

import json

import pytest

from speeddet.analytics import KinematicAnalyzer, LitterAnalyzer, OccupantAnalyzer
from speeddet.analytics.occupant import CueOccupantClassifier
from speeddet.calibration import Calibrator
from speeddet.detection import ColorBlobDetector
from speeddet.events import EventBus, EventType
from speeddet.pipeline import PipelineConfig, SpeedPipeline
from speeddet.plates import QatarPlateReader
from speeddet.tools.scenarios import build_scenario

pytestmark = pytest.mark.slow


def _run(scenario: str, tmp_path):
    info = build_scenario(scenario, str(tmp_path / f"{scenario}.mp4"))
    with open(info["ground_truth"]) as fh:
        gt = json.load(fh)
    bus = EventBus()
    pipeline = SpeedPipeline(
        # small_object_area_px lets the demo detector distinguish an ejected
        # object from a vehicle; a real detector supplies true class names.
        detector=ColorBlobDetector(small_object_area_px=800),
        calibrator=Calibrator.load(info["calibration"]),
        config=PipelineConfig(output_dir=str(tmp_path / f"out_{scenario}"),
                              write_annotated_video=False, save_clips=False),
        plate_reader=QatarPlateReader(),
        analyzers=[KinematicAnalyzer(), LitterAnalyzer(),
                   OccupantAnalyzer(CueOccupantClassifier())],
        bus=bus,
    )
    pipeline.run_video(info["video"])
    fired = {e.type.value for e in bus.published}
    return bus, gt, fired


def test_collision_scenario(tmp_path):
    bus, gt, fired = _run("collision", tmp_path)
    assert "collision" in fired
    collisions = bus.events_of(EventType.COLLISION)
    assert len(collisions) == 1, "one crash must produce one event"
    c = collisions[0]
    impact = gt["incident"]["impact_time_s"]
    assert abs(c.timestamp - impact) <= gt["incident"]["impact_tolerance_s"]
    assert c.confidence >= 0.6
    assert c.severity >= 40  # CRITICAL


def test_stopped_vehicle_scenario(tmp_path):
    bus, gt, fired = _run("stopped", tmp_path)
    assert "stopped_vehicle" in fired
    assert len(bus.events_of(EventType.STOPPED_VEHICLE)) == 1
    # A vehicle braking normally to a halt is a breakdown, not a crash.
    assert "collision" not in fired


def test_wrong_way_scenario(tmp_path):
    bus, gt, fired = _run("wrong_way", tmp_path)
    assert "wrong_way" in fired
    ww = bus.events_of(EventType.WRONG_WAY)
    assert len(ww) == 1
    assert ww[0].severity >= 40


def test_littering_scenario(tmp_path):
    bus, gt, fired = _run("litter", tmp_path)
    assert "littering" in fired
    events = bus.events_of(EventType.LITTERING)
    assert len(events) == 1
    ev = events[0]
    # The whole point is attribution: the event must name the source vehicle.
    assert ev.plate_text == "TX 6642"
    assert ev.requires_review, "littering is a proposal, never an auto-citation"
    # The object rolling to a halt must not be mistaken for a wrong-way driver.
    assert "wrong_way" not in fired


def test_erratic_driving_scenario(tmp_path):
    bus, gt, fired = _run("swerve", tmp_path)
    assert "erratic_driving" in fired
    assert len(bus.events_of(EventType.ERRATIC_DRIVING)) == 1


def test_occupant_scenario(tmp_path):
    bus, gt, fired = _run("occupant", tmp_path)
    assert "no_seatbelt" in fired
    assert "phone_use" in fired
    for ev in (bus.events_of(EventType.NO_SEATBELT)
               + bus.events_of(EventType.PHONE_USE)):
        assert ev.requires_review, "classifier output must be review-gated"
        assert "operator confirmation" in ev.message


def test_plain_traffic_raises_no_false_incidents(tmp_path):
    """The baseline that matters: normal traffic must stay quiet."""
    from speeddet.tools.generate_synthetic_video import generate

    info = generate(out_path=str(tmp_path / "traffic.mp4"), width=1920,
                    height=1080, far_road_y_m=30.0, speed_limit_kmh=60.0)
    bus = EventBus()
    pipeline = SpeedPipeline(
        detector=ColorBlobDetector(small_object_area_px=800),
        calibrator=Calibrator.load(info["calibration"]),
        config=PipelineConfig(output_dir=str(tmp_path / "out_traffic"),
                              write_annotated_video=False, save_clips=False),
        analyzers=[KinematicAnalyzer(), LitterAnalyzer()],
        bus=bus,
    )
    pipeline.run_video(info["video"])
    fired = {e.type.value for e in bus.published}
    for noise in ("collision", "wrong_way", "stopped_vehicle", "littering",
                  "pedestrian_on_roadway"):
        assert noise not in fired, f"false {noise} on clean traffic"
