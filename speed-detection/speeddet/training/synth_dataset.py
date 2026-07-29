"""Domain-randomised synthetic windshield crops for the occupant classifier.

The point is not to look photoreal — it is to reproduce the *confusions* that
make this task hard in the field, so that a model which scores well here has
actually learned something rather than memorised a fixed cue:

* **Glare** is the number-one confounder. Sunlight on a raked windshield
  produces bright diagonal streaks that look exactly like a seatbelt sash.
  The generator draws glare streaks at sash-like angles on *both* belted and
  unbelted samples, so "bright diagonal ⇒ belt" is a losing strategy.
* **Belt appearance varies**: sashes run light grey to near-black, thin to
  wide, and are often partially occluded by the A-pillar or an arm.
* **Tint** darkens everything non-linearly; in the real system near-IR is used
  to see through it, which changes the colour statistics entirely — hence the
  optional IR rendering mode.
* **Pose and scale** vary with lane position and vehicle height.
* **Degradation**: motion blur, defocus, sensor noise, compression.

Everything is seeded, so a dataset is reproducible from its config.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


@dataclass
class SynthConfig:
    size: Tuple[int, int] = (96, 96)      # (w, h) of the produced crop
    #: Probability a sample is rendered as near-IR (monochrome, tint-defeating)
    ir_fraction: float = 0.35
    #: Probability of adding glare streaks. High on purpose.
    glare_prob: float = 0.55
    max_glare_streaks: int = 3
    #: Probability the belt is partially occluded (arm, pillar, shadow).
    belt_occlusion_prob: float = 0.35
    #: Probability the whole crop is heavily degraded (far vehicle, bad frame).
    heavy_degradation_prob: float = 0.20
    seed: int = 0


class CabinRenderer:
    """Renders one labelled windshield crop."""

    def __init__(self, config: Optional[SynthConfig] = None) -> None:
        self.cfg = config or SynthConfig()

    # ------------------------------------------------------------------ #
    def render(self, rng: np.random.Generator, belt: bool,
               phone: bool) -> np.ndarray:
        import cv2

        w, h = self.cfg.size
        # Render at 2x then downsample — antialiasing matters at these sizes.
        W, H = w * 2, h * 2
        ir = rng.random() < self.cfg.ir_fraction

        img = self._glass(rng, W, H, ir)
        occ_box = self._occupant(rng, img, ir)
        if belt:
            self._sash(rng, img, occ_box, ir)
        if phone:
            self._phone(rng, img, occ_box, ir)
        if rng.random() < self.cfg.glare_prob:
            self._glare(rng, img, ir)
        img = self._geometry(rng, img)
        img = self._degrade(rng, img)

        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
        return np.clip(img, 0, 255).astype(np.uint8)

    # ------------------------------------------------------------------ #
    def _glass(self, rng, W, H, ir) -> np.ndarray:
        """Tinted glass with a reflected-sky gradient."""
        import cv2

        base = rng.integers(18, 70)
        img = np.full((H, W, 3), base, dtype=np.float32)
        if not ir:
            # Slight blue/green cast typical of automotive glass.
            img[..., 0] *= rng.uniform(1.0, 1.25)
            img[..., 1] *= rng.uniform(0.95, 1.1)
        # Reflected sky: brighter toward the top, random strength and slope.
        grad = np.linspace(rng.uniform(0.4, 1.6), 0.0, H, dtype=np.float32)
        grad = grad[:, None] * rng.uniform(20, 90)
        img += grad[..., None]
        # Occasional broad reflection blob (buildings, other vehicles).
        if rng.random() < 0.4:
            cx, cy = rng.integers(0, W), rng.integers(0, H // 2)
            r = rng.integers(W // 6, W // 2)
            overlay = img.copy()
            cv2.circle(overlay, (int(cx), int(cy)), int(r),
                       (float(rng.integers(90, 180)),) * 3, -1)
            img = cv2.addWeighted(overlay, rng.uniform(0.1, 0.35),
                                  img, 1 - rng.uniform(0.1, 0.35), 0)
        return img

    def _occupant(self, rng, img, ir) -> Tuple[int, int, int, int]:
        """Torso + head. Returns the torso box the sash must cross."""
        import cv2

        H, W = img.shape[:2]
        # Driver sits right-of-centre in this view; vary position and size.
        cx = int(W * rng.uniform(0.50, 0.82))
        top = int(H * rng.uniform(0.18, 0.42))
        half_w = int(W * rng.uniform(0.14, 0.26))
        x1, x2 = max(0, cx - half_w), min(W, cx + half_w)
        y1, y2 = top, H

        tone = rng.integers(20, 95)
        colour = (float(tone), float(tone), float(tone)) if ir else (
            float(tone * rng.uniform(0.8, 1.2)),
            float(tone * rng.uniform(0.8, 1.2)),
            float(tone * rng.uniform(0.8, 1.2)))
        cv2.rectangle(img, (x1, y1), (x2, y2), colour, -1)

        # Head
        head_r = int((x2 - x1) * rng.uniform(0.28, 0.40))
        head_c = (int((x1 + x2) / 2 + rng.integers(-4, 5)), int(y1 + head_r * 0.6))
        skin = rng.integers(60, 165)
        head_col = (float(skin),) * 3 if ir else (
            float(skin * rng.uniform(0.7, 0.9)),
            float(skin * rng.uniform(0.8, 1.0)),
            float(skin * rng.uniform(0.9, 1.15)))
        cv2.circle(img, head_c, head_r, head_col, -1)
        return (x1, y1, x2, y2)

    def _sash(self, rng, img, box, ir) -> None:
        """Seatbelt across the torso — the positive cue, deliberately varied."""
        import cv2

        x1, y1, x2, y2 = box
        H, W = img.shape[:2]
        # Belts are not always bright. Dark belts on dark clothing are the
        # hard negative-looking positives.
        bright = rng.integers(70, 245)
        col = (float(bright),) * 3 if ir else (
            float(bright * rng.uniform(0.85, 1.0)),
            float(bright * rng.uniform(0.85, 1.0)),
            float(bright * rng.uniform(0.85, 1.05)))
        thickness = max(2, int((x2 - x1) * rng.uniform(0.10, 0.20)))

        # Runs shoulder -> opposite hip; direction varies with driver side.
        if rng.random() < 0.8:
            p0 = (int(x1 + (x2 - x1) * rng.uniform(0.05, 0.25)), int(y2))
            p1 = (int(x2 - (x2 - x1) * rng.uniform(0.05, 0.30)),
                  int(y1 + (y2 - y1) * rng.uniform(0.10, 0.35)))
        else:
            p0 = (int(x2 - (x2 - x1) * rng.uniform(0.05, 0.25)), int(y2))
            p1 = (int(x1 + (x2 - x1) * rng.uniform(0.05, 0.30)),
                  int(y1 + (y2 - y1) * rng.uniform(0.10, 0.35)))
        cv2.line(img, p0, p1, col, thickness, cv2.LINE_AA)

        if rng.random() < self.cfg.belt_occlusion_prob:
            # Occlude part of the sash with an arm / pillar shadow.
            ox = int(rng.uniform(min(p0[0], p1[0]), max(p0[0], p1[0])))
            oy = int(rng.uniform(min(p0[1], p1[1]), max(p0[1], p1[1])))
            ow = int((x2 - x1) * rng.uniform(0.15, 0.40))
            cv2.rectangle(img, (ox - ow // 2, oy - ow // 2),
                          (ox + ow // 2, oy + ow // 2),
                          (float(rng.integers(15, 60)),) * 3, -1)

    def _phone(self, rng, img, box, ir) -> None:
        import cv2

        x1, y1, x2, y2 = box
        # Held near the ear or low near the lap/wheel.
        near_ear = rng.random() < 0.6
        pw = int((x2 - x1) * rng.uniform(0.14, 0.26))
        ph = int(pw * rng.uniform(1.4, 2.1))
        if near_ear:
            px = int(x1 - pw * 0.3 + rng.integers(-4, 8)) if rng.random() < 0.5 \
                else int(x2 - pw * 0.7 + rng.integers(-8, 4))
            py = int(y1 + (y2 - y1) * rng.uniform(0.05, 0.30))
        else:
            px = int((x1 + x2) / 2 + rng.integers(-10, 10))
            py = int(y1 + (y2 - y1) * rng.uniform(0.45, 0.75))
        glow = rng.integers(120, 255)
        col = (float(glow),) * 3 if ir else (
            float(glow * rng.uniform(0.85, 1.1)),
            float(glow * rng.uniform(0.8, 1.05)),
            float(glow * rng.uniform(0.6, 0.95)))
        cv2.rectangle(img, (px, py), (px + pw, py + ph), col, -1)

    def _glare(self, rng, img, ir) -> None:
        """Bright streaks — including at seatbelt angles, on purpose.

        This is what stops the model learning "bright diagonal ⇒ belt".
        """
        import cv2

        H, W = img.shape[:2]
        n = int(rng.integers(1, self.cfg.max_glare_streaks + 1))
        overlay = img.copy()
        for _ in range(n):
            angle = rng.uniform(20, 70) * (1 if rng.random() < 0.5 else -1)
            length = rng.uniform(0.5, 1.4) * W
            cx, cy = rng.uniform(0, W), rng.uniform(0, H)
            dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
            p0 = (int(cx - dx * length / 2), int(cy - dy * length / 2))
            p1 = (int(cx + dx * length / 2), int(cy + dy * length / 2))
            thick = int(rng.integers(2, max(3, W // 8)))
            val = float(rng.integers(170, 255))
            cv2.line(overlay, p0, p1, (val, val, val), thick, cv2.LINE_AA)
        k = int(rng.integers(3, 15)) | 1
        overlay = cv2.GaussianBlur(overlay, (k, k), 0)
        alpha = rng.uniform(0.15, 0.6)
        img[:] = cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0)

    def _geometry(self, rng, img) -> np.ndarray:
        """Small perspective + rotation: vehicles are not axis-aligned."""
        import cv2

        H, W = img.shape[:2]
        j = rng.uniform(0.0, 0.10)
        src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
        dst = np.float32([
            [W * rng.uniform(0, j), H * rng.uniform(0, j)],
            [W * (1 - rng.uniform(0, j)), H * rng.uniform(0, j)],
            [W * (1 - rng.uniform(0, j)), H * (1 - rng.uniform(0, j))],
            [W * rng.uniform(0, j), H * (1 - rng.uniform(0, j))],
        ])
        M = cv2.getPerspectiveTransform(src, dst)
        img = cv2.warpPerspective(img, M, (W, H), borderMode=cv2.BORDER_REPLICATE)
        ang = rng.uniform(-7, 7)
        R = cv2.getRotationMatrix2D((W / 2, H / 2), ang, 1.0)
        return cv2.warpAffine(img, R, (W, H), borderMode=cv2.BORDER_REPLICATE)

    def _degrade(self, rng, img) -> np.ndarray:
        import cv2

        heavy = rng.random() < self.cfg.heavy_degradation_prob
        # Motion blur along a random direction (vehicle moving, long exposure).
        if rng.random() < (0.7 if heavy else 0.35):
            n = int(rng.integers(3, 13 if heavy else 8)) | 1
            kern = np.zeros((n, n), np.float32)
            if rng.random() < 0.5:
                kern[n // 2, :] = 1.0
            else:
                np.fill_diagonal(kern, 1.0)
            kern /= kern.sum()
            img = cv2.filter2D(img, -1, kern)
        if rng.random() < (0.6 if heavy else 0.3):
            k = int(rng.integers(3, 9 if heavy else 5)) | 1
            img = cv2.GaussianBlur(img, (k, k), 0)
        # Exposure / contrast
        img = img * rng.uniform(0.55, 1.5) + rng.uniform(-30, 30)
        # Sensor noise
        img = img + rng.normal(0, rng.uniform(2, 18 if heavy else 9), img.shape)
        img = np.clip(img, 0, 255)
        # Compression artefacts
        if rng.random() < 0.4:
            q = int(rng.integers(25, 85))
            ok, enc = cv2.imencode(".jpg", img.astype(np.uint8),
                                   [int(cv2.IMWRITE_JPEG_QUALITY), q])
            if ok:
                img = cv2.imdecode(enc, cv2.IMREAD_COLOR).astype(np.float32)
        return img


def build_dataset(n: int, config: Optional[SynthConfig] = None,
                  seed: int = 0, belt_rate: float = 0.62,
                  phone_rate: float = 0.28) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate ``n`` crops.

    Class balance is deliberately *not* 50/50 — real traffic is mostly belted
    and mostly not on the phone, and a model tuned on a balanced set will be
    badly calibrated when deployed. Defaults approximate observed compliance:
    ~62% visibly belted in the crop, ~28% phone. Tune to your own site.

    Returns ``(images, belt_labels, phone_labels)`` with labels in {0, 1}
    where 1 means "belt worn" and 1 means "phone in use".
    """
    cfg = config or SynthConfig()
    renderer = CabinRenderer(cfg)
    rng = np.random.default_rng(seed)
    w, h = cfg.size
    images = np.zeros((n, h, w, 3), dtype=np.uint8)
    belts = np.zeros(n, dtype=np.int64)
    phones = np.zeros(n, dtype=np.int64)
    for i in range(n):
        belt = bool(rng.random() < belt_rate)
        phone = bool(rng.random() < phone_rate)
        images[i] = renderer.render(rng, belt, phone)
        belts[i] = int(belt)
        phones[i] = int(phone)
    return images, belts, phones
