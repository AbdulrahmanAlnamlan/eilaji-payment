"""Privacy controls: face handling, retention, and the identity boundary.

This module exists because a tower that watches a public street continuously
is a different legal object from a speed camera, and the difference has to be
enforced in code rather than in a policy document nobody reads.

Three things live here.

1. **Face detection for redaction.** Faces and bystanders in stored evidence
   are blurred by default. Detection here serves *de-identification*: the
   output is a blur, not an identity.

2. **The identity boundary.** The tower deliberately holds **no face
   database and no face embeddings**. Where an authorised identity lookup is
   required, :class:`IdentityResolver` is an interface to the *government's*
   system: the tower sends a request and receives an answer. It never becomes
   a roving biometric index itself.

   This is not only the compliant design, it is the better one:

   * a compromised or stolen roadside unit leaks no biometric database;
   * the authorised system keeps one audit trail instead of N;
   * plate → owner is already the lawful, sufficient path for traffic
     enforcement, and it is far more accurate than face matching at
     highway distance through a windshield.

   Under Qatar's Personal Data Privacy Protection Law (Law No. 13 of 2016),
   biometric data is special-category data requiring a stronger lawful basis
   than ordinary traffic enforcement provides. Design accordingly: keep face
   *recognition* off the tower, and gate any lookup behind the authority that
   owns the legal basis.

3. **Retention and audit.** Evidence has a clock on it, and every operator
   who opens a live view or pulls a clip is recorded. If the system is ever
   challenged, the audit log is what shows it was used as intended.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

import numpy as np

Bbox = Tuple[int, int, int, int]


class RedactionMode(str, Enum):
    #: Blur every detected face (default for anything stored or exported).
    ALL_FACES = "all_faces"
    #: Blur faces except inside the bounding box of the vehicle that is the
    #: subject of the violation — used only when a reviewer must confirm a
    #: driver-behaviour proposal, and only inside the review tool.
    EXCEPT_SUBJECT = "except_subject"
    #: No redaction. Requires an explicit, logged authorisation.
    NONE = "none"


@dataclass
class PrivacyConfig:
    redaction: RedactionMode = RedactionMode.ALL_FACES
    blur_kernel: int = 31
    #: Days to keep evidence for events that were never actioned.
    retention_days_unactioned: int = 30
    #: Days to keep evidence attached to an issued citation / open case.
    retention_days_actioned: int = 365
    #: Days to keep raw (non-event) recording. Zero = keep nothing, which is
    #: the right default: the tower is an event sensor, not a mass recorder.
    retention_days_raw: int = 0
    #: Blur pedestrians entirely, not just their faces (safer at distance,
    #: where face detection fails but a person is still identifiable by
    #: clothing and gait).
    blur_whole_pedestrians: bool = True


class FaceDetector(Protocol):
    def detect_faces(self, frame: np.ndarray) -> List[Bbox]:
        ...


class HaarFaceDetector:
    """OpenCV cascade face detector — dependency-free, adequate for redaction.

    Redaction has an asymmetric cost profile: a false positive blurs some
    tarmac (harmless), a false negative leaks a face. So we run it permissively
    and combine it with whole-pedestrian blurring rather than chasing accuracy.
    """

    def __init__(self, scale_factor: float = 1.1, min_neighbors: int = 4,
                 min_size: int = 16) -> None:
        import cv2

        path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        self._cascade = cv2.CascadeClassifier(str(path))
        self.scale_factor = scale_factor
        self.min_neighbors = min_neighbors
        self.min_size = min_size
        self.available = not self._cascade.empty()

    def detect_faces(self, frame: np.ndarray) -> List[Bbox]:
        if not self.available or frame is None or frame.size == 0:
            return []
        import cv2

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(
            gray, scaleFactor=self.scale_factor, minNeighbors=self.min_neighbors,
            minSize=(self.min_size, self.min_size),
        )
        return [(int(x), int(y), int(x + w), int(y + h)) for x, y, w, h in faces]


class NullFaceDetector:
    def detect_faces(self, frame: np.ndarray) -> List[Bbox]:  # noqa: ARG002
        return []


def blur_regions(frame: np.ndarray, regions: Sequence[Bbox],
                 kernel: int = 31) -> np.ndarray:
    """Return a copy of ``frame`` with each region irreversibly blurred.

    Uses a heavy Gaussian plus downsample-upsample so the result cannot be
    sharpened back — a light blur is not redaction.
    """
    import cv2

    out = frame.copy()
    k = kernel if kernel % 2 == 1 else kernel + 1
    for (x1, y1, x2, y2) in regions:
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(out.shape[1], int(x2)), min(out.shape[0], int(y2))
        if x2 <= x1 or y2 <= y1:
            continue
        patch = out[y1:y2, x1:x2]
        small = cv2.resize(patch, (max(1, patch.shape[1] // 12),
                                   max(1, patch.shape[0] // 12)),
                           interpolation=cv2.INTER_AREA)
        patch = cv2.resize(small, (patch.shape[1], patch.shape[0]),
                           interpolation=cv2.INTER_NEAREST)
        out[y1:y2, x1:x2] = cv2.GaussianBlur(patch, (k, k), 0)
    return out


class PrivacyFilter:
    """Applies the configured redaction to frames before they are stored."""

    def __init__(self, config: Optional[PrivacyConfig] = None,
                 face_detector: Optional[FaceDetector] = None) -> None:
        self.cfg = config or PrivacyConfig()
        self.face_detector = face_detector or NullFaceDetector()

    def apply(self, frame: np.ndarray,
              subject_bbox: Optional[Tuple[float, float, float, float]] = None,
              pedestrian_bboxes: Sequence[Tuple[float, float, float, float]] = (),
              ) -> np.ndarray:
        if self.cfg.redaction is RedactionMode.NONE:
            return frame
        regions: List[Bbox] = [tuple(int(v) for v in b) for b in self.face_detector.detect_faces(frame)]
        if self.cfg.blur_whole_pedestrians:
            regions += [tuple(int(v) for v in b) for b in pedestrian_bboxes]
        if self.cfg.redaction is RedactionMode.EXCEPT_SUBJECT and subject_bbox:
            sx1, sy1, sx2, sy2 = subject_bbox
            regions = [r for r in regions
                       if not (r[0] >= sx1 and r[1] >= sy1
                               and r[2] <= sx2 and r[3] <= sy2)]
        if not regions:
            return frame
        return blur_regions(frame, regions, self.cfg.blur_kernel)


# ---------------------------------------------------------------------- #
# Identity boundary
# ---------------------------------------------------------------------- #
@dataclass
class IdentityRequest:
    """A request for identity, always tied to a specific event and operator."""

    event_id: str
    plate_text: Optional[str]
    requested_by: str
    justification: str
    requested_at: float = field(default_factory=time.time)


@dataclass
class IdentityResponse:
    matched: bool
    reference: Optional[str] = None  # opaque case/owner reference, not raw PII
    source: str = ""
    note: str = ""


class IdentityResolver(Protocol):
    """Interface to the *authorised* identity system, outside the tower."""

    def resolve(self, request: IdentityRequest) -> IdentityResponse:
        ...


class DeniedIdentityResolver:
    """Default resolver: refuses. A tower with no integration resolves nothing.

    This is deliberately the default so that an unconfigured unit cannot be
    made to perform identity lookups — the capability has to be switched on
    with an explicit, authorised integration.
    """

    def resolve(self, request: IdentityRequest) -> IdentityResponse:  # noqa: ARG002
        return IdentityResponse(
            matched=False, source="none",
            note="No authorised identity system configured for this tower.",
        )


class PlateLookupResolver:
    """Plate → owner via the authority's registry endpoint (no biometrics).

    The lawful, accurate path for traffic enforcement: the vehicle is the
    subject, the registered keeper is the addressee, and the tower never holds
    the answer — it forwards a question and logs that it asked.
    """

    def __init__(self, endpoint: str, auth_token: Optional[str] = None,
                 timeout: float = 5.0, audit: Optional["AuditLog"] = None) -> None:
        self.endpoint = endpoint
        self.auth_token = auth_token
        self.timeout = timeout
        self.audit = audit

    def resolve(self, request: IdentityRequest) -> IdentityResponse:
        import urllib.request

        if self.audit:
            self.audit.record("identity_lookup", request.requested_by, {
                "event_id": request.event_id,
                "plate": request.plate_text,
                "justification": request.justification,
            })
        if not request.plate_text:
            return IdentityResponse(matched=False, source=self.endpoint,
                                    note="no plate on event")
        payload = json.dumps({"plate": request.plate_text,
                              "event_id": request.event_id}).encode()
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        req = urllib.request.Request(self.endpoint, data=payload,
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
            return IdentityResponse(matched=bool(data.get("matched")),
                                    reference=data.get("reference"),
                                    source=self.endpoint)
        except Exception as exc:
            return IdentityResponse(matched=False, source=self.endpoint,
                                    note=f"lookup failed: {exc}")


# ---------------------------------------------------------------------- #
# Audit + retention
# ---------------------------------------------------------------------- #
class AuditLog:
    """Append-only, hash-chained record of every privileged action.

    Each entry embeds the hash of the previous one, so removing or editing a
    line breaks the chain and :meth:`verify` fails. That is what makes the log
    evidence rather than a text file.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def _last_hash(self) -> str:
        last = ""
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = line.strip()
        if not last:
            return "0" * 64
        return json.loads(last)["entry_hash"]

    def record(self, action: str, actor: str,
               detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        entry = {
            "timestamp": time.time(),
            "action": action,
            "actor": actor,
            "detail": detail or {},
            "prev_hash": self._last_hash(),
        }
        blob = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        entry["entry_hash"] = hashlib.sha256(blob.encode()).hexdigest()
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def verify(self) -> bool:
        prev = "0" * 64
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry["prev_hash"] != prev:
                    return False
                claimed = entry.pop("entry_hash")
                blob = json.dumps(entry, sort_keys=True, ensure_ascii=False)
                if hashlib.sha256(blob.encode()).hexdigest() != claimed:
                    return False
                prev = claimed
        return True

    def entries(self) -> List[Dict[str, Any]]:
        out = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    out.append(json.loads(line))
        return out


class RetentionPolicy:
    """Deletes evidence whose clock has run out."""

    def __init__(self, config: Optional[PrivacyConfig] = None,
                 audit: Optional[AuditLog] = None) -> None:
        self.cfg = config or PrivacyConfig()
        self.audit = audit

    def expired(self, path: Path, actioned: bool, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        days = (self.cfg.retention_days_actioned if actioned
                else self.cfg.retention_days_unactioned)
        try:
            age_days = (now - path.stat().st_mtime) / 86400.0
        except OSError:
            return False
        return age_days > days

    def sweep(self, directory: str | Path, actioned_paths: Sequence[str] = (),
              now: Optional[float] = None) -> List[str]:
        directory = Path(directory)
        actioned = {str(Path(p).resolve()) for p in actioned_paths}
        removed: List[str] = []
        if not directory.exists():
            return removed
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            is_actioned = str(path.resolve()) in actioned
            if self.expired(path, is_actioned, now):
                try:
                    path.unlink()
                    removed.append(str(path))
                except OSError:
                    continue
        if removed and self.audit:
            self.audit.record("retention_sweep", "system",
                              {"removed_count": len(removed)})
        return removed
