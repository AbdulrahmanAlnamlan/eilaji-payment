# Sentinel Tower — integrated roadside enforcement, safety and response unit

**One sentence.** A stacked roadside tower that measures speed to instrument
grade, watches for dangerous behaviour and abnormal events, gives the command
centre a live window and a documented incident feed, and carries a drone in
its head that launches to a coordinate, films, and returns to charge.

This document is the whole vision. Where a capability is already built and
tested in this repository it says so; where it needs hardware, a trained model
or an authority's cooperation it says that instead. The distinction matters —
the parts that are done are the parts you can demonstrate next week.

---

## 1. The stack

Physically the unit is one mast with functional decks. Each deck is a field
replaceable unit: a failure or an upgrade touches one layer, not the tower.

```
        ╔══════════════════════════════════════════╗
   D5   ║  DRONE HEAD                              ║  sealed nest, hatch,
        ║  landing pad · contacts · climate bay     ║  precision landing
        ╠══════════════════════════════════════════╣
   D4   ║  SENSING HEAD                            ║  speed cam · ALPR tele
        ║  4 × camera · IR · Doppler · weather      ║  occupant tele · PTZ
        ╠══════════════════════════════════════════╣
   D3   ║  COMPUTE DECK                            ║  Jetson Orin ×1–2
        ║  edge AI · NVMe evidence · TPM            ║  all inference here
        ╠══════════════════════════════════════════╣
   D2   ║  COMMS DECK                              ║  5G · fibre · mesh
        ║  router · VPN · GNSS time                ║  backhaul + failover
        ╠══════════════════════════════════════════╣
   D1   ║  POWER & THERMAL                         ║  1 kW service · UPS
        ║  PSU · battery · A/C · filtration         ║  the Qatar deck
        ╚══════════════════╤═══════════════════════╝
                    mast, 6–9 m, breakaway base
        ════════════════════╧═══════════════════════  carriageway
```

**Why stacked and modular.** Roadside access is expensive and disruptive: a
lane closure to swap a camera costs more than the camera. Decks let a
technician replace the compute or the nest in one visit without touching the
calibrated sensing head — and the sensing head is the thing that must *never*
move, because every speed measurement depends on its calibration holding.

---

## 2. Sensor suite (deck D4)

| Sensor | Purpose | Notes |
| --- | --- | --- |
| Wide camera, 4K 30–60 fps | speed measurement, tracking, anomaly detection | the calibrated instrument; covers 60–100 m |
| Telephoto ALPR camera ×2 (per direction) | plate capture | IR-pass filter + IR illuminator; plates are retro-reflective, so IR reads them at night better than visible light |
| Telephoto occupant camera | seatbelt / phone | **circular polariser** to kill windshield reflection; near-IR to see through tint |
| 24 GHz Doppler radar | independent speed | the second opinion — see §4 |
| PTZ dome | operator live view | the CCTV function; separate from the measurement cameras so an operator panning cannot disturb calibration |
| Weather head | anemometer, temp, humidity, particulate | gates drone flight; local truth, not a forecast |
| Microphone array *(optional)* | impact//scream acoustic trigger | strong accident cue; check legal position on audio capture separately — it is treated far more strictly than video in most regimes |

**The calibration rule that governs the whole design:** the wide camera is a
measuring instrument. It is rigidly mounted, never zoomed, never panned, and
its homography is surveyed on installation and re-verified on a schedule. All
the flexible, operator-driven viewing happens on the PTZ, which measures
nothing. Mixing those two roles into one camera is the most common way these
systems lose their evidential standing.

---

## 3. The AI stack — and an honest taxonomy

Everything the tower detects falls into one of three classes, and the class
determines what may be done with the output. This is the most important idea
in the document.

### Class A — Instrument-grade measurement
*Speed, wrong-way, stopped vehicle, collision kinematics.*

Derived from physics on a calibrated ground plane: metres and seconds, not
model opinions. Reproducible, explainable in a sentence a magistrate
understands ("the vehicle covered 27.4 m in 1.00 s"), and testable against
known ground truth — which is exactly what the test-suite in this repo does.

**Status: built and verified.** Speed recovers scripted ground truth to
within ~3% (0.1–0.5% on the tighter camera geometry). Collision, stopped
vehicle, wrong-way and erratic driving detect their scripted scenarios.

### Class B — Classifier proposals
*Seatbelt, phone use, littering, helmet.*

A neural network's opinion about pixels seen through glass, at an angle, in
glare. These systems work — Australia and the UAE run them at scale — but they
work as **proposal generators feeding human adjudication**, typically with a
double-review workflow. Australia's NSW programme, the largest deployment of
phone-detection cameras, reviews machine-flagged images before any penalty
issues, and that is not timidity, it is what makes the programme survive
appeal.

Build it exactly that way: the tower proposes, a trained reviewer disposes.
In code, every Class B event carries `requires_review = True` and no path
exists to auto-issue from one.

**Status: pipeline built and tested end-to-end** (ROI extraction → temporal
voting → review-flagged event). **The classifier model itself must be trained
on your own footage** — a model trained on another country's vehicle mix and
camera geometry will not transfer. Budget a labelling campaign: ~20–50k
labelled windshield crops from your actual cameras is the realistic order.

### Class C — Anomaly signals
*Fights, crowd behaviour, "something unusual".*

Genuinely useful as an **attention router** — a signal that says "operator,
look at camera 12 now". Genuinely unreliable as a classifier of what is
happening. Fight-detection models trained on curated datasets have high
false-positive rates on real CCTV, where two people embracing, a group
celebrating, and a scuffle look similar from 40 m in a fixed camera.

So: use Class C to *direct human attention*, never to conclude. The
operational value is real and large — an operator watching 60 cameras cannot
see them all, and cutting time-to-notice on a real incident from minutes to
seconds saves lives at a crash scene. Just do not let it produce a record
that says "assault detected", because that record will be wrong often enough
to poison the whole system's credibility.

**Status: architecture and event routing built; the anomaly models
themselves are the next build.** The honest first version is
motion/kinematic: sudden crowd convergence, running detection, a person
falling and not getting up, vehicles stopping abnormally. Those are far more
reliable than "fight classification" and cover most of the real value.

---

## 4. Why the tower carries a radar as well as a camera

The vision pipeline is good. It is not, on its own, the strongest possible
evidence. A 24 GHz Doppler module gives a second, physically independent
measurement, and the rule is simple:

> Issue a speeding citation only when the vision speed and the radar speed
> agree within a set tolerance. Log both. If they disagree, the event is
> retained for engineering review and no citation issues.

This is how certified enforcement units work, it turns a disputed measurement
into a corroborated one, and it costs about $1k per unit. It also gives you a
continuous self-check on calibration drift: if vision and radar start
disagreeing systematically at one site, the camera has moved and the tower
tells you so before anyone challenges a ticket.

---

## 5. From event to command centre

```
 detect ─► classify ─► EventBus ─┬─► local JSONL     (always, the record)
                                 ├─► webhook  ──► command centre
                                 ├─► evidence clip cut from ring buffer
                                 └─► auto-response (drone) if permitted
```

Every event carries: type, severity, confidence, timestamp, tower id, world
coordinates, involved track ids, plate (if read), the evidence pointer, and
the detector's own explanation of which signals fired. That last field is what
lets an engineer answer "why did it think that?" six months later.

**Severity drives routing, not event type.** A CRITICAL event (collision,
wrong-way, pedestrian on the carriageway) goes straight to the duty
dispatcher's queue with the clip auto-cut and, where permitted, a drone
launched. A LOW event (a marginal speeder) goes to the batch review queue.

**Backhaul reality:** only events leave the tower — a few MB each. Raw video
never streams continuously; that would cost a fortune in 5G and create a
mass-retention problem you do not want. The tower is an event sensor that can
be *asked* for a live view, not a firehose.

**Offline behaviour:** if the link drops, events queue on local NVMe and drain
on reconnect. An enforcement tower that loses incidents during an outage is
worse than useless, because you cannot tell which incidents you lost.

---

## 6. The CCTV function — and the discipline it needs

The command centre can take live control of the PTZ camera. This is the
feature that makes the unit multi-functional, and it is also the feature that
quietly turns a traffic system into a general surveillance system if it is
built carelessly. Three controls, all implemented in `tower/station.py`:

1. **Sessions are named.** A live view is opened by an identified operator
   with a stated justification. No anonymous viewing.
2. **Sessions expire.** Default 10 minutes, then it closes and must be
   renewed. An always-open feed is precisely the failure mode to design out.
3. **Everything is audited** to a hash-chained log (`privacy.AuditLog`). Edit
   or delete a line and verification fails. This protects the *operators* as
   much as the public — when someone alleges misuse, the log is the defence.

---

## 7. Faces: what to build, and what not to

You asked for face detection. Split it into two things that sound similar and
are completely different in law and in risk:

**Face detection (finding that a face is present)** — build this. Its job in
this system is *redaction*: automatically blurring bystanders in stored
evidence so a clip of a crash does not become a file of everyone who walked
past. `privacy.PrivacyFilter` does this by default. It reduces your legal
exposure and it is the right default.

**Face recognition (matching a face to an identity)** — do not put this in the
tower. Reasons, in order of how much they should matter to you:

1. **It does not work well enough at this geometry.** A face through a raked,
   tinted windshield at 40 m, at speed, at night, is not a usable biometric
   probe. Vendors' accuracy figures come from cooperative subjects at 2 m.
   You would be adding a large legal liability in exchange for a capability
   that mostly returns "no match" or, worse, a wrong match.
2. **The plate already solves your problem, better.** For traffic enforcement
   the addressee is the registered keeper. Plate → registry is accurate,
   lawful, and already built here.
3. **Biometric data is special-category data under Qatar's PDPPL (Law No. 13
   of 2016).** It requires a stronger lawful basis than routine traffic
   enforcement supplies, and it puts you in a much more demanding compliance
   posture — one that is unpleasant to retrofit and easy to design around now.
4. **A roadside box is a bad place for a biometric database.** Towers are
   physically accessible, get stolen, get decommissioned. A tower holding
   face embeddings is a breach waiting to happen; a tower holding none is not.

The architecture that gives you the capability without the liability is
already in `privacy.py`: the tower holds **no face database and no
embeddings**. Where an authorised identity question must be asked, it is asked
*of the authority's system*, through `IdentityResolver`, per event, with the
requesting operator and justification recorded. The default resolver refuses;
an unconfigured tower cannot perform identity lookups at all.

If MOI later requires face matching for a specific, authorised purpose, it
belongs on their side of that interface, under their legal basis and their
audit — not distributed across a hundred roadside units. Design it that way
now and the conversation with their legal team is short instead of fatal.

---

## 8. The drone head

**The scoping decision that keeps this sane:** the drone does not measure
speed. A moving camera has no fixed homography, so its speed estimates are not
citation-grade, and claiming otherwise would undermine the fixed head's
credibility too. The fixed deck measures. The drone *documents and extends*:

* **Incident response.** A collision fires; the drone launches to the
  coordinate, holds at 45 m with the gimbal down, and films the scene while
  responders are still en route. Overhead footage of a crash — vehicle
  positions, debris field, skid marks — is the single most valuable
  reconstruction artefact and it disappears within minutes of traffic
  resuming.
* **Patrol.** Scheduled loops over a pre-approved corridor for congestion,
  wrong-way, debris, illegal parking.
* **Reach.** Service roads, compound interiors, the far side of an
  interchange — places the mast cannot see.

**Nest.** Sealed bay with a motorised hatch (non-negotiable in Qatar: an open
pad is finished after one shamal), climate-held interior, precision landing on
RTK + a visual fiducial + IR beacon for night, mechanical centring bars, and
spring contact charging. Contact beats wireless here: wireless charging dumps
its losses as heat, and heat is already the enemy.

**Duty cycle.** ~30 min flight, ~40 min charge → one drone is airborne roughly
35–40% of the time. Two bays gets you near-continuous coverage. Size the
promise to that number; a single-bay tower cannot honestly be sold as
"continuous aerial monitoring".

**Interlocks** (in `tower/nest.py`, checked at launch *and* continuously in
flight, because a condition that turns unsafe mid-sortie must trigger a recall,
not a warning): sustained wind, gusts, ambient temperature, battery
temperature and charge, visibility, dust index, precipitation, GNSS satellite
count, link quality, permitted hours, and a hard mission time cap. Battery
below the recall threshold or gusts over limit ⇒ come home now.

**Autonomy posture.** `autonomous_launch_enabled` defaults to on for the
state machine but `drone_auto_response_enabled` on the station defaults to
**off**. A tower does not start flying by itself until someone deliberately
enables it for that site, with the flight permissions to match.

---

## 9. Qatar engineering — the constraints that actually bite

* **Heat.** 45–50 °C ambient; far higher inside a sealed sunlit box. This is
  the binding constraint on the entire drone concept: a LiPo pack cycled and
  stored at 50 °C is finished in a season. Budget active cooling for the
  compute deck *and* the nest, white/radiative finishes, sunshades, and
  components rated ≥ 60 °C. Then plan for the cooling to be the thing that
  fails first — it has moving parts and a filter.
* **Dust.** IP66 minimum, filtered positive pressure where possible, hatch
  seals as a scheduled wear item, hydrophobic/oleophobic optical coatings, and
  a realistic lens-cleaning cadence. Dust on the ALPR window is the most
  common cause of a silent accuracy decline.
* **Salt** (coastal): conformal-coated boards, sealed connectors.
* **Shamal.** The weather head must recall the drone on dust index *before*
  visibility collapses — by the time you can see the storm on camera it is
  too late to launch a recovery.
* **Power.** 40–70 W compute, 100–300 W cooling in summer, 300–500 W peak
  drone charging → design a **1 kW mains service**. Solar-only is viable for a
  camera-only unit (~600 W array + 2–3 kWh LiFePO₄), not for a drone tower.

---

## 10. Legal and operational reality

* **Enforcement authority.** Speed and red-light enforcement is an MOI
  function. Until adopted, the unit is a *pilot instrument*: it measures,
  records and demonstrates, it does not issue. On private land (a compound,
  an industrial estate, Al-Thuraiya's own site) you can operate the same stack
  today for internal safety policy and gate access control with no enforcement
  authority at all — which is why that remains the right first deployment.
* **Drone flight.** QCAA permits per operation; autonomous BVLOS over public
  roads is a high bar and realistically needs the government partner. Over
  private land the path is far simpler.
* **Data.** PDPPL applies. Practical posture: minimise (events not streams),
  redact by default (blur bystanders), retain on a clock (30 days unactioned,
  365 actioned, **zero** raw non-event video), keep identity resolution on the
  authority's side, and audit every privileged access. All implemented in
  `privacy.py` — retention is enforced by a sweep, not by a policy sentence.
* **Transparency.** Signposted enforcement sites outperform hidden ones on
  the metric that matters (fewer crashes, not more citations), and they are
  vastly easier to defend politically. Design the programme to be visible.

---

## 11. What exists today vs what is next

**Built and tested in this repository (105 tests passing):**

- calibrated speed measurement (homography, tracking, least-squares velocity)
- Qatar ALPR: full category-code taxonomy, plate reading, safe-degradation
- evidence ring buffer → per-incident clips; violation logging
- event model, bus with dedupe, JSONL/webhook/console dispatch
- kinematic anomaly analytics: collision, near-miss, stopped vehicle,
  wrong-way, erratic driving, congestion, pedestrian-on-roadway
- occupant analytics pipeline (windshield ROI → temporal voting → review
  event) with a pluggable classifier
- littering detection with source-vehicle attribution
- privacy: face-blur redaction, hash-chained audit log, retention sweep,
  refusing-by-default identity boundary
- tower orchestration: subsystem health, time-boxed audited CCTV sessions,
  drone nest state machine with full interlocks, mission planning with
  endurance feasibility checks
- scripted incident scenario generator producing ground truth for all of it
- an executable whole-system demo (`examples/sentinel_demo.py`): boot →
  audited CCTV session → footage → collision event → drone sortie with
  interlocks → audit verification → retention sweep

**Three bugs the incident tests caught, worth recording** because each is a
false-positive mode a demo would have hidden:

1. A thrown object decelerating at 7 m/s² and stopping is kinematically
   *identical to a crash*. Fixed by restricting collision logic to
   vehicle-class tracks — which is also why the detector must supply real
   classes, not just blobs.
2. The occupant classifier called "no seatbelt" on a car whose cabin was not
   visible at all. An absent belt and an absent *view* of a belt are not the
   same observation; it now requires positive evidence of a cabin before
   ruling, and returns "unclear" otherwise.
3. Litter events fired before the plate became readable, losing the
   attribution that is the entire point. Fixed with an attribution grace
   period, and by reading plates for *every* vehicle rather than only
   speeders — a litterer is usually not speeding.

**Next, in order of value per effort:**

1. Real footage from one site → survey calibration → validate speed against a
   GPS-instrumented vehicle at three speeds. *This is the step that converts
   the repo into a credible pilot.*
2. Doppler module + fusion rule.
3. Labelling campaign → train the occupant classifier on local data.
4. Command-centre UI (event queue, review workflow, live view, map).
5. Nest v1 on an off-the-shelf dock; custom/local-assembly nest as the
   production and procurement story.

---

## 12. Indicative BOM (prototype quantities, USD)

| Configuration | Estimate |
| --- | --- |
| Camera-only unit (2 cams, Jetson Orin NX, 5G, enclosure, cooling) | $4–7k |
| + telephoto occupant camera, polariser, IR illuminator | +$1.5–3k |
| + Doppler module | +$0.5–1.5k |
| + PTZ dome for CCTV | +$0.8–2k |
| + drone nest, off-the-shelf dock incl. airframe | +$25–35k |
| + drone nest, custom build | +$10–18k parts, months of engineering |
| Mast, foundation, power connection, installation | $5–15k site-dependent |
| **Full Sentinel tower, prototype** | **~$45–70k** |

Camera-only variants are the volume product; full towers go at the sites that
justify them.

---

## 13. The risks worth naming

1. **Calibration drift** — a knocked or thermally-crept camera silently
   corrupts every speed. Mitigate: rigid mount, radar cross-check, scheduled
   re-verification, automatic drift alarm.
2. **Classifier false positives at scale** — 1% error on 100k vehicles/day is
   1,000 wrong proposals daily. Mitigate: human review as an architectural
   requirement, per-class confidence thresholds tuned on real data, published
   accuracy figures.
3. **Scope creep into general surveillance** — the fastest way to lose public
   and political support. Mitigate: the session/audit/retention controls
   above, and a written scope for what the tower is for.
4. **Drone loss over a public road** — a falling airframe is a lethal object.
   Mitigate: conservative interlocks, no-fly over live lanes where avoidable,
   parachute on the airframe, and flight only under the partner's permits.
5. **Thermal failure in August** — plan the cooling maintenance cycle before
   the first summer, not after it.
6. **Vendor/procurement risk on the drone** — government buyers increasingly
   restrict certain foreign drone platforms for security work. Prototype on
   what is available; plan the locally-assembled airframe as the production
   answer.
