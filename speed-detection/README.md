# speeddet — camera-based vehicle speed-detection core

A runnable prototype of the **speed-detection core** from the "smart traffic
radar" system in the post: detect vehicles, track them across frames, map pixels
to real-world metres via camera calibration, and compute speed. It flags
speeding vehicles, saves a short **video evidence clip** per violation, and
exposes hooks for the later phases (ALPR, backend/notification dispatch).

This is phase 1 — the piece that proves the concept. It is deliberately
dependency-light and **fully runnable without a GPU or downloaded model
weights**, because it ships with a synthetic-footage generator whose vehicles
move at *known* speeds, so the speed math can be checked against ground truth.

```
video frames ─► detect ─► track (assign IDs) ─► project ground point to world
             ─► estimate speed ─► violation trigger ─► evidence clip + log ─► annotate
```

## Why this maps to the post

| Post component (Arabic)            | Here                                                        |
| ---------------------------------- | ----------------------------------------------------------- |
| التتبع اللحظي — real-time tracking | `detection.py` (YOLO) + `tracking.py` (IoU tracker)         |
| Speed monitoring via cameras       | `calibration.py` (homography) + `speed.py` (least-squares)  |
| التوثيق بالفيديو — video evidence  | `violations.py` ring buffer → per-violation `.mp4` clip     |
| التعرف الآلي (ALPR)                | `alpr.py` hook (Fast-ALPR / PaddleOCR wrappers, phase 2)    |
| الأتمتة — automated dispatch       | `violations.json` log + hooks for a FastAPI/DB backend      |

## Quick start

```bash
cd speed-detection
pip install -r requirements.txt          # numpy + opencv

# End-to-end demo: generates synthetic footage with known speeds,
# runs the full pipeline, and checks recovered speeds vs ground truth.
python -m speeddet.cli demo --output demo
```

Sample output (measured speeds vs the speeds the footage was generated with):

```
=== ground-truth check ===
    OK  truth   52.0 km/h  ~  measured   53.2 km/h  ( 2.4% err)
    OK  truth   78.0 km/h  ~  measured   79.8 km/h  ( 2.4% err)
    OK  truth   96.0 km/h  ~  measured   96.9 km/h  ( 1.0% err)
    OK  truth  124.0 km/h  ~  measured  128.3 km/h  ( 3.4% err)
```

Outputs land in `demo/`: `annotated.mp4` (boxes + IDs + km/h + HUD),
`clips/` (one evidence clip per violation), and `violations.json`.

![annotated frame](docs/annotated_frame.png)

## Running on real footage (YOLO)

```bash
pip install ultralytics                   # adds the production detector

python -m speeddet.cli run \
    --video highway.mp4 \
    --calibration my_calib.json \
    --detector yolo --model yolov8n.pt --device cpu
```

The same pipeline runs; only the detector changes. Swap `yolov8n.pt` for a
model fine-tuned on local vehicles/plates for best results.

## Running on a live camera (RTSP / USB)

`--video` also accepts an RTSP/HTTP URL or a camera index. Live mode is
auto-detected: timestamps switch to the wall clock (IP cameras routinely report
a bogus FPS — 0, 90000, … — and trusting it would silently corrupt every speed
reading), and dropped frames trigger reconnect attempts instead of ending the
run.

```bash
# IP camera (any ONVIF/RTSP cam — check the camera manual for the stream URL)
python -m speeddet.cli run \
    --video "rtsp://user:pass@192.168.1.50:554/stream1" \
    --calibration my_calib.json \
    --detector yolo --max-seconds 120

# USB webcam for a desk test
python -m speeddet.cli run --video 0 --calibration my_calib.json --detector yolo
```

Field-test checklist:
1. **Mount the camera rigidly** (pole/overpass/tripod) with a clear view of
   ≥30–60 m of road. Any camera movement invalidates the calibration.
2. **Calibrate that exact view**: grab one frame, pick 4+ pixel points whose
   ground positions you can measure (lane-line dashes have standardised
   length/gap; or tape-measure a rectangle on the tarmac), and put them in the
   calibration JSON. Check `reprojection_error()` is a few pixels at most.
3. **Validate before trusting it**: drive a car through the view at a known
   GPS/cruise-control speed and compare. Do this at 2–3 different speeds.
4. Start with `--max-seconds 60 --no-clips` to confirm detection/tracking look
   right in `annotated.mp4`, then enable clips.

## Calibration — the accuracy-critical part

Speed is only as good as the pixel→metre mapping. `calibration.py` uses a planar
homography: you supply ≥4 image points whose real-world ground positions (in
metres) you know — lane markings at standard spacing, a measured rectangle on
the tarmac, or survey points.

```json
{
  "image_points": [[420,690],[860,690],[760,300],[520,300]],
  "world_points": [[0,0],[10.95,0],[10.95,60],[0,60]],
  "speed_limit_kmh": 60,
  "notes": "3 lanes x 3.65m; 60m longitudinal span"
}
```

`Calibrator.reprojection_error()` reports the fit quality (pixels). For a real
deployment this is where legal defensibility is won or lost — the demo's
auto-generated calibration is a convenience, not a substitute for surveyed
points.

## How speed is computed

Per track we keep a short, time-stamped history of world-plane positions and fit
a velocity by **least squares** over a sliding window (default 0.6 s):

```
X(t) = ax + bx·t ,  Y(t) = ay + by·t  →  speed = √(bx² + by²) · 3.6  [km/h]
```

A windowed fit is far more robust to per-frame detection jitter than
`Δposition / Δt` between two frames, which amplifies pixel noise. Readings are
withheld until enough time span/samples exist, and physically impossible jumps
(from ID swaps) are rejected.

## Architecture

```
speeddet/
  types.py          Detection / TrackedObject dataclasses
  calibration.py    homography, pixel<->world, ground-plane builder
  detection.py      YoloDetector | ColorBlobDetector | GroundTruthDetector
  tracking.py       IouTracker (greedy IoU + constant-velocity coast)
  speed.py          SpeedEstimator (windowed least-squares velocity)
  violations.py     RingBuffer + ViolationLogger (clips + JSON, per-track cooldown)
  alpr.py           plate-reader hook (Fast-ALPR / PaddleOCR wrappers)
  annotate.py       overlays (boxes, speeds, HUD, calibration region)
  pipeline.py       SpeedPipeline — wires it all together over a video
  cli.py            `speeddet run` / `speeddet demo`
  tools/generate_synthetic_video.py   ground-truth footage generator
tests/              calibration, tracking, speed, and end-to-end checks
```

The detector is injected, so `ColorBlobDetector` (demo) and `YoloDetector`
(production) are fully interchangeable. Likewise the tracker can be swapped for
ByteTrack/DeepSORT, and `plate_reader`/`ViolationLogger` are the seams for the
ALPR and backend/notification phases.

## Tests

```bash
pip install pytest
python -m pytest -q            # 17 tests: homography, tracking, speed, end-to-end
```

`tests/test_pipeline_synthetic.py` runs the whole chain on generated footage and
asserts recovered speeds are within 12% of ground truth and that exactly the
speeders (and no under-limit car) trigger violations.

## Roadmap (from the post's 4-week plan)

- **Done (this repo):** YOLO-ready detection + tracking + calibrated speed + violation clips.
- **Phase 2:** wire `alpr.py` to a plate model fine-tuned on local plates.
- **Phase 3:** FastAPI + PostgreSQL backend, plate→owner lookup, email/SMS dispatch.
- **Phase 4:** live RTSP ingest + edge deployment (Jetson Orin / small GPU box).

## Limitations & honest caveats

- Accuracy hinges entirely on real calibration; the demo numbers reflect a
  *perfect* synthetic homography. Field accuracy depends on survey quality,
  camera stability, and lens distortion (add undistortion for wide lenses).
- The in-house IoU tracker is intentionally simple; heavy occlusion/traffic
  warrants ByteTrack/DeepSORT.
- Radar enforcement is a regulated government function — deploy only in an
  authorised pilot (e.g. MOI/Ashghal) or pivot the same stack to private-sector
  use (compound/industrial speed monitoring, gate ALPR access control, fleet).
```
