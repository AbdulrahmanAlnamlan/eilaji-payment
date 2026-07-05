"""speeddet — a runnable prototype of the speed-detection core.

Pipeline: video frames -> object detection -> multi-object tracking ->
homography-based pixel->world mapping -> speed estimation -> violation triggers.

The detection backend is pluggable:
  * ``YoloDetector``       — real YOLOv8/v11 via ultralytics (production path).
  * ``ColorBlobDetector``  — dependency-light detector used by the synthetic
                             demo so the whole pipeline is runnable/verifiable
                             without downloading model weights or a GPU.

See the top-level README for the architecture and how this maps to the full
"smart traffic radar" system (evidence clips, ALPR, backend dispatch).
"""

from .types import Detection, TrackedObject
from .calibration import Calibrator
from .tracking import IouTracker
from .speed import SpeedEstimator
from .pipeline import SpeedPipeline, PipelineConfig

__all__ = [
    "Detection",
    "TrackedObject",
    "Calibrator",
    "IouTracker",
    "SpeedEstimator",
    "SpeedPipeline",
    "PipelineConfig",
]

__version__ = "0.1.0"
