"""speeddet — the Sentinel tower software stack.

Layers, lowest to highest:

* **Measurement** — :mod:`.calibration`, :mod:`.detection`, :mod:`.tracking`,
  :mod:`.speed`. Homography-calibrated, instrument-grade speed.
* **Identification** — :mod:`.plates` (Qatar plate taxonomy + OCR),
  :mod:`.alpr` (production ALPR backends).
* **Analytics** — :mod:`.analytics`: kinematic anomalies (collision, stopped
  vehicle, wrong-way, erratic driving, congestion), occupant behaviour
  (seatbelt, phone) and littering.
* **Events** — :mod:`.events`: one bus, deduped, dispatched to the command
  centre. Classifier outputs are flagged for human review, never auto-actioned.
* **Privacy** — :mod:`.privacy`: redaction by default, hash-chained audit,
  retention clock, and an identity boundary that keeps biometrics off the
  tower.
* **Tower** — :mod:`.tower`: subsystem health, time-boxed CCTV sessions, and
  the drone nest state machine with its safety interlocks.

See ``docs/sentinel-tower.md`` for the whole system design.
"""

from .calibration import Calibrator
from .events import Event, EventBus, EventType, Severity
from .pipeline import PipelineConfig, SpeedPipeline
from .speed import SpeedEstimator
from .tracking import IouTracker
from .types import Detection, TrackedObject

__all__ = [
    "Detection",
    "TrackedObject",
    "Calibrator",
    "IouTracker",
    "SpeedEstimator",
    "SpeedPipeline",
    "PipelineConfig",
    "Event",
    "EventBus",
    "EventType",
    "Severity",
]

__version__ = "0.3.0"
