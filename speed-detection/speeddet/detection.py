"""Object detection backends.

Two interchangeable detectors implement the same ``detect(frame) -> [Detection]``
interface:

* ``YoloDetector``      — production path. Wraps ultralytics YOLOv8/v11. Lazily
                          imported so the rest of the package works without it.
* ``ColorBlobDetector`` — a tiny classical-CV detector that finds saturated
                          coloured blobs. Used by the synthetic demo so the full
                          tracking + speed pipeline is runnable and testable
                          without downloading YOLO weights or needing a GPU.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

from .types import Detection

# COCO class ids that count as "vehicles" for YOLO.
VEHICLE_CLASS_IDS = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


class YoloDetector:
    """Ultralytics YOLO wrapper (YOLOv8 / YOLOv11).

    Parameters
    ----------
    model_path: path or model name, e.g. ``"yolov8n.pt"`` or a fine-tuned weight.
    conf: confidence threshold.
    vehicle_only: keep only vehicle classes (car/motorcycle/bus/truck).
    device: ``None`` (auto), ``"cpu"``, ``"cuda:0"`` …
    """

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        conf: float = 0.35,
        iou: float = 0.5,
        vehicle_only: bool = True,
        device: Optional[str] = None,
        imgsz: int = 640,
    ) -> None:
        try:
            from ultralytics import YOLO  # noqa: WPS433 (lazy, optional dep)
        except Exception as exc:  # pragma: no cover - depends on env
            raise ImportError(
                "ultralytics is required for YoloDetector. Install with "
                "`pip install ultralytics` (see requirements.txt), or use "
                "ColorBlobDetector for the synthetic demo."
            ) from exc
        self._model = YOLO(model_path)
        self.conf = conf
        self.iou = iou
        self.vehicle_only = vehicle_only
        self.device = device
        self.imgsz = imgsz

    def detect(self, frame: np.ndarray) -> List[Detection]:
        results = self._model.predict(
            frame,
            conf=self.conf,
            iou=self.iou,
            imgsz=self.imgsz,
            device=self.device,
            verbose=False,
        )
        detections: List[Detection] = []
        for res in results:
            boxes = getattr(res, "boxes", None)
            if boxes is None:
                continue
            names = getattr(res, "names", {})
            for box in boxes:
                cls_id = int(box.cls[0])
                if self.vehicle_only and cls_id not in VEHICLE_CLASS_IDS:
                    continue
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
                detections.append(
                    Detection(
                        bbox=(x1, y1, x2, y2),
                        confidence=float(box.conf[0]),
                        class_id=cls_id,
                        class_name=VEHICLE_CLASS_IDS.get(cls_id, names.get(cls_id, "object")),
                    )
                )
        return detections


class ColorBlobDetector:
    """Detect saturated coloured rectangles on a low-saturation background.

    This is deliberately simple: the synthetic footage draws each vehicle in a
    distinct vivid colour on a grey road, so an HSV saturation/value threshold
    plus contour extraction recovers clean bounding boxes. It lets us validate
    detection -> tracking -> speed end-to-end with zero heavyweight deps.
    """

    def __init__(
        self,
        sat_min: int = 90,
        val_min: int = 60,
        min_area_px: int = 60,
        class_name: str = "vehicle",
    ) -> None:
        self.sat_min = sat_min
        self.val_min = val_min
        self.min_area_px = min_area_px
        self.class_name = class_name

    def detect(self, frame: np.ndarray) -> List[Detection]:
        import cv2  # local import; opencv is a core dep for video I/O anyway

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        _, sat, val = cv2.split(hsv)
        mask = ((sat >= self.sat_min) & (val >= self.val_min)).astype(np.uint8) * 255
        # Merge nearby fragments belonging to the same vehicle.
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        detections: List[Detection] = []
        for cnt in contours:
            if cv2.contourArea(cnt) < self.min_area_px:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            detections.append(
                Detection(
                    bbox=(float(x), float(y), float(x + w), float(y + h)),
                    confidence=1.0,
                    class_id=0,
                    class_name=self.class_name,
                )
            )
        return detections


class GroundTruthDetector:
    """Replays pre-recorded per-frame boxes (used to isolate tracking/speed).

    ``frames`` maps a frame index to a list of ``Detection`` objects.
    """

    def __init__(self, frames: Sequence[Sequence[Detection]]) -> None:
        self._frames = list(frames)
        self._i = 0

    def detect(self, frame: np.ndarray) -> List[Detection]:  # noqa: ARG002
        if self._i >= len(self._frames):
            return []
        dets = list(self._frames[self._i])
        self._i += 1
        return dets
