"""Training utilities for the occupant (seatbelt / phone) classifier.

Two things live here:

* :mod:`.synth_dataset` — a domain-randomised synthetic windshield-crop
  generator. It exists so the training pipeline can be built, run and
  *verified end to end* before any real footage exists, and so the pipeline
  itself is proven before you spend money on a labelling campaign.
* :mod:`.train_occupant` — the real training loop: model, augmentation,
  held-out evaluation with per-class metrics, calibration check, ONNX export.

**Read this before trusting a model from here.** A classifier trained only on
synthetic crops will not transfer to a real camera. Synthetic data fixes the
*engineering* risk (does the pipeline work, does the loss go down, does the
export load, does the tower consume it) — it does not fix the *domain* risk
(does it work on real windshields at your mounting angle, in Doha glare, on
locally common vehicles). The documented path is:

1. train on synthetic to prove the pipeline (what this module does);
2. collect and label real crops from your own cameras;
3. fine-tune on real data, keeping synthetic as augmentation;
4. evaluate on a held-out *real* set, per-class, and publish the numbers;
5. only then let it propose violations to a human reviewer.

See ``docs/report-2-data-and-models.md``.
"""

from .synth_dataset import CabinRenderer, SynthConfig, build_dataset

__all__ = ["CabinRenderer", "SynthConfig", "build_dataset"]
