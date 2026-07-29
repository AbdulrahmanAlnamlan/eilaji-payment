"""Drone nest interlocks, state machine, mission feasibility, tower sessions."""

import pytest

from speeddet.events import Event, EventBus, EventType, Severity
from speeddet.privacy import AuditLog
from speeddet.tower import (
    DroneNest,
    MissionPlanner,
    NestConfig,
    NestState,
    TowerConfig,
    TowerStation,
    Waypoint,
)
from speeddet.tower.missions import Mission, MissionType


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt
        return self.t


HOME = Waypoint(lat=25.2854, lon=51.5310, altitude_m=0.0)


def _nest(clock=None, **cfg):
    planner = MissionPlanner(home=HOME, cruise_mps=12.0, endurance_s=1500.0)
    return DroneNest(config=NestConfig(**cfg), planner=planner,
                     clock=clock or FakeClock())


def _mission():
    return Mission(type=MissionType.INCIDENT_RESPONSE,
                   waypoints=[Waypoint(lat=25.2860, lon=51.5315, hold_s=60.0)],
                   reason="test")


# --------------------------- interlocks -------------------------------- #
def test_launch_allowed_in_good_conditions():
    nest = _nest()
    nest.telemetry.battery_pct = 100.0
    assert nest.launch_interlocks().ok


@pytest.mark.parametrize("field,value,expect_word", [
    ("wind_mps", 15.0, "wind"),
    ("gust_mps", 20.0, "gust"),
    ("temperature_c", 52.0, "ambient"),
    ("visibility_m", 500.0, "visibility"),
    ("dust_index", 0.9, "dust"),
])
def test_weather_blocks_launch(field, value, expect_word):
    nest = _nest()
    setattr(nest.weather, field, value)
    status = nest.launch_interlocks()
    assert not status.ok
    assert any(expect_word in b for b in status.blockers)


def test_low_battery_blocks_launch():
    nest = _nest()
    nest.telemetry.battery_pct = 40.0
    status = nest.launch_interlocks()
    assert not status.ok
    assert any("battery" in b for b in status.blockers)


def test_hot_battery_blocks_launch():
    """The Qatar case: pack too hot to fly even when everything else is fine."""
    nest = _nest()
    nest.telemetry.battery_pct = 100.0
    nest.telemetry.battery_temp_c = 52.0
    assert not nest.launch_interlocks().ok


def test_poor_gnss_blocks_launch():
    nest = _nest()
    nest.telemetry.gps_satellites = 4
    assert not nest.launch_interlocks().ok


# ------------------------- state machine ------------------------------- #
def test_full_sortie_cycle():
    clock = FakeClock()
    nest = _nest(clock)
    nest.telemetry.battery_pct = 100.0
    accepted, why = nest.request_launch(_mission())
    assert accepted, why
    assert nest.state is NestState.PREFLIGHT

    seen = {nest.state}
    for _ in range(400):          # 400 s of simulated time
        clock.advance(1.0)
        seen.add(nest.update(1.0))
        if nest.state is NestState.DOCKED_CHARGING and nest.sortie_count:
            break

    for expected in (NestState.HATCH_OPENING, NestState.LAUNCHING,
                     NestState.ON_MISSION, NestState.RETURNING,
                     NestState.LANDING, NestState.HATCH_CLOSING):
        assert expected in seen, f"never entered {expected}"
    assert nest.sortie_count == 1
    assert nest.telemetry.airborne is False


def test_inflight_battery_drop_triggers_recall():
    clock = FakeClock()
    nest = _nest(clock)
    nest.telemetry.battery_pct = 100.0
    nest.request_launch(_mission())
    for _ in range(60):
        clock.advance(1.0)
        nest.update(1.0)
        if nest.state is NestState.ON_MISSION:
            break
    assert nest.state is NestState.ON_MISSION

    nest.telemetry.battery_pct = 25.0     # below recall threshold
    clock.advance(1.0)
    nest.update(1.0)
    assert nest.state is NestState.RETURNING
    assert "battery" in nest.recall_reason


def test_inflight_gust_triggers_recall():
    clock = FakeClock()
    nest = _nest(clock)
    nest.telemetry.battery_pct = 100.0
    nest.request_launch(_mission())
    for _ in range(60):
        clock.advance(1.0)
        nest.update(1.0)
        if nest.state is NestState.ON_MISSION:
            break
    nest.weather.gust_mps = 25.0
    clock.advance(1.0)
    nest.update(1.0)
    assert nest.state is NestState.RETURNING


def test_launch_refused_when_autonomy_disabled():
    nest = _nest(autonomous_launch_enabled=False)
    nest.telemetry.battery_pct = 100.0
    accepted, why = nest.request_launch(_mission())
    assert not accepted
    assert "operator" in why
    # An operator can still send it explicitly.
    accepted, _ = nest.request_launch(_mission(), operator_override=True)
    assert accepted


# --------------------------- missions ---------------------------------- #
def test_mission_beyond_endurance_is_refused():
    planner = MissionPlanner(home=HOME, cruise_mps=12.0, endurance_s=600.0)
    far = Mission(type=MissionType.OPERATOR_DIRECTED,
                  waypoints=[Waypoint(lat=25.60, lon=51.90)],  # tens of km
                  reason="too far")
    ok, why = planner.feasible(far, battery_pct=100.0)
    assert not ok
    assert "needs" in why


def test_mission_refused_on_low_battery_even_if_short():
    planner = MissionPlanner(home=HOME, cruise_mps=12.0, endurance_s=1500.0)
    near = planner.incident_response(lat=25.2860, lon=51.5315,
                                     event_id="e1", reason="crash")
    assert planner.feasible(near, battery_pct=100.0)[0]
    assert not planner.feasible(near, battery_pct=10.0)[0]


def test_waypoint_distance_is_metric():
    a = Waypoint(lat=25.2854, lon=51.5310)
    b = Waypoint(lat=25.2944, lon=51.5310)   # ~1 km north
    assert 950 < a.distance_to(b) < 1050


# ----------------------------- tower ----------------------------------- #
def test_cctv_session_is_audited_and_expires(tmp_path):
    clock = FakeClock()
    audit = AuditLog(tmp_path / "audit.jsonl")
    station = TowerStation(TowerConfig(cctv_session_seconds=300.0),
                           audit=audit, clock=clock)
    session = station.open_cctv_session("operator_a", "ptz-1", "incident review")
    assert session.active
    assert any(e["action"] == "cctv_session_open" for e in audit.entries())

    clock.advance(301.0)
    expired = station.expire_sessions()
    assert session.session_id in expired
    assert not station.sessions[session.session_id].active
    assert audit.verify()


def test_operator_access_raises_an_event():
    station = TowerStation(TowerConfig())
    station.open_cctv_session("operator_a", "ptz-1", "routine check")
    assert len(station.bus.events_of(EventType.OPERATOR_ACCESS)) == 1


def test_subsystem_failure_raises_event():
    station = TowerStation(TowerConfig())
    station.report_health("alpr_camera", True)
    assert not station.bus.events_of(EventType.SYSTEM_HEALTH)
    station.report_health("alpr_camera", False, "no frames for 30 s")
    assert len(station.bus.events_of(EventType.SYSTEM_HEALTH)) == 1
    assert not station.healthy()


def test_drone_auto_response_off_by_default():
    """A tower must not start flying by itself until deliberately enabled."""
    clock = FakeClock()
    nest = _nest(clock)
    nest.telemetry.battery_pct = 100.0
    planner = MissionPlanner(home=HOME)
    station = TowerStation(TowerConfig(), nest=nest, planner=planner, clock=clock)
    station.bus.publish(Event(type=EventType.COLLISION, severity=Severity.CRITICAL,
                              timestamp=1.0, world_xy=(5.0, 30.0)))
    assert nest.state is NestState.DOCKED_CHARGING
    assert station.auto_missions == []


def test_drone_auto_response_launches_when_enabled():
    clock = FakeClock()
    nest = _nest(clock)
    nest.telemetry.battery_pct = 100.0
    planner = MissionPlanner(home=HOME)
    station = TowerStation(
        TowerConfig(drone_auto_response_enabled=True, lat=HOME.lat, lon=HOME.lon),
        nest=nest, planner=planner, clock=clock)
    station.bus.publish(Event(type=EventType.COLLISION, severity=Severity.CRITICAL,
                              timestamp=1.0, world_xy=(5.0, 30.0)))
    assert nest.state is NestState.PREFLIGHT
    assert len(station.auto_missions) == 1
    assert station.auto_missions[0].type is MissionType.INCIDENT_RESPONSE


def test_speeding_does_not_launch_the_drone():
    clock = FakeClock()
    nest = _nest(clock)
    nest.telemetry.battery_pct = 100.0
    station = TowerStation(TowerConfig(drone_auto_response_enabled=True),
                           nest=nest, planner=MissionPlanner(home=HOME), clock=clock)
    station.bus.publish(Event(type=EventType.SPEEDING, severity=Severity.MEDIUM,
                              timestamp=1.0, world_xy=(5.0, 30.0)))
    assert nest.state is NestState.DOCKED_CHARGING
