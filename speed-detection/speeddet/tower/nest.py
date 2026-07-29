"""Drone nest: the state machine and the interlocks that keep it out of trouble.

The nest sits at the top of the tower. It holds the drone in a sealed,
climate-managed bay, opens a hatch, launches, tracks the sortie, recovers the
drone by precision landing, closes up and charges.

The state machine is deliberately explicit and the transitions are guarded,
because the failure modes are physical: launching into a sandstorm, opening a
hatch at 55 °C, or sending an airframe past the point where it can get home
are all unrecoverable in a way that a software bug normally is not.

**Interlocks are checked at launch and re-checked continuously in flight.** A
condition that becomes unsafe mid-sortie triggers a recall, not a warning.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from .missions import Mission, MissionPlanner, Waypoint


class NestState(str, Enum):
    OFFLINE = "offline"
    DOCKED_CHARGING = "docked_charging"
    DOCKED_READY = "docked_ready"
    PREFLIGHT = "preflight"
    HATCH_OPENING = "hatch_opening"
    LAUNCHING = "launching"
    ON_MISSION = "on_mission"
    RETURNING = "returning"
    LANDING = "landing"
    HATCH_CLOSING = "hatch_closing"
    FAULT = "fault"


@dataclass
class WeatherReading:
    """From the station's own weather head — never a forecast.

    Local truth matters: a met-office reading 8 km away does not know about
    the dust plume at this junction.
    """

    wind_mps: float = 0.0
    gust_mps: float = 0.0
    temperature_c: float = 30.0
    visibility_m: float = 10_000.0
    #: Particulate index; a shamal drives this up long before visibility drops.
    dust_index: float = 0.0
    precipitation: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass
class DroneTelemetry:
    battery_pct: float = 100.0
    battery_temp_c: float = 30.0
    altitude_m: float = 0.0
    lat: float = 0.0
    lon: float = 0.0
    gps_satellites: int = 18
    link_quality: float = 1.0  # 0..1
    airborne: bool = False
    timestamp: float = field(default_factory=time.time)


@dataclass
class NestConfig:
    #: Wind limits. Sustained is the launch gate; gusts are the recall gate.
    max_wind_mps: float = 10.0
    max_gust_mps: float = 13.0
    #: Ambient limits. The Qatar summer is the binding constraint on the whole
    #: drone concept — a LiPo pack cycled at 50 °C ages out in a season, so we
    #: refuse to launch hot and rely on the conditioned bay to bring the pack
    #: back into range before the next sortie.
    max_ambient_c: float = 48.0
    max_battery_temp_c: float = 45.0
    min_battery_temp_c: float = 5.0
    #: Dust/visibility gates.
    min_visibility_m: float = 1500.0
    max_dust_index: float = 0.65
    #: Battery gates.
    min_launch_battery_pct: float = 60.0
    recall_battery_pct: float = 35.0
    land_now_battery_pct: float = 20.0
    #: GNSS/link gates.
    min_gps_satellites: int = 10
    min_link_quality: float = 0.35
    #: Charging model.
    charge_rate_pct_per_min: float = 1.8
    #: Discharge in flight. ~3.3 %/min gives the ~30 min endurance a
    #: nest-compatible airframe actually has; this is what makes the duty
    #: cycle (and the recall thresholds) real rather than decorative.
    discharge_rate_pct_per_min: float = 3.3
    #: Extra drain while hovering on station versus cruising.
    hover_drain_multiplier: float = 1.15
    #: Mechanical timings (seconds) — used to sequence the state machine.
    hatch_travel_s: float = 12.0
    preflight_s: float = 20.0
    launch_s: float = 15.0
    landing_s: float = 45.0
    #: Refuse to fly at all outside these hours unless an operator overrides.
    allowed_hours: Optional[Tuple[int, int]] = None
    #: Master switch: no autonomous launches, operator-commanded only.
    autonomous_launch_enabled: bool = True


@dataclass
class InterlockStatus:
    ok: bool
    blockers: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


class DroneNest:
    """Nest controller. Drive it by calling :meth:`update` on a timer."""

    def __init__(self, config: Optional[NestConfig] = None,
                 planner: Optional[MissionPlanner] = None,
                 on_state_change: Optional[Callable[[NestState, NestState], None]] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg = config or NestConfig()
        self.planner = planner
        self.state = NestState.DOCKED_CHARGING
        self.weather = WeatherReading()
        self.telemetry = DroneTelemetry()
        self.mission: Optional[Mission] = None
        self.mission_started_at: Optional[float] = None
        self.fault_reason: str = ""
        self.history: List[Tuple[float, NestState, str]] = []
        self._on_state_change = on_state_change
        self._clock = clock
        self._state_entered = clock()
        self.sortie_count = 0
        self.recall_reason: str = ""

    # ------------------------------------------------------------------ #
    @property
    def elapsed_in_state(self) -> float:
        return self._clock() - self._state_entered

    @property
    def mission_elapsed(self) -> float:
        if self.mission_started_at is None:
            return 0.0
        return self._clock() - self.mission_started_at

    def _transition(self, new: NestState, note: str = "") -> None:
        if new is self.state:
            return
        old = self.state
        self.state = new
        self._state_entered = self._clock()
        self.history.append((self._clock(), new, note))
        if self._on_state_change:
            self._on_state_change(old, new)

    # ------------------------------------------------------------------ #
    # Interlocks
    # ------------------------------------------------------------------ #
    def launch_interlocks(self, now_hour: Optional[int] = None) -> InterlockStatus:
        cfg, w, t = self.cfg, self.weather, self.telemetry
        blockers: List[str] = []

        if self.state not in (NestState.DOCKED_READY, NestState.DOCKED_CHARGING):
            blockers.append(f"nest not docked (state={self.state.value})")
        if w.wind_mps > cfg.max_wind_mps:
            blockers.append(f"wind {w.wind_mps:.1f} m/s > {cfg.max_wind_mps}")
        if w.gust_mps > cfg.max_gust_mps:
            blockers.append(f"gusts {w.gust_mps:.1f} m/s > {cfg.max_gust_mps}")
        if w.temperature_c > cfg.max_ambient_c:
            blockers.append(f"ambient {w.temperature_c:.0f}°C > {cfg.max_ambient_c}")
        if w.visibility_m < cfg.min_visibility_m:
            blockers.append(f"visibility {w.visibility_m:.0f} m < {cfg.min_visibility_m}")
        if w.dust_index > cfg.max_dust_index:
            blockers.append(f"dust index {w.dust_index:.2f} > {cfg.max_dust_index}")
        if w.precipitation:
            blockers.append("precipitation")
        if t.battery_pct < cfg.min_launch_battery_pct:
            blockers.append(f"battery {t.battery_pct:.0f}% < {cfg.min_launch_battery_pct}%")
        if not (cfg.min_battery_temp_c <= t.battery_temp_c <= cfg.max_battery_temp_c):
            blockers.append(f"battery temp {t.battery_temp_c:.0f}°C out of range")
        if t.gps_satellites < cfg.min_gps_satellites:
            blockers.append(f"GNSS {t.gps_satellites} sats < {cfg.min_gps_satellites}")
        if t.link_quality < cfg.min_link_quality:
            blockers.append(f"link {t.link_quality:.2f} < {cfg.min_link_quality}")
        if cfg.allowed_hours and now_hour is not None:
            lo, hi = cfg.allowed_hours
            if not (lo <= now_hour < hi):
                blockers.append(f"outside permitted hours {lo:02d}-{hi:02d}")
        return InterlockStatus(ok=not blockers, blockers=blockers)

    def inflight_recall_reason(self) -> Optional[str]:
        """Conditions that force an immediate return, checked every update."""
        cfg, w, t = self.cfg, self.weather, self.telemetry
        if t.battery_pct <= cfg.land_now_battery_pct:
            return f"battery critical ({t.battery_pct:.0f}%)"
        if t.battery_pct <= cfg.recall_battery_pct:
            return f"battery low ({t.battery_pct:.0f}%)"
        if w.gust_mps > cfg.max_gust_mps:
            return f"gusts {w.gust_mps:.1f} m/s"
        if w.dust_index > cfg.max_dust_index:
            return f"dust index {w.dust_index:.2f}"
        if w.visibility_m < cfg.min_visibility_m:
            return f"visibility {w.visibility_m:.0f} m"
        if w.precipitation:
            return "precipitation"
        if t.link_quality < cfg.min_link_quality:
            return f"link degraded ({t.link_quality:.2f})"
        if self.mission and self.mission_elapsed > self.mission.max_duration_s:
            return "mission time cap reached"
        return None

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #
    def request_launch(self, mission: Mission, now_hour: Optional[int] = None,
                       operator_override: bool = False) -> Tuple[bool, str]:
        """Attempt to start a mission. Returns ``(accepted, reason)``."""
        if not self.cfg.autonomous_launch_enabled and not operator_override:
            return False, "autonomous launch disabled; operator command required"
        interlocks = self.launch_interlocks(now_hour)
        if not interlocks.ok:
            return False, "; ".join(interlocks.blockers)
        if self.planner is not None:
            feasible, why = self.planner.feasible(mission, self.telemetry.battery_pct)
            if not feasible:
                return False, why
        self.mission = mission
        self.recall_reason = ""
        self._transition(NestState.PREFLIGHT, f"mission {mission.mission_id}")
        return True, "accepted"

    def recall(self, reason: str = "operator recall") -> None:
        if self.state in (NestState.ON_MISSION, NestState.LAUNCHING):
            self.recall_reason = reason
            self._transition(NestState.RETURNING, reason)

    def abort_to_fault(self, reason: str) -> None:
        self.fault_reason = reason
        self._transition(NestState.FAULT, reason)

    def clear_fault(self) -> None:
        if self.state is NestState.FAULT:
            self.fault_reason = ""
            self._transition(NestState.DOCKED_CHARGING, "fault cleared")

    # ------------------------------------------------------------------ #
    # Tick
    # ------------------------------------------------------------------ #
    def update(self, dt_s: float = 1.0) -> NestState:
        """Advance the state machine. ``dt_s`` is wall time since last call."""
        cfg = self.cfg
        st = self.state

        # Airborne states drain the pack; this happens before the state logic
        # so the in-flight recall checks below see the current charge.
        if st in (NestState.LAUNCHING, NestState.ON_MISSION,
                  NestState.RETURNING, NestState.LANDING):
            rate = cfg.discharge_rate_pct_per_min
            if st is NestState.ON_MISSION:
                rate *= cfg.hover_drain_multiplier
            self.telemetry.battery_pct = max(
                0.0, self.telemetry.battery_pct - rate * (dt_s / 60.0))

        if st is NestState.DOCKED_CHARGING:
            self.telemetry.battery_pct = min(
                100.0, self.telemetry.battery_pct
                + cfg.charge_rate_pct_per_min * (dt_s / 60.0))
            if self.telemetry.battery_pct >= 99.0:
                self._transition(NestState.DOCKED_READY, "charged")

        elif st is NestState.PREFLIGHT:
            if self.elapsed_in_state >= cfg.preflight_s:
                self._transition(NestState.HATCH_OPENING, "preflight complete")

        elif st is NestState.HATCH_OPENING:
            if self.elapsed_in_state >= cfg.hatch_travel_s:
                self._transition(NestState.LAUNCHING, "hatch open")

        elif st is NestState.LAUNCHING:
            self.telemetry.airborne = True
            if self.elapsed_in_state >= cfg.launch_s:
                self.mission_started_at = self._clock()
                self.sortie_count += 1
                self._transition(NestState.ON_MISSION, "airborne")

        elif st is NestState.ON_MISSION:
            reason = self.inflight_recall_reason()
            if reason:
                self.recall(reason)
            elif self.mission and self.planner and \
                    self.mission_elapsed >= self.mission.estimated_duration_s(
                        self.planner.cruise_mps, self.planner.home):
                self.recall("mission complete")

        elif st is NestState.RETURNING:
            # Simplified: assume the return leg completes within the landing
            # window; a real controller tracks distance-to-home telemetry.
            if self.elapsed_in_state >= cfg.landing_s * 0.5:
                self._transition(NestState.LANDING, self.recall_reason or "returning")

        elif st is NestState.LANDING:
            if self.elapsed_in_state >= cfg.landing_s:
                self.telemetry.airborne = False
                self.telemetry.altitude_m = 0.0
                self.mission = None
                self.mission_started_at = None
                self._transition(NestState.HATCH_CLOSING, "landed")

        elif st is NestState.HATCH_CLOSING:
            if self.elapsed_in_state >= cfg.hatch_travel_s:
                self._transition(NestState.DOCKED_CHARGING, "secured")

        return self.state

    # ------------------------------------------------------------------ #
    def status(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "elapsed_in_state_s": round(self.elapsed_in_state, 1),
            "battery_pct": round(self.telemetry.battery_pct, 1),
            "airborne": self.telemetry.airborne,
            "sortie_count": self.sortie_count,
            "mission_id": self.mission.mission_id if self.mission else None,
            "mission_type": self.mission.type.value if self.mission else None,
            "recall_reason": self.recall_reason or None,
            "fault": self.fault_reason or None,
            "interlocks_ok": self.launch_interlocks().ok,
            "interlock_blockers": self.launch_interlocks().blockers,
        }
