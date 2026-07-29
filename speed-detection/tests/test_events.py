"""Event model, bus dedupe, and dispatch."""

import json

import pytest

from speeddet.events import (
    ConsoleDispatcher,
    Event,
    EventBus,
    EventType,
    Evidence,
    JsonlDispatcher,
    Severity,
)


def _ev(t=0.0, etype=EventType.SPEEDING, tracks=(1,), sev=Severity.MEDIUM):
    return Event(type=etype, severity=sev, timestamp=t, track_ids=list(tracks))


def test_review_and_immediate_flags():
    assert _ev(etype=EventType.NO_SEATBELT).requires_review
    assert _ev(etype=EventType.PHONE_USE).requires_review
    assert _ev(etype=EventType.LITTERING).requires_review
    # Measurement-class events are not review-gated by type.
    assert not _ev(etype=EventType.SPEEDING).requires_review
    # Life-safety events dispatch immediately regardless of severity.
    assert _ev(etype=EventType.COLLISION, sev=Severity.LOW).immediate
    assert _ev(etype=EventType.WRONG_WAY, sev=Severity.LOW).immediate
    assert not _ev(etype=EventType.SPEEDING, sev=Severity.LOW).immediate


def test_serialises_round_trip():
    e = _ev()
    e.evidence = Evidence(frame_index=10, timestamp=0.4, clip_path="/x.mp4")
    d = json.loads(e.to_json())
    assert d["type"] == "speeding"
    assert d["severity_name"] == "MEDIUM"
    assert d["evidence"]["clip_path"] == "/x.mp4"
    assert d["requires_review"] is False


def test_bus_dedupes_same_type_and_track():
    bus = EventBus(cooldowns={EventType.SPEEDING: 5.0})
    assert bus.publish(_ev(t=0.0)) is True
    assert bus.publish(_ev(t=1.0)) is False      # inside cooldown
    assert bus.publish(_ev(t=6.0)) is True       # cooldown elapsed
    assert len(bus.published) == 2
    assert bus.suppressed_count["speeding"] == 1


def test_bus_does_not_dedupe_across_tracks():
    bus = EventBus(cooldowns={EventType.SPEEDING: 5.0})
    assert bus.publish(_ev(t=0.0, tracks=(1,))) is True
    assert bus.publish(_ev(t=0.1, tracks=(2,))) is True
    assert len(bus.published) == 2


def test_zero_cooldown_disables_suppression():
    bus = EventBus(cooldowns={EventType.COLLISION: 0.0})
    for i in range(3):
        assert bus.publish(_ev(t=i * 0.1, etype=EventType.COLLISION)) is True
    assert len(bus.published) == 3


def test_handler_predicate_filters():
    bus = EventBus(cooldowns={EventType.SPEEDING: 0.0})
    seen = []
    bus.subscribe(lambda e: seen.append(e),
                  predicate=lambda e: e.severity >= Severity.HIGH)
    bus.publish(_ev(t=0.0, sev=Severity.LOW))
    bus.publish(_ev(t=1.0, sev=Severity.HIGH))
    assert len(seen) == 1
    assert seen[0].severity is Severity.HIGH


def test_broken_handler_does_not_break_pipeline():
    bus = EventBus(cooldowns={EventType.SPEEDING: 0.0})
    good = []

    def explode(event):
        raise RuntimeError("dispatcher is down")

    bus.subscribe(explode)
    bus.subscribe(lambda e: good.append(e))
    assert bus.publish(_ev()) is True
    assert len(good) == 1  # the healthy dispatcher still received it


def test_jsonl_dispatcher_writes_lines(tmp_path):
    path = tmp_path / "events.jsonl"
    bus = EventBus(cooldowns={EventType.SPEEDING: 0.0})
    bus.subscribe(JsonlDispatcher(path))
    bus.publish(_ev(t=0.0))
    bus.publish(_ev(t=1.0))
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["type"] == "speeding"


def test_events_of_filters_by_type():
    bus = EventBus(cooldowns={EventType.SPEEDING: 0.0, EventType.COLLISION: 0.0})
    bus.publish(_ev(t=0.0, etype=EventType.SPEEDING))
    bus.publish(_ev(t=0.1, etype=EventType.COLLISION))
    assert len(bus.events_of(EventType.COLLISION)) == 1
    assert len(bus.events_of(EventType.SPEEDING)) == 1
