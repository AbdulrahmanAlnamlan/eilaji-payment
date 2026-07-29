"""Command-line entry point for the speed-detection prototype.

Examples
--------
Generate synthetic footage and run the pipeline on it (no YOLO needed)::

    python -m speeddet.cli demo

Run on your own footage with real YOLO::

    python -m speeddet.cli run \\
        --video highway.mp4 \\
        --calibration calib.json \\
        --detector yolo --model yolov8n.pt

Run on the synthetic footage with the colour detector::

    python -m speeddet.cli run \\
        --video demo/highway.mp4 \\
        --calibration demo/highway.calibration.json \\
        --detector color
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .calibration import Calibrator
from .detection import ColorBlobDetector, YoloDetector
from .pipeline import PipelineConfig, SpeedPipeline
from .plates import QatarPlateReader


def _build_plate_reader(name: str):
    if name == "none":
        return None
    if name == "qatar-demo":
        return QatarPlateReader()
    if name == "fast-alpr":
        from .alpr import FastAlprReader
        return FastAlprReader()
    raise ValueError(f"unknown --alpr '{name}'")


def _build_detector(name: str, args) -> object:
    if name == "yolo":
        return YoloDetector(
            model_path=args.model,
            conf=args.conf,
            device=args.device,
            vehicle_only=not args.all_classes,
        )
    if name == "color":
        return ColorBlobDetector()
    raise ValueError(f"unknown detector '{name}' (use 'yolo' or 'color')")


def _print_result(result) -> None:
    print("\n=== speed-detection summary ===")
    print(f"frames processed : {result.frames_processed}")
    print(f"fps              : {result.fps:.2f}")
    print(f"tracks seen      : {len(result.max_speed_by_track)}")
    if result.max_speed_by_track:
        print("peak speed / track (km/h):")
        for tid, spd in sorted(result.max_speed_by_track.items()):
            print(f"    track #{tid:<3d}: {spd:6.1f}")
    print(f"violations       : {len(result.violations)}")
    for v in result.violations:
        plate = f" plate={v.plate_text}" if v.plate_text else ""
        clip = f" clip={v.clip_path}" if v.clip_path else ""
        print(f"    track #{v.track_id}: {v.speed_kmh:.1f} km/h "
              f"(limit {v.speed_limit_kmh:.0f}, +{v.over_by_kmh:.1f}) "
              f"@ t={v.timestamp:.2f}s{plate}{clip}")
    if result.annotated_video:
        print(f"annotated video  : {result.annotated_video}")
    if result.violations_log:
        print(f"violations log   : {result.violations_log}")


def cmd_run(args) -> None:
    calib = Calibrator.load(args.calibration)
    print(f"calibration reprojection error: {calib.reprojection_error():.3f} px "
          f"(speed limit {calib.speed_limit_kmh:.0f} km/h)")
    detector = _build_detector(args.detector, args)
    cfg = PipelineConfig(
        output_dir=args.output,
        write_annotated_video=not args.no_video,
        save_clips=not args.no_clips,
        clip_seconds=args.clip_seconds,
    )
    pipeline = SpeedPipeline(detector=detector, calibrator=calib, config=cfg,
                             plate_reader=_build_plate_reader(args.alpr))
    result = pipeline.run_video(
        args.video,
        live=True if args.live else None,
        max_frames=args.max_frames,
        max_seconds=args.max_seconds,
    )
    _print_result(result)


def cmd_demo(args) -> None:
    """End-to-end demo: generate footage, then run the pipeline on it."""
    from .tools.generate_synthetic_video import generate

    out_dir = Path(args.output)
    video = out_dir / "highway.mp4"
    print("generating synthetic footage with known ground-truth speeds ...")
    # 1080p with a ~30 m road span mimics the tighter ALPR camera view real
    # deployments use, so plates (incl. the category letter row) are large
    # enough to read near the camera.
    info = generate(out_path=video, speed_limit_kmh=args.speed_limit,
                    width=1920, height=1080, far_road_y_m=30.0)
    print(json.dumps(info, indent=2))

    calib = Calibrator.load(info["calibration"])
    detector = ColorBlobDetector()
    cfg = PipelineConfig(output_dir=str(out_dir), save_clips=not args.no_clips)
    pipeline = SpeedPipeline(detector=detector, calibrator=calib, config=cfg,
                             plate_reader=QatarPlateReader())
    result = pipeline.run_video(str(video))
    _print_result(result)

    # Compare recovered peak speeds against ground truth.
    with open(info["ground_truth"], "r", encoding="utf-8") as fh:
        gt = json.load(fh)
    print("\n=== ground-truth check ===")
    gt_speeds = sorted(v["speed_kmh"] for v in gt["vehicles"])
    got_speeds = sorted(result.max_speed_by_track.values(), reverse=True)[: len(gt_speeds)]
    got_speeds = sorted(got_speeds)
    for g, r in zip(gt_speeds, got_speeds):
        err = abs(g - r) / g * 100.0
        flag = "OK " if err < 12 else "!! "
        print(f"    {flag} truth {g:6.1f} km/h  ~  measured {r:6.1f} km/h  ({err:4.1f}% err)")

    # Plate check: every ground-truth speeder should appear in the violation
    # log with its (correct) Qatar plate number.
    print("\n=== plate (ALPR) check ===")
    speeder_plates = {v["plate_number"] for v in gt["vehicles"] if v["is_violation"]}
    read_plates = {v.plate_text for v in result.violations if v.plate_text}
    for plate in sorted(speeder_plates):
        status = "OK  read" if plate in read_plates else "!!  MISSED"
        print(f"    {status}  plate {plate}")
    bogus = read_plates - speeder_plates
    if bogus:
        print(f"    !!  WRONG reads (not in ground truth): {sorted(bogus)}")


def cmd_scenario(args) -> None:
    """Render a scripted incident and run the full analytics stack on it."""
    from .analytics import KinematicAnalyzer, LitterAnalyzer, OccupantAnalyzer
    from .analytics.occupant import CueOccupantClassifier
    from .events import ConsoleDispatcher, EventBus, JsonlDispatcher
    from .tools.scenarios import SCENARIOS, build_scenario

    out_dir = Path(args.output)
    print(f"rendering '{args.scenario}' scenario ...")
    info = build_scenario(args.scenario, str(out_dir / f"{args.scenario}.mp4"))
    print(f"  video       : {info['video']}")
    print(f"  ground truth: {info['incident']}")

    bus = EventBus()
    bus.subscribe(ConsoleDispatcher())
    bus.subscribe(JsonlDispatcher(out_dir / "events.jsonl"))
    pipeline = SpeedPipeline(
        detector=ColorBlobDetector(small_object_area_px=800),
        calibrator=Calibrator.load(info["calibration"]),
        config=PipelineConfig(output_dir=str(out_dir),
                              annotated_video_name=f"{args.scenario}_annotated.mp4",
                              save_clips=not args.no_clips),
        plate_reader=QatarPlateReader(),
        analyzers=[KinematicAnalyzer(), LitterAnalyzer(),
                   OccupantAnalyzer(CueOccupantClassifier())],
        bus=bus,
    )
    print("\n--- live event stream ---")
    result = pipeline.run_video(info["video"])

    expected = set(info["incident"]["expected_events"])
    fired = {e.type.value for e in bus.published}
    print("\n=== incident check ===")
    for want in sorted(expected):
        print(f"    {'OK  detected' if want in fired else '!!  MISSED  '}  {want}")
    unexpected = fired - expected - {"speeding", "operator_access",
                                     "system_health", "drone_status"}
    if unexpected:
        print(f"    ..  also fired: {sorted(unexpected)}")
    print(f"\nannotated video : {result.annotated_video}")
    print(f"event log       : {out_dir / 'events.jsonl'}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="speeddet", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run the pipeline on a video file, RTSP stream, or camera")
    r.add_argument("--video", required=True,
                   help="video file, RTSP/HTTP URL, or camera index (e.g. 0)")
    r.add_argument("--calibration", required=True)
    r.add_argument("--live", action="store_true",
                   help="force live mode (wall-clock timestamps, reconnect); "
                        "auto-enabled for RTSP URLs and camera indices")
    r.add_argument("--max-seconds", type=float, default=None,
                   help="stop after this many seconds (useful for live tests)")
    r.add_argument("--max-frames", type=int, default=None)
    r.add_argument("--detector", default="yolo", choices=["yolo", "color"])
    r.add_argument("--model", default="yolov8n.pt", help="YOLO weights (yolo detector)")
    r.add_argument("--conf", type=float, default=0.35)
    r.add_argument("--device", default=None, help="cpu / cuda:0 / None(auto)")
    r.add_argument("--all-classes", action="store_true", help="don't filter to vehicles")
    r.add_argument("--output", default="output")
    r.add_argument("--clip-seconds", type=float, default=8.0)
    r.add_argument("--no-video", action="store_true", help="skip annotated video output")
    r.add_argument("--no-clips", action="store_true", help="skip evidence clip extraction")
    r.add_argument("--alpr", default="none", choices=["none", "qatar-demo", "fast-alpr"],
                   help="plate reader: qatar-demo (built-in, synthetic plates) or "
                        "fast-alpr (pip install fast-alpr; real footage)")
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("demo", help="generate synthetic footage and run end-to-end")
    d.add_argument("--output", default="demo")
    d.add_argument("--speed-limit", type=float, default=60.0)
    d.add_argument("--no-clips", action="store_true")
    d.set_defaults(func=cmd_demo)

    s = sub.add_parser("scenario",
                       help="render a scripted incident and run the full "
                            "analytics stack (collision, stopped vehicle, "
                            "wrong-way, littering, swerve, occupant)")
    s.add_argument("--scenario", default="collision",
                   choices=["collision", "stopped", "wrong_way", "litter",
                            "swerve", "occupant"])
    s.add_argument("--output", default="demo/incidents")
    s.add_argument("--no-clips", action="store_true")
    s.set_defaults(func=cmd_scenario)

    return ap


def main(argv=None) -> None:
    ap = build_parser()
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
