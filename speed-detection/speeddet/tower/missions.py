"""Drone mission definitions and planning.

A mission is a bounded, reviewable unit of flight: why it launched, where it
went, and when it must be home. Bounding matters — an unbounded "monitor the
area" order is neither safe (battery) nor accountable (scope).
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class MissionType(str, Enum):
    #: Routine loop over a pre-approved corridor at a set time.
    SCHEDULED_PATROL = "scheduled_patrol"
    #: Auto-launched by a CRITICAL event (collision, wrong-way) to document.
    INCIDENT_RESPONSE = "incident_response"
    #: A human operator sent it to specific coordinates.
    OPERATOR_DIRECTED = "operator_directed"
    #: Fly the airframe to verify health without a surveillance purpose.
    MAINTENANCE_CHECK = "maintenance_check"


@dataclass
class Waypoint:
    """A point the drone must reach. ``lat``/``lon`` in WGS84 degrees."""

    lat: float
    lon: float
    altitude_m: float = 40.0
    #: Seconds to hold station here (0 = pass through).
    hold_s: float = 0.0
    #: Gimbal pitch in degrees (-90 = straight down).
    gimbal_pitch_deg: float = -45.0
    label: str = ""

    def distance_to(self, other: "Waypoint") -> float:
        """Great-circle distance in metres (equirectangular approximation)."""
        r = 6_371_000.0
        lat1, lat2 = math.radians(self.lat), math.radians(other.lat)
        dlat = lat2 - lat1
        dlon = math.radians(other.lon - self.lon)
        x = dlon * math.cos(0.5 * (lat1 + lat2))
        return float(r * math.hypot(dlat, x))


@dataclass
class Mission:
    type: MissionType
    waypoints: List[Waypoint]
    mission_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    #: Why this flight exists — recorded for the audit trail.
    reason: str = ""
    authorised_by: str = "system"
    #: Hard limit; the nest recalls the drone at this point regardless.
    max_duration_s: float = 900.0
    triggering_event_id: Optional[str] = None
    priority: int = 50  # higher wins when two missions compete
    metadata: Dict[str, Any] = field(default_factory=dict)

    def path_length_m(self, home: Optional[Waypoint] = None) -> float:
        pts = ([home] if home else []) + list(self.waypoints) + ([home] if home else [])
        return sum(pts[i].distance_to(pts[i + 1]) for i in range(len(pts) - 1))

    def estimated_duration_s(self, cruise_mps: float = 12.0,
                             home: Optional[Waypoint] = None) -> float:
        travel = self.path_length_m(home) / max(cruise_mps, 0.1)
        holds = sum(w.hold_s for w in self.waypoints)
        return travel + holds + 30.0  # launch + land overhead


class MissionPlanner:
    """Builds missions and checks them against the airframe's real endurance.

    The endurance check is the part that matters operationally: a mission that
    cannot get home on the remaining battery must be rejected *before* launch,
    not discovered at the far waypoint.
    """

    def __init__(self, home: Waypoint, cruise_mps: float = 12.0,
                 endurance_s: float = 1500.0, reserve_fraction: float = 0.30) -> None:
        self.home = home
        self.cruise_mps = cruise_mps
        self.endurance_s = endurance_s
        self.reserve_fraction = reserve_fraction

    @property
    def usable_endurance_s(self) -> float:
        return self.endurance_s * (1.0 - self.reserve_fraction)

    def feasible(self, mission: Mission, battery_pct: float = 100.0) -> Tuple[bool, str]:
        available = self.usable_endurance_s * (battery_pct / 100.0)
        needed = mission.estimated_duration_s(self.cruise_mps, self.home)
        if needed > available:
            return False, (f"mission needs {needed:.0f}s, only {available:.0f}s "
                           f"available at {battery_pct:.0f}% battery")
        if needed > mission.max_duration_s:
            return False, (f"mission needs {needed:.0f}s, exceeds its own cap "
                           f"of {mission.max_duration_s:.0f}s")
        return True, "ok"

    def incident_response(self, lat: float, lon: float, event_id: str,
                          reason: str, altitude_m: float = 45.0,
                          hold_s: float = 120.0) -> Mission:
        """One waypoint over the incident, looking down, holding to document."""
        return Mission(
            type=MissionType.INCIDENT_RESPONSE,
            waypoints=[Waypoint(lat=lat, lon=lon, altitude_m=altitude_m,
                                hold_s=hold_s, gimbal_pitch_deg=-75.0,
                                label="incident")],
            reason=reason,
            triggering_event_id=event_id,
            priority=90,
            max_duration_s=600.0,
        )

    def patrol(self, corridor: List[Tuple[float, float]], altitude_m: float = 50.0,
               reason: str = "scheduled corridor patrol") -> Mission:
        return Mission(
            type=MissionType.SCHEDULED_PATROL,
            waypoints=[Waypoint(lat=la, lon=lo, altitude_m=altitude_m,
                                gimbal_pitch_deg=-45.0, label=f"wp{i}")
                       for i, (la, lo) in enumerate(corridor)],
            reason=reason,
            priority=30,
        )
