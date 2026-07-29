"""Synthetic data generator and training-metric correctness.

These are fast: they exercise the generator and the metric maths without
training a model. The full training run is a script, not a test.
"""

import numpy as np
import pytest

from speeddet.training.synth_dataset import CabinRenderer, SynthConfig, build_dataset


# --------------------------- generator --------------------------------- #
def test_dataset_shape_and_labels():
    X, belts, phones = build_dataset(64, SynthConfig(size=(48, 48)), seed=3)
    assert X.shape == (64, 48, 48, 3)
    assert X.dtype == np.uint8
    assert set(np.unique(belts)) <= {0, 1}
    assert set(np.unique(phones)) <= {0, 1}


def test_dataset_is_reproducible_from_seed():
    a = build_dataset(16, SynthConfig(size=(48, 48)), seed=7)[0]
    b = build_dataset(16, SynthConfig(size=(48, 48)), seed=7)[0]
    assert np.array_equal(a, b)


def test_different_seeds_give_different_data():
    a = build_dataset(16, SynthConfig(size=(48, 48)), seed=1)[0]
    b = build_dataset(16, SynthConfig(size=(48, 48)), seed=2)[0]
    assert not np.array_equal(a, b)


def test_class_balance_is_deliberately_skewed():
    """Real traffic is mostly belted and mostly not on the phone; a 50/50
    training set produces a badly calibrated deployed model."""
    _, belts, phones = build_dataset(2000, SynthConfig(size=(32, 32)), seed=5)
    assert 0.5 < belts.mean() < 0.75
    assert 0.15 < phones.mean() < 0.40


def test_task_is_not_trivially_separable_by_brightness():
    """The generator must not leak the label through a global statistic.

    If mean brightness alone separated belted from unbelted, the model would
    learn that instead of the sash, and would collapse on real footage where
    glare decouples the two.
    """
    X, belts, _ = build_dataset(600, SynthConfig(size=(48, 48)), seed=11)
    means = X.reshape(len(X), -1).mean(axis=1)
    belted, unbelted = means[belts == 1], means[belts == 0]
    # Standardised mean difference (Cohen's d) should be small.
    pooled = np.sqrt((belted.var() + unbelted.var()) / 2) + 1e-9
    d = abs(belted.mean() - unbelted.mean()) / pooled
    assert d < 0.6, f"brightness alone separates the classes (d={d:.2f})"


def test_renderer_respects_requested_size():
    r = CabinRenderer(SynthConfig(size=(72, 56)))
    rng = np.random.default_rng(0)
    img = r.render(rng, belt=True, phone=False)
    assert img.shape == (56, 72, 3)


def test_ir_samples_are_near_monochrome():
    """IR rendering must actually be colour-free, since the production camera
    uses near-IR to see through tint."""
    cfg = SynthConfig(size=(48, 48), ir_fraction=1.0, glare_prob=0.0,
                      heavy_degradation_prob=0.0)
    r = CabinRenderer(cfg)
    rng = np.random.default_rng(4)
    spreads = []
    for _ in range(20):
        img = r.render(rng, belt=True, phone=True).astype(float)
        spreads.append(np.mean(np.abs(img.max(axis=2) - img.min(axis=2))))
    assert np.mean(spreads) < 40


# ---------------------------- metrics ---------------------------------- #
def test_binary_metrics_match_hand_computation():
    from speeddet.training.train_occupant import binary_metrics

    # probs[:,1] is P(positive). Labels: 1,1,0,0
    probs = np.array([[0.1, 0.9], [0.6, 0.4], [0.2, 0.8], [0.9, 0.1]])
    labels = np.array([1, 1, 0, 0])
    m = binary_metrics(probs, labels)
    assert m["tp"] == 1 and m["fn"] == 1 and m["fp"] == 1 and m["tn"] == 1
    assert m["precision"] == pytest.approx(0.5)
    assert m["recall"] == pytest.approx(0.5)
    assert m["accuracy"] == pytest.approx(0.5)
    assert m["false_positive_rate"] == pytest.approx(0.5)


def test_abstention_curve_trades_coverage_for_accuracy():
    from speeddet.training.train_occupant import abstention_curve

    # Confident and correct, versus unconfident and wrong.
    probs = np.array([[0.02, 0.98], [0.02, 0.98], [0.48, 0.52], [0.52, 0.48]])
    labels = np.array([1, 1, 0, 1])
    curve = abstention_curve(probs, labels, thresholds=(0.5, 0.9))
    low, high = curve[0], curve[1]
    assert low["coverage"] == 1.0
    assert high["coverage"] == 0.5
    # Declining the uncertain half raises accuracy on what remains.
    assert high["accuracy_when_judged"] > low["accuracy_when_judged"]


def test_perfect_confidence_and_accuracy_gives_zero_ece():
    from speeddet.training.train_occupant import expected_calibration_error

    probs = np.array([[0.0, 1.0], [0.0, 1.0], [1.0, 0.0]])
    labels = np.array([1, 1, 0])
    assert expected_calibration_error(probs, labels) == pytest.approx(0.0, abs=1e-6)


def test_overconfident_wrong_model_has_high_ece():
    from speeddet.training.train_occupant import expected_calibration_error

    # Claims 99% confidence, gets everything wrong.
    probs = np.array([[0.01, 0.99]] * 8)
    labels = np.zeros(8, dtype=int)
    assert expected_calibration_error(probs, labels) > 0.9


def test_model_builds_with_two_heads():
    pytest.importorskip("torch")
    import torch

    from speeddet.training.train_occupant import build_model

    model = build_model(width=8)
    belt, phone = model(torch.randn(2, 3, 64, 64))
    assert belt.shape == (2, 2)
    assert phone.shape == (2, 2)
