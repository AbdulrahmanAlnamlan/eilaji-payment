# Sentinel: roadside radar unit + drone nest

> **Precedent (China, 2025–26) — read the caveat before using this in a pitch.**
> Reporting describes municipal deployments in Shenzhen and Guangzhou where
> drones dispatch from automated pole-mounted "hives" and AI identifies
> illegal parking, wrong-way driving, emergency-lane occupation and speeding,
> framed as "non-contact law enforcement and evidence collection".
>
> **What is verified:** drones launching from automated nests for traffic
> monitoring and *evidence capture*, with humans in the loop.
> **What is NOT verified:** that any citation is issued autonomously. The
> available sources are low-tier — a drone-industry blog, an aggregator, one
> state-adjacent outlet and one vendor's own marketing page
> ([Unmanned Airspace](https://www.unmannedairspace.info/latest-news-and-information/how-drones-in-china-are-transforming-road-traffic-management-safety/),
> [The Droning Company](https://thedroningcompany.com/blog/china-using-traffic-drones-to-ease-congestion),
> [China Daily HK](https://www.chinadailyhk.com/hk/article/616654)).
> An earlier draft of this document asserted autonomous violation issuance and
> a specific helmet-enforcement example as fact, sourced only from a social
> media clip. That was an overstatement and has been removed. **Do not put the
> autonomous-citation claim in front of MOI** — if they check it and it does
> not hold, it costs the credibility of everything else in the deck.
>
> Two design lessons that survive the caveat: (1) **pole-top retrofit** on
> existing street furniture beats building a new pole — smaller footprint, no
> civil works, faster rollout; (2) their nest is a light clamshell viable in a
> temperate climate — the Qatar version needs the sealed, cooled bay in §4.

Design for the street hardware: a pole-mounted enforcement camera (the
"radar") that is also a docking/charging station for a patrol drone. The
fixed head does the legally-defensible speed measurement; the drone extends
coverage — patrol loops over the road/street, incident documentation — and
returns to the station to recharge.

```
                    ┌──────────────────────────┐
                    │  DRONE NEST (roof bay)   │  motorised dust-proof hatch
                    │  landing pad + charging  │  precision-landing beacons
                    ├──────────────────────────┤
                    │  SENSING HEAD            │  wide speed cam + tele ALPR
                    │  (optional Doppler unit) │  IR illuminator (night)
                    ├──────────────────────────┤
                    │  EDGE COMPUTE BOX        │  Jetson Orin, runs speeddet
                    │  5G router · storage     │  only violations uploaded
                    ├──────────────────────────┤
                    │  POWER & COOLING         │  mains 1 kW / solar hybrid
                    └────────────┬─────────────┘
                                 │ pole, 6–8 m
                            ─────┴─────  road
```

## 1. Fixed sensing head (the radar)

| Component | Choice | Why |
| --- | --- | --- |
| Speed camera | 1080p–4K, 25–60 fps, wide view of 60–100 m of road | feeds the calibrated homography + tracking pipeline in this repo |
| ALPR camera | telephoto per direction, IR illuminator + IR-pass filter | plates need ≥ ~20 px height; night reads via retro-reflective plates |
| Doppler radar module (optional but recommended) | 24 GHz K-band traffic radar | independent second speed source; vision+radar agreement is what makes a citation defensible — mirrors how commercial enforcement units are certified |
| Edge compute | Jetson Orin NX (or AGX for multi-lane) | runs YOLO + tracking + speed + ALPR on-device; only violation events (clip + JSON) leave the unit |
| Comms | 5G/LTE modem (Ooredoo/Vodafone), local SSD ring buffer as fallback | violations are a few MB each; no raw-video streaming needed |
| Enclosure | IP66+, sunshade, active cooling | see §4 — Qatar summer is the design driver |

The software is exactly the `speeddet` pipeline: the unit runs
`speeddet run --video rtsp://<local-cam> --live` with a surveyed calibration
per approach. Sensor fusion rule for citations: issue only when
`|v_vision − v_radar| < threshold`, log both.

## 2. Drone nest

**Role of the drone (important scoping):** the drone is *not* the speed
measuring instrument — a moving camera has no fixed homography, so its speed
estimates aren't citation-grade. The fixed head measures; the drone:

- flies scheduled patrol loops over the street/road segment (situational
  awareness, congestion, wrong-way/illegal-parking detection),
- launches on triggers (accident detected, violation of interest) to
  document the scene from above and re-read plates with its zoom camera,
- extends ALPR coverage to places the pole can't see (parallel service
  roads, compound interiors).

**Nest mechanics:**

- Enclosed roof bay with a motorised hatch — mandatory in Qatar (dust/sand;
  an open pad is dead in one shamal). Interior climate-held for battery
  health (LiPo storage above ~40 °C ages fast; summer ambient exceeds 45 °C).
- Precision landing: RTK GPS gets the drone to ~1 m; final approach on a
  visual fiducial (ArUco/AprilTag on the pad) + IR beacon for night; X-Y
  centering bars physically align the drone for charging contact.
- Charging: spring contact pads (simple, fast, serviceable) over wireless
  (lossy → heat, and heat is the enemy here). ~35–45 min to 80 %.
- Duty cycle per drone: ~25–35 min flight + ~40 min charge → one drone gives
  ~35–40 % airborne time. A two-bay nest (or two alternating single-bay
  stations) approaches continuous coverage.

**Drone platform decision — the key fork:**

| Option | Pros | Cons |
| --- | --- | --- |
| Off-the-shelf dock ecosystem (e.g. DJI Dock 3 + Matrice 4D/4TD) | proven precision-landing + charging + thermal mgmt; weeks to deploy; IP55+, rated to 50 °C | cost (~$25–35k); government buyers (MOI) increasingly restrict Chinese-made drones for security work — check procurement rules **before** committing |
| Custom PX4/ArduPilot drone + custom nest | data sovereignty, local assembly story (strong pitch angle in Qatar), no vendor lock | you own precision landing, charging, weatherproofing — months of engineering; v1 risk |

Recommendation: **prototype on an off-the-shelf dock** to prove the concept
and the software integration, and present the custom/local-assembly path as
the production roadmap item — that's also the better industrial-strategy
story for an MOI/Ashghal pitch.

## 3. Software integration

- Nest controller (same Jetson or a small SBC) speaks to the drone via the
  vendor SDK / MAVLink: mission upload, launch/land, telemetry, video pull.
- Drone video runs through the same `speeddet` detection + tracking +
  `QatarPlateReader`/ALPR stack — just without the speed stage (no fixed
  calibration). Detections are georeferenced from gimbal pose + drone GPS.
- Event bus: fixed head publishes `violation` events; mission scheduler
  subscribes (e.g. accident-class detection → launch documentation sortie).
- Everything lands in the same backend (FastAPI + PostgreSQL from the
  roadmap): violations, drone sorties, plate reads, evidence clips.

## 4. Qatar environmental engineering (the real hard part)

- **Heat:** 45–50 °C ambient, much higher inside a sealed box in the sun.
  Budget active cooling (compressor or big TEC) for the electronics bay and
  especially the nest battery area. White paint + radiation shield + sunshade
  are free wins. All components rated ≥ 60 °C or derated.
- **Dust/sand:** IP66 minimum, positive-pressure filtered bay if possible;
  hatch seals are a wear item; camera windows need a maintenance wipe
  schedule (or hydrophobic/oleophobic coating).
- **Humidity/salt** (coastal): conformal-coated boards, sealed connectors.
- **Wind:** patrol drone needs ≥ 12 m/s wind tolerance; nest auto-recalls on
  wind/dust alerts (station weather sensor: anemometer + PM sensor).

## 5. Power budget

| Load | Draw |
| --- | --- |
| Jetson + cameras + comms | 40–70 W continuous |
| Cooling (summer peak) | 100–300 W |
| Drone charging (peak) | 300–500 W |
| **Design point** | **~1 kW mains service** |

Mains is strongly recommended for any drone-charging unit. A camera-only
(no nest) variant can run standalone on ~600 W of solar + 2–3 kWh LiFePO₄.

## 6. Regulatory reality (Qatar)

- **Drones:** QCAA permits per operation; autonomous BVLOS patrol over public
  roads is a high bar and effectively requires the government partner. Over a
  **private compound / industrial area** (the Al-Thuraiya first-site idea)
  the approval path is far simpler — that's another reason it's the right
  pilot site.
- **Enforcement:** radar citations remain MOI authority — the unit is a
  *pilot/PoC* instrument until adopted; private sites use it for internal
  speed policy, gate ALPR and safety, which needs no enforcement authority.
- **Data:** plate → person data falls under Qatar's PDPPL; keep owner lookup
  on the government side of the interface, store only plate strings + clips.

## 6b. Configuration variants

| Variant | What | When |
| --- | --- | --- |
| **A. Full station** (this doc's main design) | new pole: sensing head + edge box + climate-controlled nest, ~1 kW mains | flagship sites, highway segments, the MOI pilot |
| **B. Pole-top retrofit nest** (China-style) | compact nest clamped to an *existing* light/sign pole, small drone, power tapped from the street-light circuit; sensing optional | dense urban rollout, intersections, compounds — cheapest per point |
| **C. Camera-only unit** | sensing head + edge box, no nest; solar-capable | pure speed/ALPR points feeding the same backend |

Variant B is what the Chinese municipal pilots run. Its constraints: the
street-light circuit is often energised only at night (needs a small battery
buffer or a dedicated feed for daytime charging), pole load/wind moment must
be checked, and in Qatar the clamshell must still be sealed against dust with
at least passive thermal management for the parked drone's battery.

## 7. Phased build

1. **Fixed unit on the pilot site** — pole, cameras, Jetson running
   `speeddet`, calibration surveyed, violations dashboard. (This repo is that
   software, ready today.)
2. **Add Doppler module + fusion rule** — citation-grade evidence story.
3. **Nest v1 with off-the-shelf dock** — scheduled patrols, event-triggered
   sorties, drone ALPR feeding the same backend.
4. **Custom nest / local-assembly drone** — production + procurement story
   for the MOI/Ashghal pitch; two-bay for continuous coverage.

## 8. Rough unit economics (prototype quantities)

| Configuration | BOM estimate |
| --- | --- |
| Fixed radar unit (cam ×2, Jetson Orin NX, 5G, enclosure, cooling) | $4–7k |
| + Doppler module | +$0.5–1.5k |
| + Nest, off-the-shelf dock incl. drone | +$25–35k |
| + Nest, custom (drone + pad + hatch + charging) | +$10–18k (plus engineering time) |
