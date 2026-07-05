"""End-to-end: synthetic footage -> pipeline -> speeds match ground truth.

This is the proof-of-concept test. It exercises detection -> tracking ->
homography -> speed -> violation triggering as one chain and checks the numbers
against the constant speeds the footage was generated with.
"""

import json

import pytest

from speeddet.calibration import Calibrator
from speeddet.detection import ColorBlobDetector
from speeddet.pipeline import PipelineConfig, SpeedPipeline
from speeddet.tools.generate_synthetic_video import Vehicle, generate


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    video = out / "highway.mp4"
    info = generate(out_path=video, speed_limit_kmh=60.0, fps=25.0, duration_s=5.0)
    with open(info["ground_truth"]) as fh:
        gt = json.load(fh)
    return out, info, gt


def _run(out, info):
    calib = Calibrator.load(info["calibration"])
    pipeline = SpeedPipeline(
        detector=ColorBlobDetector(),
        calibrator=calib,
        config=PipelineConfig(output_dir=str(out), save_clips=True),
    )
    return pipeline.run_video(info["video"])


def test_speeds_match_ground_truth(demo):
    out, info, gt = demo
    result = _run(out, info)

    truth = sorted(v["speed_kmh"] for v in gt["vehicles"])
    measured = sorted(sorted(result.max_speed_by_track.values(), reverse=True)[: len(truth)])

    assert len(measured) == len(truth), "did not recover one track per vehicle"
    for g, m in zip(truth, measured):
        rel_err = abs(g - m) / g
        assert rel_err < 0.12, f"speed off: truth={g:.1f} measured={m:.1f} ({rel_err:.1%})"


def test_violations_detected(demo):
    out, info, gt = demo
    result = _run(out, info)
    expected_violations = sum(1 for v in gt["vehicles"] if v["is_violation"])
    fired_tracks = {v.track_id for v in result.violations}
    # Every speeder should trigger at least one violation; no under-limit car should.
    assert len(fired_tracks) == expected_violations


def test_evidence_clip_written(demo):
    out, info, gt = demo
    result = _run(out, info)
    clips = [v.clip_path for v in result.violations if v.clip_path]
    assert clips, "expected at least one evidence clip"
    from pathlib import Path
    assert all(Path(c).exists() for c in clips)
