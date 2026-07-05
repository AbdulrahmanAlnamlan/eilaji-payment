"""Qatar plate format rules, render->read roundtrip, and end-to-end ALPR."""

import json

import numpy as np
import pytest

from speeddet.plates import (
    QatarPlateReader,
    normalize_digits,
    render_qatar_plate,
    to_eastern,
    validate_qatar_plate,
)


# ------------------------- format rules ------------------------------- #
def test_normalize_eastern_arabic_digits():
    assert normalize_digits("٩٠٢١") == "9021"
    assert normalize_digits("٣٥٨") == "358"
    assert normalize_digits(" 42-781 QATAR ") == "42781"


def test_validate_qatar_plate():
    assert validate_qatar_plate("9021") == "9021"
    assert validate_qatar_plate("٩٠٢١") == "9021"      # Eastern Arabic form
    assert validate_qatar_plate("123456") == "123456"  # 6 digits max
    assert validate_qatar_plate("1234567") is None     # too long
    assert validate_qatar_plate("") is None
    assert validate_qatar_plate(None) is None
    assert validate_qatar_plate("ABC") is None         # Qatar plates are digit-only


def test_to_eastern_roundtrip():
    assert normalize_digits(to_eastern("2043")) == "2043"


# --------------------- render -> read roundtrip ----------------------- #
@pytest.fixture(scope="module")
def reader():
    return QatarPlateReader()


def _on_car(plate: np.ndarray) -> np.ndarray:
    h, w = plate.shape[:2]
    car = np.full((h * 3, w * 2, 3), (50, 45, 160), dtype=np.uint8)
    car[h : h * 2, w // 2 : w // 2 + w] = plate
    return car


@pytest.mark.parametrize("num", ["7", "42", "358", "9021", "54871", "123456"])
def test_roundtrip_readable_sizes(reader, num):
    for width in (240, 120, 80):
        got = reader.read_crop(_on_car(render_qatar_plate(num, width)))
        assert got == num, f"{num} @ {width}px read as {got}"


def test_never_returns_wrong_plate(reader):
    """The enforcement-critical property: unreadable -> None, never a wrong
    but plausible number."""
    for num in ("42", "9021", "54871", "123456"):
        for width in (56, 40, 32):
            got = reader.read_crop(_on_car(render_qatar_plate(num, width)))
            assert got in (num, None), f"WRONG read: {num} @ {width}px -> {got}"


def test_unreadable_far_plate_returns_none(reader):
    tiny = render_qatar_plate("9021", 26)  # below the min-height gate
    assert reader.read_crop(_on_car(tiny)) is None


# --------------------------- end-to-end -------------------------------- #
def test_pipeline_reads_speeder_plates(tmp_path):
    from speeddet.calibration import Calibrator
    from speeddet.detection import ColorBlobDetector
    from speeddet.pipeline import PipelineConfig, SpeedPipeline
    from speeddet.tools.generate_synthetic_video import generate

    video = tmp_path / "alpr.mp4"
    info = generate(out_path=video, width=1920, height=1080,
                    far_road_y_m=35.0, speed_limit_kmh=60.0)
    with open(info["ground_truth"]) as fh:
        gt = json.load(fh)

    pipeline = SpeedPipeline(
        detector=ColorBlobDetector(),
        calibrator=Calibrator.load(info["calibration"]),
        config=PipelineConfig(output_dir=str(tmp_path / "out"),
                              write_annotated_video=False, save_clips=False),
        plate_reader=QatarPlateReader(),
    )
    result = pipeline.run_video(str(video))

    speeder_plates = {v["plate_number"] for v in gt["vehicles"] if v["is_violation"]}
    read_plates = {v.plate_text for v in result.violations if v.plate_text}
    assert read_plates == speeder_plates
