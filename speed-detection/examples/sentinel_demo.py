"""End-to-end Sentinel tower demo: incident -> event -> drone -> audit.

Runs the whole stack on a scripted collision and prints what the command
centre would see:

1. the tower boots, subsystems report health;
2. an operator opens a live CCTV session (audited, time-boxed);
3. footage is processed — speed, plates, occupant analytics, anomaly AI;
4. the collision fires a CRITICAL event;
5. the drone auto-launches to the incident coordinates, flies the sortie and
   returns to charge, with every interlock enforced;
6. the audit log is verified and the retention clock is shown.

Run:
    python examples/sentinel_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from speeddet.analytics import KinematicAnalyzer, LitterAnalyzer, OccupantAnalyzer
from speeddet.analytics.occupant import CueOccupantClassifier
from speeddet.calibration import Calibrator
from speeddet.detection import ColorBlobDetector
from speeddet.events import ConsoleDispatcher, EventBus, EventType, JsonlDispatcher
from speeddet.pipeline import PipelineConfig, SpeedPipeline
from speeddet.plates import QatarPlateReader
from speeddet.privacy import AuditLog, PrivacyConfig, RetentionPolicy
from speeddet.tower import (
    DroneNest,
    MissionPlanner,
    NestConfig,
    NestState,
    TowerConfig,
    TowerStation,
    Waypoint,
)
from speeddet.tools.scenarios import build_scenario

OUT = Path("demo/sentinel")
# Somewhere on Al Rayyan Road, for the sake of having real coordinates.
HOME = Waypoint(lat=25.2854, lon=51.4310, altitude_m=0.0)


class SimClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt
        return self.t


def rule(title: str) -> None:
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    clock = SimClock()

    # ---------------------------------------------------------------- #
    rule("1. TOWER BOOT")
    audit = AuditLog(OUT / "audit.jsonl")
    planner = MissionPlanner(home=HOME, cruise_mps=12.0, endurance_s=1500.0)
    nest = DroneNest(config=NestConfig(), planner=planner, clock=clock)
    nest.telemetry.battery_pct = 100.0
    nest.weather.temperature_c = 41.0      # a warm Doha morning
    nest.weather.wind_mps = 4.0

    bus = EventBus()
    station = TowerStation(
        TowerConfig(tower_id="QA-TWR-014", site_name="Al Rayyan Rd @ Exit 8",
                    lat=HOME.lat, lon=HOME.lon,
                    drone_auto_response_enabled=True),
        bus=bus, nest=nest, planner=planner, audit=audit, clock=clock,
    )
    bus.subscribe(ConsoleDispatcher())
    bus.subscribe(JsonlDispatcher(OUT / "events.jsonl"))

    for name in ("wide_camera", "alpr_camera", "occupant_camera",
                 "doppler_radar", "edge_compute", "5g_link", "drone_nest"):
        station.report_health(name, True, "nominal")
    print(f"tower {station.cfg.tower_id} @ {station.cfg.site_name}")
    print(f"subsystems healthy: {station.healthy()}")
    print(f"nest: {nest.state.value}, battery {nest.telemetry.battery_pct:.0f}%, "
          f"interlocks_ok={nest.launch_interlocks().ok}")

    # ---------------------------------------------------------------- #
    rule("2. OPERATOR OPENS A LIVE CCTV SESSION")
    session = station.open_cctv_session(
        operator="ops.alnamlan", camera="ptz-1",
        justification="morning traffic check, Exit 8 merge")
    print(f"session {session.session_id} open, expires in "
          f"{session.expires_at - session.opened_at:.0f}s — and audited")

    # ---------------------------------------------------------------- #
    rule("3. PROCESSING FOOTAGE (scripted rear-end collision)")
    info = build_scenario("collision", str(OUT / "collision.mp4"))
    pipeline = SpeedPipeline(
        detector=ColorBlobDetector(small_object_area_px=800),
        calibrator=Calibrator.load(info["calibration"]),
        config=PipelineConfig(output_dir=str(OUT), tower_id=station.cfg.tower_id,
                              annotated_video_name="annotated.mp4",
                              clip_seconds=8.0),
        plate_reader=QatarPlateReader(),
        analyzers=[KinematicAnalyzer(), LitterAnalyzer(),
                   OccupantAnalyzer(CueOccupantClassifier())],
        bus=bus,
    )
    print("--- live event stream to command centre ---")
    result = pipeline.run_video(info["video"])

    # ---------------------------------------------------------------- #
    rule("4. INCIDENT SUMMARY")
    collisions = bus.events_of(EventType.COLLISION)
    speeders = bus.events_of(EventType.SPEEDING)
    print(f"frames processed : {result.frames_processed}")
    print(f"speeding events  : {len(speeders)}")
    print(f"collisions       : {len(collisions)}")
    for c in collisions:
        print(f"  ! t={c.timestamp:.2f}s conf={c.confidence:.2f} "
              f"tracks={c.track_ids}")
        print(f"    signals: {c.metadata.get('signals')}")
        print(f"    world  : {c.world_xy}  -> lat/lon "
              f"{station._event_latlon(c)}")
    print(f"evidence clips   : {OUT / 'clips'}")

    # ---------------------------------------------------------------- #
    rule("5. DRONE AUTO-RESPONSE")
    if not station.auto_missions:
        print("no sortie launched (check interlocks / auto-response flag)")
    else:
        m = station.auto_missions[0]
        print(f"mission {m.mission_id} [{m.type.value}] — {m.reason}")
        wp = m.waypoints[0]
        print(f"  waypoint  : {wp.lat:.5f}, {wp.lon:.5f} @ {wp.altitude_m} m, "
              f"hold {wp.hold_s:.0f}s, gimbal {wp.gimbal_pitch_deg}°")
        print(f"  distance  : {m.path_length_m(HOME):.0f} m round trip")
        print(f"  estimated : {m.estimated_duration_s(12.0, HOME):.0f}s "
              f"(cap {m.max_duration_s:.0f}s)")
        print("\n  flight log:")
        last = None
        for _ in range(420):
            clock.advance(1.0)
            station.tick(1.0)
            if nest.state is not last:
                print(f"    t+{clock.t:5.0f}s  {nest.state.value:<16} "
                      f"battery {nest.telemetry.battery_pct:5.1f}%")
                last = nest.state
            if nest.state is NestState.DOCKED_CHARGING and nest.sortie_count:
                break
        print(f"  sorties flown: {nest.sortie_count}, "
              f"drone docked and charging")

    # ---------------------------------------------------------------- #
    rule("6. INTERLOCK CHECK — a shamal rolls in")
    nest.weather.dust_index = 0.85
    nest.weather.visibility_m = 900.0
    nest.weather.gust_mps = 17.0
    status = nest.launch_interlocks()
    print(f"launch permitted: {status.ok}")
    for blocker in status.blockers:
        print(f"  blocked: {blocker}")

    # ---------------------------------------------------------------- #
    rule("7. GOVERNANCE")
    station.close_cctv_session(session.session_id)
    print(f"audit entries      : {len(audit.entries())}")
    print(f"audit chain valid  : {audit.verify()}")
    for entry in audit.entries():
        print(f"  {entry['action']:<24} by {entry['actor']}")
    cfg = PrivacyConfig()
    print(f"\nretention          : {cfg.retention_days_unactioned}d unactioned, "
          f"{cfg.retention_days_actioned}d actioned, "
          f"{cfg.retention_days_raw}d raw video")
    print(f"redaction default  : {cfg.redaction.value}")
    removed = RetentionPolicy(cfg, audit).sweep(OUT / "clips")
    print(f"retention sweep    : {len(removed)} expired file(s) removed")

    rule("DONE")
    print(f"events   : {OUT / 'events.jsonl'}")
    print(f"annotated: {result.annotated_video}")
    print(f"audit    : {OUT / 'audit.jsonl'}")


if __name__ == "__main__":
    main()
