"""The tower station: subsystem health, CCTV sessions, and event→drone routing.

This is the object the command centre talks to. It owns:

* the **event bus** every analyzer publishes onto;
* **subsystem health** (cameras, radar, compute, link, nest, power);
* **CCTV sessions** — an operator taking live control of a camera, which is a
  privileged action and therefore always audited and always time-boxed;
* **auto-response** — routing a CRITICAL event to a drone sortie, when the
  site's rules allow it.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..events import Event, EventBus, EventType, Severity
from ..privacy import AuditLog, PrivacyConfig
from .missions import Mission, MissionPlanner, MissionType
from .nest import DroneNest, NestState


@dataclass
class SubsystemHealth:
    name: str
    ok: bool = True
    detail: str = ""
    last_update: float = field(default_factory=time.time)
    #: Rolling metric, e.g. processing FPS or link RSSI.
    metric: Optional[float] = None

    def stale(self, max_age_s: float = 60.0, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        return (now - self.last_update) > max_age_s


@dataclass
class CctvSession:
    """A live-view session held by a named operator.

    Time-boxed by design. An always-open live feed is how a traffic system
    quietly becomes a surveillance system; requiring renewal every few minutes
    creates a decision point and an audit entry each time.
    """

    session_id: str
    operator: str
    camera: str
    justification: str
    opened_at: float
    expires_at: float
    closed_at: Optional[float] = None
    #: Time source, injected by the station so tests (and replay) are not
    #: tied to the wall clock.
    clock: Callable[[], float] = time.time

    def active_at(self, now: float) -> bool:
        return self.closed_at is None and now < self.expires_at

    @property
    def active(self) -> bool:
        return self.active_at(self.clock())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id, "operator": self.operator,
            "camera": self.camera, "justification": self.justification,
            "opened_at": self.opened_at, "expires_at": self.expires_at,
            "closed_at": self.closed_at, "active": self.active,
        }


@dataclass
class TowerConfig:
    tower_id: str = "tower-000"
    site_name: str = ""
    lat: float = 0.0
    lon: float = 0.0
    #: Auto-launch the drone for these event types (subject to nest interlocks
    #: and the site's flight permissions).
    drone_trigger_types: Tuple[EventType, ...] = (
        EventType.COLLISION,
        EventType.WRONG_WAY,
        EventType.PEDESTRIAN_ON_ROADWAY,
    )
    drone_auto_response_enabled: bool = False
    #: Maximum length of a single CCTV live session before renewal.
    cctv_session_seconds: float = 600.0
    #: Heartbeat interval; a missed heartbeat is itself an event.
    heartbeat_seconds: float = 60.0


class TowerStation:
    """Orchestrates one physical tower."""

    def __init__(self, config: Optional[TowerConfig] = None,
                 bus: Optional[EventBus] = None,
                 nest: Optional[DroneNest] = None,
                 planner: Optional[MissionPlanner] = None,
                 audit: Optional[AuditLog] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.cfg = config or TowerConfig()
        self.bus = bus or EventBus()
        self.nest = nest
        self.planner = planner
        self.audit = audit
        self._clock = clock
        self.subsystems: Dict[str, SubsystemHealth] = {}
        self.sessions: Dict[str, CctvSession] = {}
        self.last_heartbeat: float = clock()
        self.auto_missions: List[Mission] = []

        # Route qualifying events to the drone.
        self.bus.subscribe(self._on_event)

    # ------------------------------------------------------------------ #
    # Health
    # ------------------------------------------------------------------ #
    def report_health(self, name: str, ok: bool, detail: str = "",
                      metric: Optional[float] = None) -> None:
        prev = self.subsystems.get(name)
        self.subsystems[name] = SubsystemHealth(
            name=name, ok=ok, detail=detail, metric=metric,
            last_update=self._clock())
        if prev is not None and prev.ok and not ok:
            self.bus.publish(Event(
                type=EventType.SYSTEM_HEALTH,
                severity=Severity.HIGH,
                timestamp=self._clock(),
                tower_id=self.cfg.tower_id,
                message=f"Subsystem '{name}' failed: {detail}",
                metadata={"subsystem": name, "detail": detail},
            ))

    def healthy(self, max_age_s: float = 120.0) -> bool:
        now = self._clock()
        return all(s.ok and not s.stale(max_age_s, now)
                   for s in self.subsystems.values())

    def heartbeat(self) -> None:
        self.last_heartbeat = self._clock()

    def status(self) -> Dict[str, Any]:
        return {
            "tower_id": self.cfg.tower_id,
            "site": self.cfg.site_name,
            "position": {"lat": self.cfg.lat, "lon": self.cfg.lon},
            "healthy": self.healthy(),
            "subsystems": {n: {"ok": s.ok, "detail": s.detail, "metric": s.metric}
                           for n, s in self.subsystems.items()},
            "active_cctv_sessions": [s.to_dict() for s in self.sessions.values()
                                     if s.active],
            "nest": self.nest.status() if self.nest else None,
            "events_published": len(self.bus.published),
            "last_heartbeat": self.last_heartbeat,
        }

    # ------------------------------------------------------------------ #
    # CCTV
    # ------------------------------------------------------------------ #
    def open_cctv_session(self, operator: str, camera: str,
                          justification: str) -> CctvSession:
        """Grant an operator live view. Always audited, always expiring."""
        now = self._clock()
        session = CctvSession(
            session_id=uuid.uuid4().hex[:12],
            operator=operator, camera=camera, justification=justification,
            opened_at=now, expires_at=now + self.cfg.cctv_session_seconds,
            clock=self._clock,
        )
        self.sessions[session.session_id] = session
        if self.audit:
            self.audit.record("cctv_session_open", operator, {
                "camera": camera, "justification": justification,
                "session_id": session.session_id,
                "expires_at": session.expires_at,
            })
        self.bus.publish(Event(
            type=EventType.OPERATOR_ACCESS,
            severity=Severity.INFO,
            timestamp=now,
            tower_id=self.cfg.tower_id,
            message=f"Operator {operator} opened live view on {camera}",
            metadata={"session_id": session.session_id,
                      "justification": justification},
        ))
        return session

    def close_cctv_session(self, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        if session is None or session.closed_at is not None:
            return False
        session.closed_at = self._clock()
        if self.audit:
            self.audit.record("cctv_session_close", session.operator,
                              {"session_id": session_id,
                               "duration_s": session.closed_at - session.opened_at})
        return True

    def expire_sessions(self) -> List[str]:
        """Close anything past its expiry; returns the ids closed."""
        expired = [sid for sid, s in self.sessions.items()
                   if s.closed_at is None and self._clock() >= s.expires_at]
        for sid in expired:
            self.sessions[sid].closed_at = self._clock()
            if self.audit:
                self.audit.record("cctv_session_expired", self.sessions[sid].operator,
                                  {"session_id": sid})
        return expired

    # ------------------------------------------------------------------ #
    # Event routing / auto-response
    # ------------------------------------------------------------------ #
    def _on_event(self, event: Event) -> None:
        if not self.cfg.drone_auto_response_enabled:
            return
        if self.nest is None or self.planner is None:
            return
        if event.type not in self.cfg.drone_trigger_types:
            return
        if self.nest.state not in (NestState.DOCKED_READY, NestState.DOCKED_CHARGING):
            return
        lat, lon = self._event_latlon(event)
        mission = self.planner.incident_response(
            lat=lat, lon=lon, event_id=event.event_id,
            reason=f"auto-response to {event.type.value}",
        )
        accepted, why = self.nest.request_launch(mission)
        if self.audit:
            self.audit.record("drone_auto_launch", "system", {
                "event_id": event.event_id, "event_type": event.type.value,
                "accepted": accepted, "reason": why,
                "mission_id": mission.mission_id,
            })
        self.bus.publish(Event(
            type=EventType.DRONE_STATUS,
            severity=Severity.INFO if accepted else Severity.LOW,
            timestamp=event.timestamp,
            tower_id=self.cfg.tower_id,
            message=(f"Drone sortie {'launched' if accepted else 'refused'} for "
                     f"{event.type.value}: {why}"),
            metadata={"mission_id": mission.mission_id, "accepted": accepted,
                      "triggering_event": event.event_id},
        ))
        if accepted:
            self.auto_missions.append(mission)

    def _event_latlon(self, event: Event) -> Tuple[float, float]:
        """Convert an event's world offset (metres) to lat/lon near the tower.

        The calibration's world frame is local metres; this maps it onto the
        globe using a flat-earth approximation, which is exact enough over the
        tens of metres a tower observes.
        """
        if not event.world_xy:
            return (self.cfg.lat, self.cfg.lon)
        import math

        dx, dy = event.world_xy
        dlat = dy / 111_320.0
        dlon = dx / (111_320.0 * max(0.1, math.cos(math.radians(self.cfg.lat))))
        return (self.cfg.lat + dlat, self.cfg.lon + dlon)

    # ------------------------------------------------------------------ #
    def tick(self, dt_s: float = 1.0) -> None:
        """Periodic housekeeping: nest state machine, session expiry, heartbeat."""
        if self.nest is not None:
            self.nest.update(dt_s)
        self.expire_sessions()
        if (self._clock() - self.last_heartbeat) > self.cfg.heartbeat_seconds:
            self.heartbeat()
