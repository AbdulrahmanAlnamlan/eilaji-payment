"""Analytics layer: everything that turns tracks + pixels into Events.

Each analyzer implements ``analyze(ctx) -> List[Event]`` and is independent,
so a tower runs whichever subset its role requires:

* :mod:`.kinematics` — motion-derived anomalies (collision, stopped vehicle,
  wrong-way, erratic driving, congestion). Instrument-grade, no ML model
  needed, fully verifiable against known trajectories.
* :mod:`.occupant`   — in-cabin behaviour (seatbelt, phone) from the
  windshield ROI. Classifier-class: proposals for human review.
* :mod:`.litter`     — objects ejected from vehicle windows.
"""

from .base import Analyzer, FrameContext, TrackState
from .kinematics import KinematicAnalyzer, KinematicConfig
from .litter import LitterAnalyzer
from .occupant import OccupantAnalyzer, OccupantConfig, WindshieldROI

__all__ = [
    "Analyzer",
    "FrameContext",
    "TrackState",
    "KinematicAnalyzer",
    "KinematicConfig",
    "LitterAnalyzer",
    "OccupantAnalyzer",
    "OccupantConfig",
    "WindshieldROI",
]
