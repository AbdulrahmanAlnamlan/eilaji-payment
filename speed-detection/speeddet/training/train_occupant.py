"""Train the two-head occupant classifier (seatbelt / phone) and export ONNX.

The model is deliberately small — a ~200k-parameter CNN at 96×96. Reasons:

* it runs at frame rate on a Jetson alongside detection and tracking;
* the task is a two-way call on a small, tightly-cropped region, not
  ImageNet — depth buys little and costs latency;
* small models are easier to keep calibrated, and **calibration matters more
  than accuracy here**: the tower must know when to abstain, because an
  unreadable crop must return "unclear", not a confident guess.

Evaluation reports per-class precision/recall, the confusion matrix, and the
**abstention curve** — accuracy as a function of how many low-confidence
samples you decline to judge. That curve, not headline accuracy, is what
tells an operations team how much human review a given threshold costs.

Usage
-----
    python -m speeddet.training.train_occupant --epochs 8 --train 12000

Then point the tower at the result:

    OnnxOccupantClassifier("models/occupant.onnx")
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------- #
# Model
# ---------------------------------------------------------------------- #
def build_model(width: int = 32):
    import torch.nn as nn

    def block(cin, cout, stride=1):
        return nn.Sequential(
            nn.Conv2d(cin, cout, 3, stride=stride, padding=1, bias=False),
            nn.BatchNorm2d(cout),
            nn.ReLU(inplace=True),
        )

    class OccupantNet(nn.Module):
        """Shared trunk, two independent binary heads.

        Belt and phone are *not* mutually exclusive and share most of the
        useful features (where the occupant is, how degraded the crop is), so
        one trunk with two heads beats two separate models on both accuracy
        and latency.
        """

        def __init__(self, w: int):
            super().__init__()
            self.stem = nn.Sequential(
                block(3, w), block(w, w, stride=2),        # 48
                block(w, w * 2), block(w * 2, w * 2, 2),   # 24
                block(w * 2, w * 4), block(w * 4, w * 4, 2),  # 12
                block(w * 4, w * 4), nn.AdaptiveAvgPool2d(1),
            )
            self.drop = nn.Dropout(0.2)
            self.belt = nn.Linear(w * 4, 2)
            self.phone = nn.Linear(w * 4, 2)

        def forward(self, x):
            import torch

            f = self.stem(x).flatten(1)
            f = self.drop(f)
            return self.belt(f), self.phone(f)

    return OccupantNet(width)


# ---------------------------------------------------------------------- #
# Data
# ---------------------------------------------------------------------- #
def _to_tensor(images: np.ndarray):
    """HWC uint8 BGR -> NCHW float32 in [0,1]. Matches the runtime path."""
    import torch

    x = images.astype(np.float32) / 255.0
    x = np.transpose(x, (0, 3, 1, 2))
    return torch.from_numpy(np.ascontiguousarray(x))


def augment_batch(x, rng):
    """Runtime augmentation on top of the generator's randomisation.

    Horizontal flip is legitimate here: the driver sits on the right in Qatar
    (LHD), but a camera on the opposite carriageway sees the mirror image, and
    both occur in a real deployment.
    """
    import torch

    if rng.random() < 0.5:
        x = torch.flip(x, dims=[3])
    # Random erasing — forces the model to use more than one cue, which is
    # what makes it survive a partially occluded sash.
    if rng.random() < 0.3:
        n, _, h, w = x.shape
        eh, ew = int(h * rng.uniform(0.1, 0.3)), int(w * rng.uniform(0.1, 0.3))
        y0 = int(rng.integers(0, max(1, h - eh)))
        x0 = int(rng.integers(0, max(1, w - ew)))
        x[:, :, y0:y0 + eh, x0:x0 + ew] = float(rng.random())
    return x


# ---------------------------------------------------------------------- #
# Metrics
# ---------------------------------------------------------------------- #
def binary_metrics(probs: np.ndarray, labels: np.ndarray,
                   positive_is: int = 1) -> Dict[str, float]:
    pred = (probs[:, positive_is] >= 0.5).astype(int)
    tp = int(((pred == 1) & (labels == 1)).sum())
    fp = int(((pred == 1) & (labels == 0)).sum())
    tn = int(((pred == 0) & (labels == 0)).sum())
    fn = int(((pred == 0) & (labels == 1)).sum())
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {
        "accuracy": (tp + tn) / max(1, len(labels)),
        "precision": prec, "recall": rec, "f1": f1,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "false_positive_rate": fp / max(1, fp + tn),
    }


def abstention_curve(probs: np.ndarray, labels: np.ndarray,
                     thresholds=(0.5, 0.6, 0.7, 0.8, 0.9, 0.95)) -> list:
    """Accuracy vs coverage. The operations-relevant curve.

    At each confidence threshold: what fraction of vehicles do we judge
    ("coverage"), and how accurate are we on those we do judge? Declining to
    judge is free; a wrong confident call is not.
    """
    conf = probs.max(axis=1)
    pred = probs.argmax(axis=1)
    out = []
    for t in thresholds:
        keep = conf >= t
        n = int(keep.sum())
        acc = float((pred[keep] == labels[keep]).mean()) if n else float("nan")
        out.append({"threshold": t, "coverage": n / max(1, len(labels)),
                    "accuracy_when_judged": acc, "judged": n})
    return out


def expected_calibration_error(probs: np.ndarray, labels: np.ndarray,
                               bins: int = 10) -> float:
    """How far predicted confidence sits from observed accuracy."""
    conf = probs.max(axis=1)
    pred = probs.argmax(axis=1)
    correct = (pred == labels).astype(float)
    ece, n = 0.0, len(labels)
    edges = np.linspace(0.5, 1.0, bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf >= lo) & (conf < hi if hi < 1.0 else conf <= hi)
        if m.sum() == 0:
            continue
        ece += (m.sum() / n) * abs(correct[m].mean() - conf[m].mean())
    return float(ece)


# ---------------------------------------------------------------------- #
# Training
# ---------------------------------------------------------------------- #
@dataclass
class TrainConfig:
    train_n: int = 12000
    val_n: int = 3000
    test_n: int = 3000
    epochs: int = 8
    batch_size: int = 128
    lr: float = 3e-3
    weight_decay: float = 1e-4
    width: int = 32
    seed: int = 0
    image_size: int = 96
    out_dir: str = "models"


def train(cfg: Optional[TrainConfig] = None, verbose: bool = True) -> Dict:
    import torch
    import torch.nn as nn

    from .synth_dataset import SynthConfig, build_dataset

    cfg = cfg or TrainConfig()
    torch.manual_seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed)
    out_dir = Path(cfg.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sc = SynthConfig(size=(cfg.image_size, cfg.image_size), seed=cfg.seed)
    if verbose:
        print(f"generating data: {cfg.train_n} train / {cfg.val_n} val / "
              f"{cfg.test_n} test ...")
    t0 = time.time()
    # Distinct seeds: the test set must not share the generator stream with
    # training, or "held out" means nothing.
    Xtr, btr, ptr = build_dataset(cfg.train_n, sc, seed=cfg.seed + 1)
    Xva, bva, pva = build_dataset(cfg.val_n, sc, seed=cfg.seed + 202)
    Xte, bte, pte = build_dataset(cfg.test_n, sc, seed=cfg.seed + 303)
    if verbose:
        print(f"  generated in {time.time() - t0:.1f}s "
              f"(belt {btr.mean():.2f}, phone {ptr.mean():.2f})")

    xtr, xva, xte = _to_tensor(Xtr), _to_tensor(Xva), _to_tensor(Xte)
    btr_t = torch.from_numpy(btr)
    ptr_t = torch.from_numpy(ptr)

    model = build_model(cfg.width)
    n_params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr,
                            weight_decay=cfg.weight_decay)
    steps = max(1, cfg.train_n // cfg.batch_size) * cfg.epochs
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=cfg.lr,
                                                total_steps=steps)
    lossf = nn.CrossEntropyLoss()
    if verbose:
        print(f"model: {n_params:,} parameters, {steps} steps")

    history = []
    step = 0
    for epoch in range(cfg.epochs):
        model.train()
        perm = torch.randperm(cfg.train_n)
        running = 0.0
        nb = 0
        for i in range(0, cfg.train_n - cfg.batch_size + 1, cfg.batch_size):
            idx = perm[i:i + cfg.batch_size]
            xb = augment_batch(xtr[idx].clone(), rng)
            lb, lp = model(xb)
            loss = lossf(lb, btr_t[idx]) + lossf(lp, ptr_t[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            if step < steps - 1:
                sched.step()
            step += 1
            running += float(loss)
            nb += 1
        val = evaluate(model, xva, bva, pva)
        history.append({"epoch": epoch + 1, "train_loss": running / max(1, nb),
                        "val_belt_acc": val["belt"]["accuracy"],
                        "val_phone_acc": val["phone"]["accuracy"]})
        if verbose:
            print(f"  epoch {epoch + 1}/{cfg.epochs}  loss {running / max(1, nb):.4f}"
                  f"  val belt {val['belt']['accuracy']:.3f}"
                  f"  val phone {val['phone']['accuracy']:.3f}")

    test = evaluate(model, xte, bte, pte)
    report = {
        "config": asdict(cfg),
        "parameters": n_params,
        "history": history,
        "test": test,
        "train_seconds": round(time.time() - t0, 1),
    }

    onnx_path = out_dir / "occupant.onnx"
    export_onnx(model, onnx_path, cfg.image_size)
    report["onnx"] = str(onnx_path)
    with open(out_dir / "occupant_report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    import torch as _t
    _t.save(model.state_dict(), out_dir / "occupant.pt")
    return report


def evaluate(model, x, belt_labels, phone_labels, batch: int = 256) -> Dict:
    import torch

    model.eval()
    pb, pp = [], []
    with torch.no_grad():
        for i in range(0, len(x), batch):
            lb, lp = model(x[i:i + batch])
            pb.append(torch.softmax(lb, dim=1).numpy())
            pp.append(torch.softmax(lp, dim=1).numpy())
    pb = np.concatenate(pb)
    pp = np.concatenate(pp)
    return {
        "belt": {
            **binary_metrics(pb, belt_labels),
            "ece": expected_calibration_error(pb, belt_labels),
            "abstention": abstention_curve(pb, belt_labels),
        },
        "phone": {
            **binary_metrics(pp, phone_labels),
            "ece": expected_calibration_error(pp, phone_labels),
            "abstention": abstention_curve(pp, phone_labels),
        },
    }


def export_onnx(model, path: Path, image_size: int = 96) -> None:
    import torch

    model.eval()
    dummy = torch.randn(1, 3, image_size, image_size)
    torch.onnx.export(
        model, dummy, str(path),
        input_names=["input"], output_names=["belt_logits", "phone_logits"],
        dynamic_axes={"input": {0: "batch"},
                      "belt_logits": {0: "batch"},
                      "phone_logits": {0: "batch"}},
        opset_version=17,
    )


def _print_report(r: Dict) -> None:
    print("\n" + "=" * 70)
    print("HELD-OUT TEST RESULTS  (synthetic domain)")
    print("=" * 70)
    for head in ("belt", "phone"):
        m = r["test"][head]
        pos = "belt worn" if head == "belt" else "phone in use"
        print(f"\n{head.upper()}  (positive class = '{pos}')")
        print(f"  accuracy  {m['accuracy']:.4f}    f1 {m['f1']:.4f}"
              f"    ECE {m['ece']:.4f}")
        print(f"  precision {m['precision']:.4f}   recall {m['recall']:.4f}"
              f"   FPR {m['false_positive_rate']:.4f}")
        print(f"  confusion tp={m['tp']} fp={m['fp']} tn={m['tn']} fn={m['fn']}")
        print("  abstention curve (confidence -> coverage / accuracy):")
        for row in m["abstention"]:
            print(f"    >={row['threshold']:.2f}  coverage {row['coverage']:6.1%}"
                  f"  accuracy {row['accuracy_when_judged']:.4f}")
    print(f"\nparameters: {r['parameters']:,}   ONNX: {r['onnx']}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", type=int, default=12000)
    ap.add_argument("--val", type=int, default=3000)
    ap.add_argument("--test", type=int, default=3000)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--width", type=int, default=32)
    ap.add_argument("--image-size", type=int, default=96)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="models")
    args = ap.parse_args(argv)

    cfg = TrainConfig(train_n=args.train, val_n=args.val, test_n=args.test,
                      epochs=args.epochs, batch_size=args.batch_size,
                      lr=args.lr, width=args.width, seed=args.seed,
                      image_size=args.image_size, out_dir=args.out)
    report = train(cfg)
    _print_report(report)
    print("\nNOTE: these figures are on the SYNTHETIC domain. They demonstrate "
          "that the pipeline trains, calibrates and exports correctly.\n"
          "They do NOT predict field accuracy — that requires labelled crops "
          "from your own cameras. See docs/report-2-data-and-models.md.")


if __name__ == "__main__":
    main()
