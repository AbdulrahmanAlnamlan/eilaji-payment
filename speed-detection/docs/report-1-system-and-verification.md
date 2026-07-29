# Report 1 — System and Verification

**Date:** 29 July 2026 · **Repo:** `speed-detection/` · **Tests:** 105 passing

---

## 1. What exists

A working software stack for a roadside enforcement and safety tower, built in
layers so each can be deployed, tested and sold independently.

```
   measurement ──► identification ──► analytics ──► events ──► tower
   (speed)         (Qatar plates)     (anomaly,      (bus,      (health, CCTV
                                       occupant,      dedupe,     sessions,
                                       litter)        dispatch)   drone nest)
                        └──────────── privacy ────────────┘
                     (redaction, audit, retention, identity boundary)
```

| Module | Responsibility |
| --- | --- |
| `calibration.py` | Homography, pixel ↔ metric ground plane, reprojection check |
| `detection.py` | YOLO backend (production) / colour-blob + ground-truth (test) |
| `tracking.py` | Greedy IoU tracker with constant-velocity coasting |
| `speed.py` | Windowed least-squares world velocity |
| `plates.py` | Qatar plate taxonomy (25 category codes) + OCR + validation |
| `analytics/kinematics.py` | Collision, near-miss, stopped, wrong-way, erratic, congestion, pedestrian |
| `analytics/occupant.py` | Windshield ROI → classifier → temporal voting |
| `analytics/litter.py` | Object ejection with source-vehicle attribution |
| `events.py` | Typed events, severity routing, dedupe, JSONL/webhook/console |
| `privacy.py` | Face-blur redaction, hash-chained audit, retention, identity boundary |
| `tower/` | Subsystem health, CCTV sessions, drone nest state machine, missions |
| `training/` | Synthetic data generator + real training pipeline + ONNX export |

Entry points: `python -m speeddet.cli demo | run | scenario`, and
`examples/sentinel_demo.py` which runs boot → incident → drone sortie → audit
end to end.

---

## 2. What is verified, and how

The distinction that matters throughout: **measurement is verified against
ground truth; classification is verified only as a pipeline.**

### 2.1 Speed — verified to within 0.5%

Scripted synthetic footage places vehicles at known world speeds via the
inverse of the same homography the pipeline inverts. Recovered speeds:

| Ground truth | Measured | Error |
| --- | --- | --- |
| 52.0 km/h | 52.3 | 0.5% |
| 78.0 km/h | 78.2 | 0.2% |
| 96.0 km/h | 96.0 | 0.0% |
| 124.0 km/h | 123.8 | 0.1% |

**This proves the mathematics, not the instrument.** It uses a perfect
synthetic homography. Field accuracy depends entirely on survey quality,
camera rigidity and lens distortion. The step that converts this into a
credible claim is a validation run against a GPS-instrumented vehicle at three
speeds — not yet done, and the single highest-value next task.

### 2.2 Anomaly analytics — verified against scripted incidents

Each scenario renders footage with a known incident and asserts the analyzer
fires once, at the right time, with no unrelated alarms:

| Scenario | Result |
| --- | --- |
| Rear-end collision | detected, conf 0.70, within tolerance of scripted impact |
| Stopped vehicle | detected after dwell; **not** reported as a collision |
| Wrong-way driver | detected, conf 0.95, CRITICAL |
| Erratic lane change | detected, conf 0.66 |
| Littering | detected, attributed to plate `TX 6642` |
| Seatbelt + phone | both detected, both review-gated |
| **Plain traffic** | **no false incidents** — the baseline that matters |

Plus 11 fast unit tests driving fabricated world trajectories directly, so the
physics is checked without rendering: gentle braking is *not* a crash, brief
stops are *not* hazards, correct-direction travel is *not* wrong-way, and a
stopped vehicle sitting for 40 seconds produces one event rather than sixty.

### 2.3 Qatar plates — verified across the full taxonomy

All 25 category codes at 4 scales: **92% full reads, 8% degraded to
correct-digits-only, 0 wrong reads.** The enforcement-critical property is the
last one — a read is exactly right, gracefully partial, or `None`, never
plausible-but-wrong.

### 2.4 Occupant classifier — pipeline verified, accuracy NOT transferable

See Report 2. A real CNN was trained and exported to ONNX with real held-out
metrics, an abstention curve and a calibration check. **Those numbers are on
synthetic data and do not predict field accuracy.** The pipeline is proven; the
model needs real data.

---

## 3. Bugs the tests caught — worth recording

Each was a false-positive mode a demo would have hidden. They are the best
evidence that the verification is doing real work.

1. **A thrown object decelerating at 7 m/s² and stopping is kinematically
   identical to a crash.** The litter scenario produced a false collision.
   Fixed by restricting collision logic to vehicle-class tracks — which is also
   why the detector must supply real classes, not just blobs.
2. **The occupant classifier reported "no seatbelt" on a car whose cabin was
   not visible at all.** An absent belt and an absent *view* of a belt are
   different observations. It now requires positive evidence of a cabin and
   returns "unclear" otherwise. This is the single most important correctness
   fix in the system: it is exactly the failure mode that generates wrongful
   citations at scale.
3. **Litter events fired before the plate was readable**, losing the
   attribution that is the whole point. Fixed with an attribution grace period
   — and by reading plates for *every* vehicle rather than only speeders, since
   a litterer is usually not speeding.
4. **A physics error in the generator** made ejected objects roll backwards up
   the road (clamping distance instead of time), which the wrong-way detector
   correctly flagged. The detector was right; the simulation was wrong.
5. **`CctvSession.active` read the wall clock** instead of the injected clock,
   so sessions appeared expired under test.

---

## 4. Known limitations — state these before a customer finds them

- **Speed is verified in simulation only.** No field validation yet.
- **The occupant classifier has no in-domain training data.** See Report 2; this
  is a data problem, not a code problem, and it is not solvable by more
  engineering.
- **The IoU tracker swaps identities when two vehicles merge visually** — which
  is exactly what a rear-end collision looks like. Production needs appearance
  features (ByteTrack/DeepSORT). The collision detector survives this because it
  fires on deceleration plus immobility, but attribution to *both* vehicles can
  be lost.
- **The demo detector is a colour-blob detector.** Real deployment requires YOLO
  with weights fine-tuned on local vehicles. The interface is identical.
- **The synthetic renderer draws vehicles narrower than a true 1.8 m
  projection** (it uses a mean local scale that blends lateral and depth
  scales). Cosmetic; the measurement path uses the ground-contact point and is
  unaffected. Documented in the generator.
- **Anomaly Class C (fights, crowd behaviour) is architecture only.** No model.
  The honest first version is motion-based — crowd convergence, running, a
  person down — not "fight classification".
- **No red-light detection** (needs signal-phase input), no tailgating metric
  as a first-class event, no multi-camera handover.

---

## 5. Design decisions worth defending

**The three-class taxonomy.** Class A instrument-grade measurement (speed,
wrong-way, stopped, collision kinematics); Class B classifier proposals
(seatbelt, phone, littering) that carry `requires_review=True` with no path to
an automatic citation; Class C attention routing that never asserts what
happened. Report 3 shows this is not a preference — it is the architecture that
every operating programme uses, for the legal reason that no metrology standard
governs AI behaviour classification.

**Physics before models.** Every Class A detector is arithmetic on a calibrated
ground plane. No weights, no training data, no drift, and an explanation a
magistrate understands: "the vehicle covered 27.4 m in 1.00 s." This is why the
anomaly layer could be verified to ground truth while the occupant layer could
not.

**Abstention as a first-class output.** The system's most important behaviour is
knowing when to say "unclear". Plates return `None` rather than guessing; the
occupant classifier gates on cabin evidence; the evaluation reports an
abstention curve — accuracy as a function of how much you decline to judge —
because that is what tells an operations team the human-review cost of a
threshold.

**Privacy enforced in code, not policy.** Redaction by default, retention by
sweep, audit by hash chain, identity resolution refused unless explicitly
configured. A policy document does not survive contact with an operator in a
hurry; a default does.

**Deliberate restraint on the drone.** Auto-response off by default, hard
mission caps, interlocks re-checked in flight, every launch audited. Report 3
explains why this matters more than expected: a drone law was enacted in Qatar
ten days ago and autonomous docked operation may not be a recognised category
at all.

---

## 6. Next engineering steps, in value order

1. **Field-validate speed** against a GPS-instrumented vehicle at three speeds,
   at one surveyed site. Converts the repo into a credible pilot.
2. **Swap in YOLO + ByteTrack** on real footage; measure detection and ID
   stability on your own cameras.
3. **Add the Doppler fusion rule** — issue only when vision and radar agree
   within tolerance, log both. Turns a disputed measurement into a corroborated
   one and gives a continuous calibration-drift alarm.
4. **Collect and label real windshield crops**; fine-tune the occupant model;
   publish per-class numbers on a held-out real set.
5. **Command-centre UI** — event queue, review workflow, live view, map.
6. **Harden the tracker** for the merge case, since it is the collision case.
