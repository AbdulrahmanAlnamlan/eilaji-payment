"""Event model, bus and dispatchers — the spine of the Sentinel tower.

Every subsystem (speed, occupant analytics, kinematic anomaly detection,
littering, drone, health monitoring) emits :class:`Event` objects onto an
:class:`EventBus`. Dispatchers subscribe and forward them: to disk, to the
command centre over HTTP, to an operator console.

Design rules:

* **One event type per real-world thing.** Operators triage by type+severity.
* **Dedupe at the source.** A speeding car is in frame for seconds; it must
  produce one event, not 200. The bus enforces a per-(type, track) cooldown.
* **Evidence is attached, not implied.** Each event carries the frame index /
  timestamp needed to cut a clip from the ring buffer.
* **Nothing auto-issues a citation.** Events carry ``requires_review``;
  measurement-class events (speed) can be pre-validated, but classifier-class
  events (seatbelt, phone) are proposals for a human, never verdicts.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


class EventType(str, Enum):
    # --- measurement-class traffic violations (instrument-grade) ---------- #
    SPEEDING = "speeding"
    RED_LIGHT = "red_light"
    WRONG_WAY = "wrong_way"
    ILLEGAL_STOP = "illegal_stop"

    # --- classifier-class violations (proposals; need human review) ------- #
    NO_SEATBELT = "no_seatbelt"
    PHONE_USE = "phone_use"
    LITTERING = "littering"
    NO_HELMET = "no_helmet"

    # --- safety / anomaly (the "something is wrong" class) ---------------- #
    COLLISION = "collision"
    NEAR_MISS = "near_miss"
    STOPPED_VEHICLE = "stopped_vehicle"
    ERRATIC_DRIVING = "erratic_driving"
    PEDESTRIAN_ON_ROADWAY = "pedestrian_on_roadway"
    CONGESTION = "congestion"
    DEBRIS_ON_ROADWAY = "debris_on_roadway"
    ALTERCATION = "altercation"
    CROWD_ANOMALY = "crowd_anomaly"
    ANOMALY_UNCLASSIFIED = "anomaly_unclassified"

    # --- system / operations ---------------------------------------------- #
    SYSTEM_HEALTH = "system_health"
    DRONE_STATUS = "drone_status"
    OPERATOR_ACCESS = "operator_access"


class Severity(IntEnum):
    INFO = 10
    LOW = 20
    MEDIUM = 30
    HIGH = 40
    CRITICAL = 50


#: Events a human must confirm before any enforcement action. Classifier-class
#: outputs and anything life-safety related are never auto-actioned.
REVIEW_REQUIRED = {
    EventType.NO_SEATBELT,
    EventType.PHONE_USE,
    EventType.LITTERING,
    EventType.NO_HELMET,
    EventType.ALTERCATION,
    EventType.CROWD_ANOMALY,
    EventType.ANOMALY_UNCLASSIFIED,
}

#: Events that should reach a dispatcher/operator immediately (life-safety).
IMMEDIATE_DISPATCH = {
    EventType.COLLISION,
    EventType.PEDESTRIAN_ON_ROADWAY,
    EventType.WRONG_WAY,
    EventType.ALTERCATION,
    EventType.DEBRIS_ON_ROADWAY,
}


@dataclass
class Evidence:
    """Where to find the proof for an event."""

    frame_index: int
    timestamp: float
    clip_path: Optional[str] = None
    still_path: Optional[str] = None
    clip_start_frame: Optional[int] = None
    clip_end_frame: Optional[int] = None
    #: True once faces/bystanders have been blurred in the stored artefacts.
    privacy_filtered: bool = False


@dataclass
class Event:
    type: EventType
    severity: Severity
    timestamp: float
    tower_id: str = "tower-000"
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    #: Detector confidence 0..1. For measurement-class events this is the
    #: instrument confidence, not a classifier score.
    confidence: float = 1.0
    track_ids: List[int] = field(default_factory=list)
    plate_text: Optional[str] = None
    speed_kmh: Optional[float] = None
    speed_limit_kmh: Optional[float] = None
    world_xy: Optional[Tuple[float, float]] = None
    bbox: Optional[Tuple[float, float, float, float]] = None
    lane: Optional[str] = None
    evidence: Optional[Evidence] = None
    #: Human-readable one-liner for the operator console.
    message: str = ""
    #: Free-form detector detail (which signals fired, sub-scores, ...).
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def requires_review(self) -> bool:
        return self.type in REVIEW_REQUIRED

    @property
    def immediate(self) -> bool:
        return self.type in IMMEDIATE_DISPATCH or self.severity >= Severity.HIGH

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        d["severity"] = int(self.severity)
        d["severity_name"] = self.severity.name
        d["requires_review"] = self.requires_review
        d["immediate"] = self.immediate
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ---------------------------------------------------------------------- #
# Bus
# ---------------------------------------------------------------------- #
Handler = Callable[[Event], None]


class EventBus:
    """Fan-out with per-(type, track) cooldown so one incident = one event.

    ``cooldowns`` maps an :class:`EventType` to seconds; the default applies to
    anything unlisted. A cooldown of 0 disables suppression for that type.
    """

    DEFAULT_COOLDOWN_S = 5.0

    def __init__(
        self,
        cooldowns: Optional[Dict[EventType, float]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._handlers: List[Tuple[Handler, Optional[Callable[[Event], bool]]]] = []
        self._last_fired: Dict[Tuple[str, str], float] = {}
        self.cooldowns = dict(cooldowns or {})
        self._clock = clock
        self.published: List[Event] = []
        self.suppressed_count: Dict[str, int] = defaultdict(int)

    def subscribe(
        self, handler: Handler, predicate: Optional[Callable[[Event], bool]] = None
    ) -> None:
        """Register ``handler``; if ``predicate`` is given it must return True."""
        self._handlers.append((handler, predicate))

    def _key(self, event: Event) -> Tuple[str, str]:
        tracks = ",".join(str(t) for t in sorted(event.track_ids))
        return (event.type.value, tracks)

    def publish(self, event: Event) -> bool:
        """Publish unless suppressed by cooldown. Returns True if delivered."""
        cooldown = self.cooldowns.get(event.type, self.DEFAULT_COOLDOWN_S)
        if cooldown > 0:
            key = self._key(event)
            last = self._last_fired.get(key)
            now = event.timestamp
            if last is not None and (now - last) < cooldown:
                self.suppressed_count[event.type.value] += 1
                return False
            self._last_fired[key] = now

        self.published.append(event)
        for handler, predicate in self._handlers:
            if predicate is not None and not predicate(event):
                continue
            try:
                handler(event)
            except Exception:
                # A broken dispatcher must never take down the pipeline.
                continue
        return True

    def events_of(self, event_type: EventType) -> List[Event]:
        return [e for e in self.published if e.type is event_type]


# ---------------------------------------------------------------------- #
# Dispatchers
# ---------------------------------------------------------------------- #
class JsonlDispatcher:
    """Append every event to a newline-delimited JSON log (the local record)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, event: Event) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(event.to_json() + "\n")


class WebhookDispatcher:
    """POST events to the command centre.

    Queues locally on failure so a 5G outage does not lose incidents; the
    queue is drained on the next successful post.
    """

    def __init__(self, url: str, timeout: float = 5.0, max_queue: int = 5000,
                 auth_token: Optional[str] = None) -> None:
        self.url = url
        self.timeout = timeout
        self.max_queue = max_queue
        self.auth_token = auth_token
        self.queue: List[Event] = []
        self.sent_count = 0

    def _post(self, payload: str) -> bool:
        import urllib.error
        import urllib.request

        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        req = urllib.request.Request(
            self.url, data=payload.encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    def __call__(self, event: Event) -> None:
        pending = self.queue + [event]
        remaining: List[Event] = []
        for i, ev in enumerate(pending):
            if self._post(ev.to_json()):
                self.sent_count += 1
            else:
                remaining = pending[i:]
                break
        self.queue = remaining[-self.max_queue :]


class ConsoleDispatcher:
    """Human-readable operator console line."""

    ICONS = {
        Severity.CRITICAL: "!!!",
        Severity.HIGH: "!! ",
        Severity.MEDIUM: " ! ",
        Severity.LOW: "  ·",
        Severity.INFO: "  ·",
    }

    def __init__(self, min_severity: Severity = Severity.LOW) -> None:
        self.min_severity = min_severity

    def __call__(self, event: Event) -> None:
        if event.severity < self.min_severity:
            return
        icon = self.ICONS.get(event.severity, "   ")
        tag = "[REVIEW]" if event.requires_review else ""
        plate = f" {event.plate_text}" if event.plate_text else ""
        print(f"{icon} t={event.timestamp:7.2f}s {event.type.value:<22}"
              f"{plate:<12} {event.message} {tag}")


class CallbackDispatcher:
    """Adapter so any plain function can subscribe (tests, custom sinks)."""

    def __init__(self, fn: Handler) -> None:
        self.fn = fn

    def __call__(self, event: Event) -> None:
        self.fn(event)
