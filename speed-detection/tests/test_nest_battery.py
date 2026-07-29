"""Battery model: drain in flight, recharge docked, and the duty cycle."""

from speeddet.tower import DroneNest, MissionPlanner, NestConfig, NestState, Waypoint
from speeddet.tower.missions import Mission, MissionType

HOME = Waypoint(lat=25.2854, lon=51.5310, altitude_m=0.0)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt
        return self.t


def _nest(clock, **cfg):
    return DroneNest(config=NestConfig(**cfg),
                     planner=MissionPlanner(home=HOME, endurance_s=1800.0),
                     clock=clock)


def _long_mission():
    """The longest sortie the planner will actually accept.

    The planner refuses anything beyond usable endurance (70% of 1800 s here),
    so an 1100 s hold is near the limit but legal — long enough that the
    battery, not the mission clock, ends the flight.
    """
    return Mission(type=MissionType.OPERATOR_DIRECTED,
                   waypoints=[Waypoint(lat=25.2870, lon=51.5330, hold_s=1100.0)],
                   reason="endurance test", max_duration_s=3600.0)


def test_planner_refuses_a_sortie_it_cannot_bring_home():
    planner = MissionPlanner(home=HOME, endurance_s=1800.0)
    impossible = Mission(type=MissionType.OPERATOR_DIRECTED,
                         waypoints=[Waypoint(lat=25.2870, lon=51.5330,
                                             hold_s=3000.0)],
                         reason="too long", max_duration_s=3600.0)
    ok, why = planner.feasible(impossible, battery_pct=100.0)
    assert not ok and "needs" in why
    assert planner.feasible(_long_mission(), battery_pct=100.0)[0]


def test_battery_drains_in_flight():
    clock = FakeClock()
    nest = _nest(clock)
    nest.telemetry.battery_pct = 100.0
    nest.request_launch(_long_mission(), operator_override=True)
    for _ in range(120):
        clock.advance(1.0)
        nest.update(1.0)
        if nest.state is NestState.ON_MISSION:
            break
    start = nest.telemetry.battery_pct
    for _ in range(60):
        clock.advance(1.0)
        nest.update(1.0)
    assert nest.telemetry.battery_pct < start - 1.0, "pack must drain in flight"


def test_battery_drain_forces_recall_without_operator_action():
    """The safety property: a long sortie ends itself before the pack does."""
    clock = FakeClock()
    nest = _nest(clock)
    nest.telemetry.battery_pct = 100.0
    nest.request_launch(_long_mission(), operator_override=True)
    recalled_at = None
    for _ in range(3000):
        clock.advance(1.0)
        nest.update(1.0)
        if nest.state is NestState.RETURNING and recalled_at is None:
            recalled_at = nest.telemetry.battery_pct
            break
    assert recalled_at is not None, "drone never recalled itself"
    assert recalled_at >= nest.cfg.land_now_battery_pct
    assert "battery" in nest.recall_reason


def test_recharges_while_docked():
    clock = FakeClock()
    nest = _nest(clock)
    nest.telemetry.battery_pct = 50.0
    for _ in range(600):
        clock.advance(1.0)
        nest.update(1.0)
    assert nest.telemetry.battery_pct > 60.0


def test_duty_cycle_is_not_continuous_coverage():
    """One drone cannot be airborne continuously — sizing sanity check."""
    clock = FakeClock()
    nest = _nest(clock)
    nest.telemetry.battery_pct = 100.0
    airborne = docked = 0
    launched_once = False
    for _ in range(7200):  # two simulated hours
        clock.advance(1.0)
        state = nest.update(1.0)
        if state in (NestState.DOCKED_READY, NestState.DOCKED_CHARGING):
            docked += 1
            if not launched_once or nest.sortie_count < 3:
                ok, _ = nest.request_launch(_long_mission(), operator_override=True)
                launched_once = launched_once or ok
        elif state is NestState.ON_MISSION:
            airborne += 1
    assert launched_once
    fraction = airborne / (airborne + docked)
    assert 0.05 < fraction < 0.75, f"airborne fraction {fraction:.2f} implausible"
