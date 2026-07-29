"""Privacy controls: redaction, audit integrity, retention, identity boundary."""

import time
from pathlib import Path

import numpy as np
import pytest

from speeddet.privacy import (
    AuditLog,
    DeniedIdentityResolver,
    IdentityRequest,
    PrivacyConfig,
    PrivacyFilter,
    RedactionMode,
    RetentionPolicy,
    blur_regions,
)


class _FakeFaceDetector:
    def __init__(self, boxes):
        self.boxes = boxes

    def detect_faces(self, frame):
        return list(self.boxes)


def _frame():
    rng = np.random.default_rng(0)
    return rng.integers(0, 255, (200, 200, 3), dtype=np.uint8)


# --------------------------- redaction --------------------------------- #
def test_blur_destroys_detail_in_region():
    frame = _frame()
    out = blur_regions(frame, [(50, 50, 150, 150)])
    inside_before = frame[60:140, 60:140].astype(float)
    inside_after = out[60:140, 60:140].astype(float)
    # Variance collapses inside the region (detail is gone)...
    assert inside_after.var() < inside_before.var() * 0.5
    # ...and nothing outside it changed.
    assert np.array_equal(out[:40, :40], frame[:40, :40])


def test_privacy_filter_blurs_detected_faces():
    frame = _frame()
    pf = PrivacyFilter(PrivacyConfig(), _FakeFaceDetector([(20, 20, 80, 80)]))
    out = pf.apply(frame)
    assert not np.array_equal(out[25:75, 25:75], frame[25:75, 25:75])


def test_redaction_none_is_passthrough():
    frame = _frame()
    pf = PrivacyFilter(PrivacyConfig(redaction=RedactionMode.NONE),
                       _FakeFaceDetector([(20, 20, 80, 80)]))
    assert np.array_equal(pf.apply(frame), frame)


def test_except_subject_keeps_the_subject_visible():
    frame = _frame()
    pf = PrivacyFilter(
        PrivacyConfig(redaction=RedactionMode.EXCEPT_SUBJECT,
                      blur_whole_pedestrians=False),
        _FakeFaceDetector([(30, 30, 60, 60), (150, 150, 180, 180)]),
    )
    out = pf.apply(frame, subject_bbox=(20, 20, 100, 100))
    # Face inside the subject vehicle survives (reviewer must see the driver).
    assert np.array_equal(out[30:60, 30:60], frame[30:60, 30:60])
    # The bystander outside it is blurred.
    assert not np.array_equal(out[150:180, 150:180], frame[150:180, 150:180])


def test_pedestrians_blurred_wholesale():
    frame = _frame()
    pf = PrivacyFilter(PrivacyConfig(blur_whole_pedestrians=True),
                       _FakeFaceDetector([]))
    out = pf.apply(frame, pedestrian_bboxes=[(10, 10, 90, 90)])
    assert not np.array_equal(out[20:80, 20:80], frame[20:80, 20:80])


# ----------------------------- audit ----------------------------------- #
def test_audit_log_chain_verifies(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("cctv_session_open", "operator_a", {"camera": "ptz-1"})
    log.record("identity_lookup", "operator_b", {"plate": "TX 42781"})
    assert log.verify() is True
    assert len(log.entries()) == 2


def test_audit_log_detects_tampering(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.record("cctv_session_open", "operator_a", {"camera": "ptz-1"})
    log.record("cctv_session_close", "operator_a", {})
    assert log.verify() is True

    lines = path.read_text().splitlines()
    lines[0] = lines[0].replace("operator_a", "operator_z")
    path.write_text("\n".join(lines) + "\n")
    assert log.verify() is False, "edited audit entry must break the chain"


def test_audit_log_detects_deletion(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(3):
        log.record("event", f"op{i}", {})
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert log.verify() is False, "removed audit entry must break the chain"


# --------------------------- identity ---------------------------------- #
def test_unconfigured_tower_refuses_identity_lookup():
    resolver = DeniedIdentityResolver()
    resp = resolver.resolve(IdentityRequest(
        event_id="abc", plate_text="TX 42781",
        requested_by="operator_a", justification="collision follow-up"))
    assert resp.matched is False
    assert "No authorised identity system" in resp.note


# --------------------------- retention --------------------------------- #
def test_retention_expires_old_unactioned_evidence(tmp_path):
    old = tmp_path / "old.mp4"
    old.write_bytes(b"x")
    recent = tmp_path / "recent.mp4"
    recent.write_bytes(b"x")
    # Age the first file 60 days.
    ancient = time.time() - 60 * 86400
    import os
    os.utime(old, (ancient, ancient))

    policy = RetentionPolicy(PrivacyConfig(retention_days_unactioned=30))
    removed = policy.sweep(tmp_path)
    assert str(old) in removed
    assert recent.exists()


def test_actioned_evidence_kept_longer(tmp_path):
    import os

    path = tmp_path / "case.mp4"
    path.write_bytes(b"x")
    ancient = time.time() - 60 * 86400
    os.utime(path, (ancient, ancient))

    policy = RetentionPolicy(PrivacyConfig(retention_days_unactioned=30,
                                           retention_days_actioned=365))
    removed = policy.sweep(tmp_path, actioned_paths=[str(path)])
    assert removed == []
    assert path.exists()
