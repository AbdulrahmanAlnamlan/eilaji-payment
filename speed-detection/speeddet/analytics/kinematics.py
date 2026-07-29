"""Motion-derived anomaly detection — the tower's "something is wrong" sense.

Everything here works on **world-space** trajectories (metres, via the
calibration homography), not pixels, so thresholds are physical quantities you
can defend in a review: "deceleration exceeded 6 m/s²", not "the box shrank".

Detectors
---------
``collision``            harsh deceleration + proximity + post-impact
                         immobility + heading jerk, scored together.
``near_miss``            proximity + evasive manoeuvre, but both parties
                         drive away — the leading indicator for a dangerous
                         junction, and the metric that justifies the site.
``stopped_vehicle``      a vehicle immobile on the carriageway — the single
                         highest-value hazard alert for a highway operator.
``wrong_way``            heading opposes the approach's expected direction.
``erratic_driving``      excessive lateral acceleration / weaving.
``congestion``           many tracks, low mean speed, sustained.
``pedestrian_on_roadway`` a person-class track inside the carriageway.

None of these needs a trained model — they are physics on top of the tracker,
which is exactly why they can be verified against known trajectories (see
``tests/test_kinematics.py``) and why they are the right first "AI" to ship.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from ..events import Event, EventType, Severity
from .base import FrameContext, TrackState, heading_delta


@dataclass
class KinematicConfig:
    # --- collision ------------------------------------------------------- #
    #: Deceleration (m/s²) that no normal braking event reaches. Emergency
    #: braking on dry asphalt tops out near 8-9 m/s²; impact exceeds it.
    harsh_decel_mps2: float = 6.0
    severe_decel_mps2: float = 9.0
    #: World distance (m) below which two vehicle centres are "in contact".
    contact_distance_m: float = 2.5
    near_miss_distance_m: float = 4.0
    #: Heading change (deg) within the reaction window that implies a spin or
    #: violent swerve.
    heading_jerk_deg: float = 35.0
    #: Speed (km/h) under which a vehicle counts as stopped.
    stopped_speed_kmh: float = 4.0
    #: How long after the candidate impact we require immobility (s).
    post_impact_stop_s: float = 1.2
    #: Score in [0,1] required to declare a collision.
    collision_threshold: float = 0.6

    # --- stopped vehicle -------------------------------------------------- #
    stopped_duration_s: float = 6.0
    #: Movement (m) allowed while still counting as stopped.
    stopped_displacement_m: float = 1.5

    # --- wrong way -------------------------------------------------------- #
    #: Expected direction of travel in world degrees (atan2(vy, vx)). The demo
    #: geometry has traffic approaching the camera => decreasing Y => -90°.
    expected_heading_deg: Optional[float] = -90.0
    wrong_way_tolerance_deg: float = 110.0
    wrong_way_min_speed_kmh: float = 8.0
    wrong_way_min_duration_s: float = 1.0

    # --- erratic ---------------------------------------------------------- #
    #: Lateral (cross-road) acceleration in m/s² implying a violent swerve.
    lateral_accel_mps2: float = 4.0
    erratic_min_speed_kmh: float = 20.0

    # --- congestion -------------------------------------------------------- #
    congestion_min_tracks: int = 6
    congestion_mean_speed_kmh: float = 20.0
    congestion_duration_s: float = 10.0

    # --- general ----------------------------------------------------------- #
    #: Ignore tracks younger than this — early speed estimates are unstable.
    min_track_age_s: float = 0.4
    #: Only these classes are subject to vehicle kinematics. A carrier bag
    #: thrown from a window decelerates at ~7 m/s² and stops dead, which is
    #: kinematically indistinguishable from a crash — the class is what tells
    #: the two apart, so debris must never enter the collision logic.
    vehicle_classes: Tuple[str, ...] = (
        "vehicle", "car", "truck", "bus", "motorcycle", "van",
    )
    pedestrian_classes: Tuple[str, ...] = ("person", "pedestrian")


class KinematicAnalyzer:
    """Stateful analyzer; feed it one :class:`FrameContext` per frame."""

    def __init__(self, config: Optional[KinematicConfig] = None) -> None:
        self.cfg = config or KinematicConfig()
        #: track_id -> timestamp of the candidate impact awaiting confirmation
        self._impact_candidates: Dict[int, Dict] = {}
        self._reported: Set[Tuple[str, int]] = set()
        self._stopped_since: Dict[int, float] = {}
        self._wrong_way_since: Dict[int, float] = {}
        self._congestion_since: Optional[float] = None
        self._congestion_reported: bool = False

    # ------------------------------------------------------------------ #
    def analyze(self, ctx: FrameContext) -> List[Event]:
        events: List[Event] = []
        live = [s for s in ctx.states.values()
                if s.last_seen == ctx.timestamp and s.age >= self.cfg.min_track_age_s]
        vehicles = [s for s in live if s.class_name in self.cfg.vehicle_classes]
        people = [s for s in live if s.class_name in self.cfg.pedestrian_classes]

        events += self._collisions(ctx, vehicles)
        events += self._stopped(ctx, vehicles)
        events += self._wrong_way(ctx, vehicles)
        events += self._erratic(ctx, vehicles)
        events += self._pedestrians(ctx, people)
        events += self._congestion(ctx, vehicles)
        return events

    # ------------------------------------------------------------------ #
    # Collision / near miss
    # ------------------------------------------------------------------ #
    def _collisions(self, ctx: FrameContext, states: List[TrackState]) -> List[Event]:
        cfg = self.cfg
        events: List[Event] = []

        # 1. Score every currently-visible track for impact-like motion.
        for st in states:
            decel = st.acceleration_mps2(window=0.5)
            heading_now = st.heading_deg(window=0.35)
            heading_before = None
            if len(st.samples) > 6:
                # heading over an earlier window, for the jerk comparison
                old = [s for s in st.samples if s.t <= ctx.timestamp - 0.5]
                if len(old) >= 3:
                    import numpy as np

                    t = np.array([s.t for s in old[-8:]])
                    if float(t.max() - t.min()) > 1e-3:
                        t = t - t.mean()
                        d = float(np.dot(t, t))
                        xs = np.array([s.x for s in old[-8:]])
                        ys = np.array([s.y for s in old[-8:]])
                        vx = float(np.dot(t, xs - xs.mean()) / d)
                        vy = float(np.dot(t, ys - ys.mean()) / d)
                        if abs(vx) > 1e-6 or abs(vy) > 1e-6:
                            heading_before = math.degrees(math.atan2(vy, vx))

            signals: Dict[str, float] = {}
            if decel is not None and decel <= -cfg.harsh_decel_mps2:
                signals["harsh_decel"] = min(
                    1.0, abs(decel) / cfg.severe_decel_mps2
                )
            if heading_now is not None and heading_before is not None:
                jerk = heading_delta(heading_now, heading_before)
                if jerk >= cfg.heading_jerk_deg:
                    signals["heading_jerk"] = min(1.0, jerk / 90.0)

            # proximity to another track
            partner = self._closest_partner(st, states)
            if partner is not None:
                other, dist = partner
                if dist <= cfg.contact_distance_m:
                    signals["contact"] = 1.0 - (dist / cfg.contact_distance_m) * 0.4
                elif dist <= cfg.near_miss_distance_m:
                    signals["proximity"] = 0.5

            if signals:
                cand = self._impact_candidates.get(st.track_id)
                strength = max(signals.values())
                if cand is None or strength > cand["strength"]:
                    self._impact_candidates[st.track_id] = {
                        "t": ctx.timestamp,
                        "signals": dict(signals),
                        "strength": strength,
                        "partner": partner[0].track_id if partner else None,
                        "speed_before": st.speed_at(0.8),
                        "world_xy": st.position,
                    }

        # 2. Confirm candidates once enough time has passed to observe the
        #    aftermath: a real crash leaves the vehicle stopped or spun.
        for st in states:
            cand = self._impact_candidates.get(st.track_id)
            if cand is None:
                continue
            elapsed = ctx.timestamp - cand["t"]
            if elapsed < cfg.post_impact_stop_s:
                continue
            if ("collision", st.track_id) in self._reported:
                continue

            score = 0.0
            sig = dict(cand["signals"])
            score += 0.40 * sig.get("harsh_decel", 0.0)
            score += 0.35 * sig.get("contact", 0.0)
            score += 0.15 * sig.get("heading_jerk", 0.0)
            score += 0.10 * sig.get("proximity", 0.0)

            speed_now = st.speed_kmh
            disp = st.displacement(window=cfg.post_impact_stop_s)
            immobile = (
                speed_now is not None and speed_now <= cfg.stopped_speed_kmh
            ) or (disp is not None and disp <= cfg.stopped_displacement_m)
            if immobile:
                score += 0.30
                sig["post_impact_immobile"] = 1.0

            if score >= cfg.collision_threshold:
                partners = [st.track_id]
                if cand["partner"] is not None:
                    partners.append(cand["partner"])
                    self._reported.add(("collision", cand["partner"]))
                self._reported.add(("collision", st.track_id))
                st.flags["collision"] = ctx.timestamp
                events.append(Event(
                    type=EventType.COLLISION,
                    severity=Severity.CRITICAL,
                    timestamp=ctx.timestamp,
                    tower_id=ctx.tower_id,
                    confidence=round(min(1.0, score), 3),
                    track_ids=partners,
                    plate_text=st.plate_text,
                    world_xy=cand["world_xy"],
                    speed_kmh=cand["speed_before"],
                    message=(
                        f"Possible collision: {len(partners)} vehicle(s), "
                        f"impact speed ~{cand['speed_before'] or 0:.0f} km/h"
                    ),
                    metadata={"signals": sig, "score": round(score, 3)},
                ))
                self._impact_candidates.pop(st.track_id, None)
            elif elapsed > 3.0:
                # Aftermath disagrees — most likely hard braking, not a crash.
                if (sig.get("proximity") or sig.get("contact")) and \
                        ("near_miss", st.track_id) not in self._reported and \
                        sig.get("harsh_decel", 0) > 0:
                    self._reported.add(("near_miss", st.track_id))
                    events.append(Event(
                        type=EventType.NEAR_MISS,
                        severity=Severity.MEDIUM,
                        timestamp=ctx.timestamp,
                        tower_id=ctx.tower_id,
                        confidence=round(min(1.0, score + 0.2), 3),
                        track_ids=[st.track_id],
                        world_xy=cand["world_xy"],
                        message="Near miss: emergency braking in close proximity",
                        metadata={"signals": sig},
                    ))
                self._impact_candidates.pop(st.track_id, None)
        return events

    @staticmethod
    def _closest_partner(
        st: TrackState, states: List[TrackState]
    ) -> Optional[Tuple[TrackState, float]]:
        pos = st.position
        if pos is None:
            return None
        best: Optional[Tuple[TrackState, float]] = None
        for other in states:
            if other.track_id == st.track_id:
                continue
            opos = other.position
            if opos is None:
                continue
            d = math.hypot(pos[0] - opos[0], pos[1] - opos[1])
            if best is None or d < best[1]:
                best = (other, d)
        return best

    # ------------------------------------------------------------------ #
    def _stopped(self, ctx: FrameContext, states: List[TrackState]) -> List[Event]:
        cfg = self.cfg
        events: List[Event] = []
        active = set()
        for st in states:
            speed = st.speed_kmh
            if speed is None:
                continue
            disp = st.displacement(window=2.0)
            is_stopped = speed <= cfg.stopped_speed_kmh and (
                disp is None or disp <= cfg.stopped_displacement_m
            )
            if not is_stopped:
                self._stopped_since.pop(st.track_id, None)
                continue
            active.add(st.track_id)
            since = self._stopped_since.setdefault(st.track_id, ctx.timestamp)
            if ctx.timestamp - since < cfg.stopped_duration_s:
                continue
            if ("stopped", st.track_id) in self._reported:
                continue
            # A vehicle already flagged as crashed is covered by that event.
            if "collision" in st.flags:
                continue
            self._reported.add(("stopped", st.track_id))
            events.append(Event(
                type=EventType.STOPPED_VEHICLE,
                severity=Severity.HIGH,
                timestamp=ctx.timestamp,
                tower_id=ctx.tower_id,
                confidence=0.9,
                track_ids=[st.track_id],
                plate_text=st.plate_text,
                world_xy=st.position,
                message=(f"Vehicle stationary on carriageway for "
                         f"{ctx.timestamp - since:.0f}s"),
                metadata={"stopped_seconds": round(ctx.timestamp - since, 1)},
            ))
        for tid in list(self._stopped_since):
            if tid not in active:
                self._stopped_since.pop(tid, None)
        return events

    # ------------------------------------------------------------------ #
    def _wrong_way(self, ctx: FrameContext, states: List[TrackState]) -> List[Event]:
        cfg = self.cfg
        if cfg.expected_heading_deg is None:
            return []
        events: List[Event] = []
        active = set()
        for st in states:
            speed = st.speed_kmh
            heading = st.heading_deg(window=0.6)
            if speed is None or heading is None:
                continue
            if speed < cfg.wrong_way_min_speed_kmh:
                self._wrong_way_since.pop(st.track_id, None)
                continue
            if heading_delta(heading, cfg.expected_heading_deg) < cfg.wrong_way_tolerance_deg:
                self._wrong_way_since.pop(st.track_id, None)
                continue
            active.add(st.track_id)
            since = self._wrong_way_since.setdefault(st.track_id, ctx.timestamp)
            if ctx.timestamp - since < cfg.wrong_way_min_duration_s:
                continue
            if ("wrong_way", st.track_id) in self._reported:
                continue
            self._reported.add(("wrong_way", st.track_id))
            events.append(Event(
                type=EventType.WRONG_WAY,
                severity=Severity.CRITICAL,
                timestamp=ctx.timestamp,
                tower_id=ctx.tower_id,
                confidence=0.95,
                track_ids=[st.track_id],
                plate_text=st.plate_text,
                speed_kmh=speed,
                world_xy=st.position,
                message=f"WRONG-WAY vehicle at {speed:.0f} km/h",
                metadata={"heading_deg": round(heading, 1),
                          "expected_deg": cfg.expected_heading_deg},
            ))
        for tid in list(self._wrong_way_since):
            if tid not in active:
                self._wrong_way_since.pop(tid, None)
        return events

    # ------------------------------------------------------------------ #
    def _erratic(self, ctx: FrameContext, states: List[TrackState]) -> List[Event]:
        cfg = self.cfg
        events: List[Event] = []
        for st in states:
            speed = st.speed_kmh
            if speed is None or speed < cfg.erratic_min_speed_kmh:
                continue
            if ("erratic", st.track_id) in self._reported:
                continue
            v_now = st.velocity(window=0.4)
            v_then = None
            old = [s for s in st.samples if s.t <= ctx.timestamp - 0.4]
            if len(old) >= 3 and v_now is not None:
                import numpy as np

                t = np.array([s.t for s in old[-8:]])
                if float(t.max() - t.min()) > 1e-3:
                    t = t - t.mean()
                    d = float(np.dot(t, t))
                    xs = np.array([s.x for s in old[-8:]])
                    v_then = (float(np.dot(t, xs - xs.mean()) / d), 0.0)
            if v_now is None or v_then is None:
                continue
            lateral_accel = abs(v_now[0] - v_then[0]) / 0.4
            if lateral_accel >= cfg.lateral_accel_mps2:
                self._reported.add(("erratic", st.track_id))
                events.append(Event(
                    type=EventType.ERRATIC_DRIVING,
                    severity=Severity.MEDIUM,
                    timestamp=ctx.timestamp,
                    tower_id=ctx.tower_id,
                    confidence=min(1.0, lateral_accel / (2 * cfg.lateral_accel_mps2)),
                    track_ids=[st.track_id],
                    plate_text=st.plate_text,
                    speed_kmh=speed,
                    world_xy=st.position,
                    message=f"Erratic manoeuvre: {lateral_accel:.1f} m/s² lateral",
                    metadata={"lateral_accel_mps2": round(lateral_accel, 2)},
                ))
        return events

    # ------------------------------------------------------------------ #
    def _pedestrians(self, ctx: FrameContext, states: List[TrackState]) -> List[Event]:
        events: List[Event] = []
        for st in states:
            if st.class_name not in ("person", "pedestrian"):
                continue
            if ("pedestrian", st.track_id) in self._reported:
                continue
            self._reported.add(("pedestrian", st.track_id))
            events.append(Event(
                type=EventType.PEDESTRIAN_ON_ROADWAY,
                severity=Severity.CRITICAL,
                timestamp=ctx.timestamp,
                tower_id=ctx.tower_id,
                confidence=0.85,
                track_ids=[st.track_id],
                world_xy=st.position,
                message="Pedestrian detected on the carriageway",
            ))
        return events

    # ------------------------------------------------------------------ #
    def _congestion(self, ctx: FrameContext, states: List[TrackState]) -> List[Event]:
        cfg = self.cfg
        speeds = [s.speed_kmh for s in states if s.speed_kmh is not None]
        if len(speeds) < cfg.congestion_min_tracks:
            self._congestion_since = None
            self._congestion_reported = False
            return []
        mean_speed = sum(speeds) / len(speeds)
        if mean_speed > cfg.congestion_mean_speed_kmh:
            self._congestion_since = None
            self._congestion_reported = False
            return []
        if self._congestion_since is None:
            self._congestion_since = ctx.timestamp
            return []
        if self._congestion_reported:
            return []
        if ctx.timestamp - self._congestion_since < cfg.congestion_duration_s:
            return []
        self._congestion_reported = True
        return [Event(
            type=EventType.CONGESTION,
            severity=Severity.LOW,
            timestamp=ctx.timestamp,
            tower_id=ctx.tower_id,
            confidence=0.9,
            track_ids=[s.track_id for s in states],
            message=(f"Congestion: {len(speeds)} vehicles at mean "
                     f"{mean_speed:.0f} km/h"),
            metadata={"vehicle_count": len(speeds),
                      "mean_speed_kmh": round(mean_speed, 1)},
        )]
