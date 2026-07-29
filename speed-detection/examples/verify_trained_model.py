"""Verify a trained occupant model end to end inside the tower pipeline.

Three checks, in increasing scope:

1. **The ONNX loads and runs** — shapes and output names are what the runtime
   expects.
2. **It agrees with the PyTorch model it was exported from** — catching the
   classic export bug where the graph is subtly wrong and nobody notices until
   field accuracy is mysteriously poor.
3. **It works as a drop-in inside `SpeedPipeline`** — the trained classifier
   replaces the demo cue-reader and the whole detect → track → ROI → classify →
   vote → review-gated event chain still runs.

Run after training:
    python examples/verify_trained_model.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MODEL_DIR = Path("models")


def rule(title: str) -> None:
    print(f"\n{'=' * 66}\n{title}\n{'=' * 66}")


def main() -> int:
    onnx_path = MODEL_DIR / "occupant.onnx"
    if not onnx_path.exists():
        print(f"No model at {onnx_path}. Train one first:\n"
              f"    python -m speeddet.training.train_occupant")
        return 1

    report_path = MODEL_DIR / "occupant_report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    image_size = report.get("config", {}).get("image_size", 96)

    # ---------------------------------------------------------------- #
    rule("1. ONNX LOADS AND RUNS")
    import onnxruntime as ort

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    outs = [o.name for o in sess.get_outputs()]
    print(f"input : {inp.name} {inp.shape}")
    print(f"outputs: {outs}")
    assert outs == ["belt_logits", "phone_logits"], f"unexpected outputs {outs}"

    rng = np.random.default_rng(0)
    x = rng.random((4, 3, image_size, image_size)).astype(np.float32)
    belt, phone = sess.run(None, {inp.name: x})
    print(f"batch of 4 -> belt {np.asarray(belt).shape}, "
          f"phone {np.asarray(phone).shape}")
    assert np.asarray(belt).shape == (4, 2)

    # ---------------------------------------------------------------- #
    rule("2. ONNX MATCHES THE PYTORCH MODEL IT CAME FROM")
    weights = MODEL_DIR / "occupant.pt"
    if not weights.exists():
        print("no .pt weights alongside; skipping parity check")
    else:
        import torch

        from speeddet.training.train_occupant import build_model

        width = report.get("config", {}).get("width", 32)
        model = build_model(width)
        model.load_state_dict(torch.load(weights, map_location="cpu"))
        model.eval()
        with torch.no_grad():
            tb, tp = model(torch.from_numpy(x))
        db = float(np.abs(tb.numpy() - np.asarray(belt)).max())
        dp = float(np.abs(tp.numpy() - np.asarray(phone)).max())
        print(f"max |torch - onnx| : belt {db:.3e}   phone {dp:.3e}")
        if max(db, dp) < 1e-3:
            print("OK  export is faithful")
        else:
            print("!!  EXPORT MISMATCH — the ONNX graph does not match the model")
            return 2

    # ---------------------------------------------------------------- #
    rule("3. RUNS INSIDE THE TOWER PIPELINE")
    from speeddet.analytics import KinematicAnalyzer, OccupantAnalyzer
    from speeddet.analytics.occupant import OccupantConfig, OnnxOccupantClassifier
    from speeddet.calibration import Calibrator
    from speeddet.detection import ColorBlobDetector
    from speeddet.events import EventBus, EventType
    from speeddet.pipeline import PipelineConfig, SpeedPipeline
    from speeddet.tools.scenarios import build_scenario

    out = Path("demo/verify")
    out.mkdir(parents=True, exist_ok=True)
    info = build_scenario("occupant", str(out / "occupant.mp4"))

    classifier = OnnxOccupantClassifier(str(onnx_path),
                                        input_size=(image_size, image_size))
    bus = EventBus()
    pipeline = SpeedPipeline(
        detector=ColorBlobDetector(small_object_area_px=800),
        calibrator=Calibrator.load(info["calibration"]),
        config=PipelineConfig(output_dir=str(out), write_annotated_video=False,
                              save_clips=False),
        analyzers=[KinematicAnalyzer(),
                   OccupantAnalyzer(classifier, OccupantConfig())],
        bus=bus,
    )
    result = pipeline.run_video(info["video"])
    print(f"frames processed : {result.frames_processed}")
    print(f"tracks           : {len(result.max_speed_by_track)}")

    occupant_events = (bus.events_of(EventType.NO_SEATBELT)
                       + bus.events_of(EventType.PHONE_USE))
    print(f"occupant events  : {len(occupant_events)}")
    for e in occupant_events:
        print(f"  {e.type.value:<12} conf {e.confidence:.2f}  "
              f"review={e.requires_review}  {e.message}")

    print("\nThe pipeline ran with the trained model in place of the demo "
          "classifier.\nNote: this model is trained on SYNTHETIC crops and the "
          "demo footage is a\ndifferent synthetic domain, so whether it fires "
          "here is a statement about\ndomain transfer, not about field "
          "accuracy. What is verified is that the\nartifact loads, matches its "
          "source model, and is consumed correctly by the\ntower.")

    if report.get("test"):
        rule("HELD-OUT METRICS FROM TRAINING")
        for head in ("belt", "phone"):
            m = report["test"].get(head, {})
            if m:
                print(f"{head:6} acc {m['accuracy']:.4f}  f1 {m['f1']:.4f}  "
                      f"prec {m['precision']:.4f}  rec {m['recall']:.4f}  "
                      f"ECE {m['ece']:.4f}")
        if report.get("note"):
            print(f"\nnote: {report['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
