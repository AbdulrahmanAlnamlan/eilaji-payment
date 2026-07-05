"""Tracker identity persistence and coasting."""

from speeddet.detection import Detection
from speeddet.tracking import IouTracker, iou


def _det(x1, y1, x2, y2):
    return Detection(bbox=(x1, y1, x2, y2))


def test_iou_basic():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert abs(iou((0, 0, 10, 10), (5, 0, 15, 10)) - (50 / 150)) < 1e-9


def test_single_object_keeps_id():
    tr = IouTracker(min_hits=1)
    ids = []
    for i in range(6):
        x = 100 + i * 10
        out = tr.update([_det(x, 100, x + 40, 160)])
        assert len(out) == 1
        ids.append(out[0][0])
    assert len(set(ids)) == 1  # same id throughout


def test_two_objects_distinct_ids():
    tr = IouTracker(min_hits=1)
    out = None
    for i in range(4):
        a = 50 + i * 8
        b = 400 + i * 8
        out = tr.update([_det(a, 100, a + 30, 140), _det(b, 100, b + 30, 140)])
    ids = {tid for tid, _ in out}
    assert len(ids) == 2


def test_coasts_through_missed_frame():
    tr = IouTracker(min_hits=1, max_misses=5)
    for i in range(4):
        x = 100 + i * 10
        tr.update([_det(x, 100, x + 40, 160)])
    # One frame with no detection: track should survive (coast), not be dropped.
    tr.update([])
    assert len(tr.tracks) == 1
    # Re-acquire near the predicted position -> same id.
    out = tr.update([_det(150, 100, 190, 160)])
    assert len(out) == 1
