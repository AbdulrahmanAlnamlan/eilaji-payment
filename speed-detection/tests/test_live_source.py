"""Live-source handling: source normalisation and bounded runs."""

import pytest

from speeddet.calibration import build_ground_plane_calibration
from speeddet.detection import ColorBlobDetector
from speeddet.pipeline import PipelineConfig, SpeedPipeline, _normalise_source
from speeddet.tools.generate_synthetic_video import generate


@pytest.mark.parametrize(
    "source,live_arg,expected_src,expected_live",
    [
        (0, None, 0, True),                       # camera index
        ("0", None, 0, True),                     # camera index as string
        ("rtsp://cam.local/stream1", None, "rtsp://cam.local/stream1", True),
        ("http://cam.local/mjpeg", None, "http://cam.local/mjpeg", True),
        ("footage.mp4", None, "footage.mp4", False),
        ("footage.mp4", True, "footage.mp4", True),   # forced live
        ("rtsp://cam.local/s", False, "rtsp://cam.local/s", False),  # forced file-style
    ],
)
def test_normalise_source(source, live_arg, expected_src, expected_live):
    assert _normalise_source(source, live_arg) == (expected_src, expected_live)


def test_max_frames_bounds_run(tmp_path):
    video = tmp_path / "clip.mp4"
    info = generate(out_path=video, fps=25.0, duration_s=2.0)
    calib = build_ground_plane_calibration((1280, 720))
    pipeline = SpeedPipeline(
        detector=ColorBlobDetector(),
        calibrator=calib,
        config=PipelineConfig(output_dir=str(tmp_path / "out"),
                              write_annotated_video=False, save_clips=False),
    )
    result = pipeline.run_video(str(video), max_frames=10)
    assert result.frames_processed == 10
