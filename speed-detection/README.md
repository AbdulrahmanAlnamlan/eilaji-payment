# speeddet — Sentinel tower software stack

> **Full system design: [`docs/sentinel-tower.md`](docs/sentinel-tower.md).**
> Roadside station design incl. drone nest: [`docs/radar-drone-station.md`](docs/radar-drone-station.md).

Beyond the speed core documented below, this package now implements the
analytics, event and tower layers of the Sentinel unit:

| Layer | Module | What it does |
| --- | --- | --- |
| Anomaly AI | `analytics/kinematics.py` | collision, near-miss, stopped vehicle, wrong-way, erratic driving, congestion, pedestrian-on-roadway — all from world-space physics, no model weights |
| Occupant AI | `analytics/occupant.py` | seatbelt / phone from the windshield ROI, temporal voting, pluggable classifier |
| Littering | `analytics/litter.py` | object ejected from a window, attributed to the source vehicle |
| Events | `events.py` | one bus, per-incident dedupe, JSONL / webhook / console dispatch |
| Privacy | `privacy.py` | face-blur redaction, hash-chained audit log, retention sweep, identity boundary |
| Tower | `tower/` | subsystem health, time-boxed audited CCTV sessions, drone nest state machine + interlocks, mission planning |

Try the incident scenarios — each renders scripted footage with known ground
truth and runs the whole stack over it:

```bash
python -m speeddet.cli scenario --scenario collision
python -m speeddet.cli scenario --scenario wrong_way
python -m speeddet.cli scenario --scenario litter
python -m speeddet.cli scenario --scenario occupant
```

### The three classes of detection — and why it matters

| Class | Examples | Status |
| --- | --- | --- |
| **A — instrument** | speed, wrong-way, stopped vehicle, collision | reproducible physics; verified against ground truth |
| **B — proposal** | seatbelt, phone, littering | flagged `requires_review`; a human confirms before any enforcement. Needs a model trained on *your* footage |
| **C — attention** | fights, crowd anomaly | routes an operator's attention; never asserts what happened |

The code enforces this: Class B events carry `requires_review=True` and there
is no path from one to an automatic citation.

---

# Speed-detection core

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
| التعرف الآلي (ALPR)                | `plates.py` Qatar plate OCR (demo) + `alpr.py` hooks        |
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

## Qatar plates (ALPR)

Current Qatari metal plates carry a **category letter code** (1–2 Latin
letters, top-right) plus **1–6 digits**, with the maroon "QATAR / قطر" legend:
`Q` private/rental/electric, `PR` private transport, `TK` truck, `BS` bus,
`LI` limousine, `MO` motorcycle, `TR` trailer, `TX` taxi, temporary codes
(`TE`/`EN`/`EX`/`UE`/`EV`), and official plates (`GV` government, `CD`
diplomatic, `UN`, `AP`, `DP`, `CV`, `NV`, `AQ`, `BN`, `PT`, `MH`, `FD`).
Police / Lekhwiya / QAF / Amiri Guard plates use non-standard Arabic layouts
and are out of the demo reader's scope. `plates.py` provides:

- **Format rules** — `parse_qatar_plate()` / `validate_qatar_plate()` (known
  category code + 1–6 digits, else reject) and `normalize_digits()`
  (Arabic-Indic ٠-٩ → Western). Run these on the output of *any* OCR backend
  to cheaply kill misreads.
- **`QatarPlateReader`** — a dependency-free OCR (plate localisation → per-band
  glyph segmentation → template correlation) reading both the digit row and
  the category letters off the demo footage. Measured across all 25 category
  codes at 4 scales: 92% full reads, 8% degrade to correct-digits-only at tiny
  sizes, **0 wrong reads** — the enforcement-critical property: a read is
  exactly right, gracefully partial, or `None` (retry on a closer frame).
- **Backfill & upgrade** — a violation usually fires while the car is far
  away; the pipeline keeps retrying on closer frames, records the digits as
  soon as they resolve, and upgrades to the full "CODE digits" form when the
  (smaller) letter row becomes readable — only if the digits agree.

```
=== plate (ALPR) check ===
    OK  read  plate LI 674
    OK  read  plate PR 9021
    OK  read  plate TX 42781
```

For **real Qatari plates** swap in `--alpr fast-alpr` (`pip install
fast-alpr`) — same callable interface — and expect to fine-tune the OCR model
on local plate fonts/layouts for production accuracy. Note the camera
geometry: plates need roughly ≥20 px of height to read, so real deployments
pair the wide speed-camera view with a tighter/zoomed ALPR view per lane (the
demo mimics this with a 1080p, 35 m-span camera).

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
