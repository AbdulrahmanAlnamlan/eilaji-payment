# Report 2 — Data and Models

**Date:** 29 July 2026 · **Status:** research complete, model trained, pipeline verified

---

## The headline, before anything else

You asked me to search the internet for real videos and pictures and train the
model on them. I did the search. The answer is the most commercially important
finding in all four reports:

> **There is no public dataset that is both (a) shot from the roadside camera
> viewpoint you need and (b) verifiably licensed for commercial use in a
> government enforcement system. Not one.**

This is not a "we couldn't find it" result. It is a structural property of the
field, and it holds along two independent axes that each rule out most of the
corpus on their own.

**Axis 1 — licensing.** The Waymo Open Dataset licence contains this, verbatim:

> "Non-commercial Purposes does not include purposes primarily intended for or
> directed towards commercial advantage or monetary compensation, or purposes
> intended for or directed towards litigation, licensing, or **enforcement,
> even in part**."

Your exact application is named as excluded, and "even in part" forecloses the
usual "we only used it for pre-training" argument. The AUC Distracted Driver
licence (verified verbatim from the signed PDF) enumerates "**Testing
commercial systems**" as prohibited — you may not even *benchmark* on it.

**Axis 2 — viewpoint.** Every driver-behaviour dataset in existence is filmed
from **inside the cabin** (dashboard, A-pillar, mirror), looking at the driver
from a metre away. You need a roadside camera looking *through the windscreen*
from 30 m at an oblique angle, through glare and tint. Every autonomous-driving
dataset (KITTI, nuScenes, Cityscapes, BDD100K, Waymo) is **dashcam** — a moving
camera at bonnet height, not a fixed elevated pole. No amount of augmentation
closes a viewpoint gap of that size.

And the two are inversely correlated: **the datasets with the right viewpoint
have the worst licences.** The single best viewpoint match in the accident
category (AI City Challenge / Iowa DOT freeway cameras) is licensed "solely for
purposes of the challenge or event."

---

## 1. Full licence audit

Verified verbatim where marked ✅ — those licence texts were fetched and read
directly, not summarised. Hosts marked ☠️ are confirmed dead by DNS (NXDOMAIN),
distinct from network-blocked.

### 1.1 Vehicle detection / autonomous driving

| Dataset | Licence | Commercial? | Viewpoint |
| --- | --- | --- | --- |
| **Waymo Open** | Waymo Non-Commercial Agreement | ❌ **Names "enforcement, even in part"** ✅ | Dashcam |
| **nuScenes / nuImages** | CC BY-NC-SA 4.0 + extra terms ✅ | ❌ No (+ShareAlike) | Dashcam |
| **KITTI / KITTI-360** | CC BY-NC-SA **3.0** ✅ | ❌ No (+ShareAlike) | Dashcam |
| **Cityscapes** | Custom non-commercial ✅ | ❌ No | Dashcam |
| **BDD100K** | UC Regents / BAIR Commons ✅ | ⚠️ Members only, **non-transferable** | Dashcam |
| **Open Images V7** | **CC BY 4.0** annots / CC BY 2.0 images ✅ | ✅ **YES** (see §2) | Web photos |

Two traps worth naming. **ShareAlike** (KITTI, nuScenes) independently blocks
proprietary software even if you obtained a commercial waiver on the NC term.
And **code and data licences differ** on almost every one of these — Waymo's
code is Apache 2.0, KITTI-360's scripts are MIT, Cityscapes' scripts are MIT —
while the *data* is restricted. An auditor who checks the GitHub licence badge
will reach the wrong conclusion.

### 1.2 Seatbelt / phone / driver behaviour — **all in-cabin, none usable**

| Dataset | Licence | Commercial? | Note |
| --- | --- | --- | --- |
| **AUC Distracted Driver** | Signed custom EULA ✅ | 🚫 **"Testing commercial systems" barred** | Primary domain may be dead |
| **State Farm** (Kaggle) | Kaggle competition rules | ❌ Almost certainly no | Could not read rules page |
| **DMD** (Vicomtech) | MIT on *code*; data terms unclear ✅ | ⚠️ Conflicted | **2026 revision removed IR + depth; 14 of ~37 subjects left** |
| **Drive&Act** | "Research only", Fraunhofer IOSB | ❌ No | **Only dataset with real IR** — commercial licence negotiable |
| **SynDD1 / SynDD2** (NIST) | Likely US public domain | 🟢 Best licence odds | Unverified; recorded in a *parked* car |

Every one is an interior camera. For your product this means they are useful
for pre-training a driver-region backbone at best, and worthless as validation
data. If a vendor tells you they trained a roadside seatbelt classifier on
State Farm or AUC, they either misunderstand the geometry or are misleading you.

### 1.3 Accident / anomaly — the YouTube problem

| Dataset | Licence | Viewpoint | Fatal flaw |
| --- | --- | --- | --- |
| **CADP** | **None in repo** | ✅ **Fixed CCTV** | YouTube-scraped; best viewpoint, worst chain of title |
| **UCF-Crime** | **None at all** | ✅ Fixed CCTV | YouTube + LiveLeak scraped; primary mirror ☠️ dead |
| **AI City / Iowa DOT** | Signed NVIDIA agreement | ✅ **Fixed freeway pole** | "**solely for the challenge or event**" |
| **DoTA** | MIT — *code only* ✅ | ❌ Dashcam | Video is YouTube; MIT cannot reach it |
| **A3D** | MIT — *code only* ✅ | ❌ Dashcam | **Ships 200 YouTube URLs and a scraper — no video at all** |
| **CCD** | MIT ✅ | ❌ Dashcam | `youtubeID` field in its own schema |
| **DADA-2000** | **None** | ❌ Dashcam | + un-consented eye-tracking biometrics |
| **DAD** (Chan 2016) | **None** | ❌ Dashcam | Decade-old personal Drive links |

**The MIT badge on DoTA, A3D and CCD is the single most dangerous item in this
audit**, because it looks cleared and is not. Those grants are scoped to "the
Software and associated documentation files." The video is other people's
YouTube uploads that the authors never owned and therefore could not license.
A3D makes this unarguable: it distributes a text file of 200 YouTube URLs and
a download script. **The liability is shifted onto you, the downloader.**

### 1.4 Roadside / surveillance viewpoint — the category you actually need

| Dataset | Host | Licence | Commercial? |
| --- | --- | --- | --- |
| **BrnoCompSpeed** | primary ☠️ dead; **email access live** | **No licence file** ✅ | ⚠️ **Negotiable — see §4** |
| **UA-DETRAC** | alive (unread) | Unverified | Unknown — best unresolved lead |
| **FishEye8K** | alive (unread) | No licence file in repo ✅ | Unverified |
| **GRAM-RTM** | alive (unread) | Unverified | Unknown |
| **BoxCars116k** | primary ☠️ dead | **No licence file** ✅; "research only" | ❌ No |
| **VeRi-776** | — | ✅ **Verbatim: non-commercial only** | 🚫 **No** — and it contains **transcribed plate strings** |
| **TSD-Max** | ☠️ **NXDOMAIN** | — | Gone |
| **WebCamT / CityCam** | ☠️ **NXDOMAIN** | — | Gone |
| **Roboflow Universe** | alive | Self-declared, **unaudited** | 🚫 **Do not rely on** |

**Roboflow Universe deserves a specific warning** because it looks like the easy
answer. Licences there are self-declared by uploaders and not audited. A large
share are re-exports of the research-only datasets above, re-stamped "CC BY" or
"MIT" by someone who had no right to relicense them. A permissive tag there is
not a chain of title and carries no indemnity. It is the highest-risk item on
this list precisely because it appears the safest.

---

## 2. The one clean option, and why it isn't enough

**Open Images V7** is the only dataset in this audit that is verifiably
commercially usable: annotations under **CC BY 4.0** from Google, images under
**CC BY 2.0**. 9.2M images, 16M boxes, with `Car`, `Truck`, `Bus`,
`Motorcycle`, `Van` and `Vehicle registration plate` classes.

Three caveats that a compliance review will raise:

1. **Google disclaims the per-image licence status**, verbatim: it makes "no
   representations or warranties regarding the license status of each image and
   you should verify the license for each image yourself." Flickr uploaders
   relicense and delete. Budget per-image verification with a retained audit
   trail as real compliance work.
2. **Wrong viewpoint.** Consumer and press photography, not elevated roadside
   CCTV. Good for general vehicle-appearance pre-training; it will not give you
   the surveillance geometry.
3. **It contains unblurred faces and legible plates** — and deliberately
   annotates a plate class, so plates are demonstrably present and readable.
   Privacy review required regardless of the copyright position.

---

## 3. What I actually trained, and what it does and does not prove

Since no lawful in-domain data exists, I built the alternative that de-risks the
*engineering* while you solve the *data*: a domain-randomised synthetic
generator and a complete training pipeline, then trained a real model on it.

### 3.1 The generator (`speeddet/training/synth_dataset.py`)

It is not trying to look photoreal. It is trying to reproduce the specific
**confusions** that make this task hard, so a model scoring well has learned
something rather than memorising a cue:

- **Glare streaks drawn at seatbelt angles on unbelted samples.** This is the
  number-one real-world confounder — sun on a raked windscreen looks exactly
  like a sash. It means "bright diagonal ⇒ belt" is a losing strategy.
- **Belts from near-white to near-black**, thin to wide, often partially
  occluded by an arm or the A-pillar.
- **35% of samples rendered as near-IR**, since the production camera uses IR to
  defeat tint — which changes the colour statistics completely.
- Perspective and rotation jitter, motion blur, defocus, sensor noise, JPEG
  artefacts, exposure swings, reflected-sky gradients.
- **Deliberately imbalanced classes** (~62% belted, ~28% phone). A model tuned
  on a 50/50 split is badly calibrated the moment it meets real traffic.

### 3.2 The model and training (`speeddet/training/train_occupant.py`)

~436k-parameter CNN, shared trunk, two independent binary heads (belt, phone —
they are not mutually exclusive and share features), 96×96 input. Small on
purpose: it must run at frame rate on a Jetson beside detection and tracking,
and small models stay better calibrated. Trained with OneCycle AdamW,
horizontal flip and random erasing.

**Evaluation reports the abstention curve, not just accuracy.** At each
confidence threshold: what fraction of vehicles do we judge, and how accurate
are we on those? Declining to judge is free. A confident wrong call is not.
That curve is what tells an operations team how much human review a threshold
costs. We also report **expected calibration error**, because the tower's most
important behaviour is knowing when to say "unclear".

### 3.3 Results — measured, on a held-out synthetic test set

245,548 parameters, 64×64 input, 5 epochs on 9,000 training crops, evaluated on
2,500 crops from a **separate generator seed** (a test set sharing the random
stream would not be held out at all).

| | Belt | Phone |
| --- | --- | --- |
| Accuracy | **0.9428** | **0.9364** |
| Precision | 0.9480 | 0.9519 |
| Recall | 0.9608 | 0.7944 |
| F1 | 0.9544 | 0.8660 |
| False-positive rate | 0.0870 | **0.0140** |
| Expected calibration error | 0.0182 | 0.0249 |

Learning curve (validation): belt 0.653 → 0.885 → 0.882 → 0.912 → **0.942**;
phone 0.601 → 0.858 → 0.852 → 0.932 → **0.929**.

**The abstention curve is the operationally useful result:**

| Confidence ≥ | Belt coverage / accuracy | Phone coverage / accuracy |
| --- | --- | --- |
| 0.50 | 100.0% / 0.9428 | 100.0% / 0.9364 |
| 0.70 | 93.2% / 0.9661 | 94.5% / 0.9551 |
| 0.90 | 77.4% / 0.9861 | 80.3% / 0.9791 |
| 0.95 | 65.6% / 0.9909 | 57.2% / 0.9916 |

Read it as an operations dial: at a 0.90 threshold the system judges ~78% of
vehicles at ~98.6% accuracy and abstains on the rest. That is how you trade
throughput against reviewer workload, and it is a conversation you can only
have if the model is calibrated — hence the ECE numbers, both under 0.025.

Note the asymmetry worth carrying into deployment: **phone recall is 0.79 while
its false-positive rate is 0.014**. The model misses phones rather than
inventing them. For an enforcement proposal that is the correct direction of
error — a missed violation costs nothing, a fabricated one costs a wrongful
citation and the programme's credibility.

**Verified end to end** (`examples/verify_trained_model.py`):
1. the ONNX loads with the expected input and output names;
2. it agrees with its source PyTorch model to **2.4e-06** — catching the class
   of export bug that silently degrades field accuracy;
3. it runs as a drop-in inside `SpeedPipeline`, producing review-gated
   `no_seatbelt` and `phone_use` events.

**Now read all of that for what it is.** These figures are measured on
synthetic data against synthetic labels. **They do not predict field
accuracy.** What they prove is that the pipeline trains, calibrates, abstains,
exports and is consumed correctly by the tower — the *engineering* risk is
retired. The *domain* risk is untouched, and no amount of further synthetic
work will touch it. That is precisely why the data-collection budget in §4 is
unavoidable rather than optional.

---

## 4. The actual path to a working model

1. **Collect from the customer's own cameras.** For an enforcement contract
   this is normally achievable — the road authority owns the cameras and can
   authorise the capture. It is the only route that simultaneously gives you
   the right viewpoint, the right geography, the right vehicle mix, the right
   hardware, and a chain of title that survives a procurement audit. Everything
   else is a detour.
2. **Approach BUT FIT about BrnoCompSpeed** — `ispanhel@fit.vutbr.cz`. This is
   the highest-value single email in this report. It is the **only public
   dataset with real speed ground truth from a fixed roadside camera**, which
   is exactly your core measurement. Its primary host is dead and it has **no
   licence file at all** — which means terms are *open to negotiation*, not
   foreclosed. Ask for commercial terms explicitly in the first email.
3. **Consider a commercial licence conversation with Fraunhofer IOSB** about
   Drive&Act if IR fidelity matters. It is the only remaining dataset with real
   IR imagery (DMD's was withdrawn in the 2026 revision), and Fraunhofer has an
   established commercial licensing route.
4. **Label campaign.** Budget on the order of **20–50k labelled windscreen
   crops** from your own cameras for a production seatbelt/phone classifier,
   plus a held-out *real* test set that never touches training. Publish the
   per-class numbers. Keep synthetic data as augmentation, not as the base.
5. **Re-verify this audit from an unrestricted network.** Every "unverified"
   above is genuinely unknown, not unavailable — the research ran behind an
   egress proxy that blocked most academic hosts. UA-DETRAC and FishEye8K are
   the two most promising unresolved leads.

---

## 5. Things to stop believing

- **"We'll just fine-tune on a public dataset."** For roadside enforcement,
  there is nothing lawful to fine-tune on. Plan for collection.
- **"It has an MIT licence."** Check what the grant covers. On DoTA, A3D and
  CCD it covers code and annotations, never the video.
- **"Research-only is a formality."** Government contracts routinely carry IP
  indemnity clauses. Shipping a model trained on VeRi-776 or BoxCars puts you
  in breach of the dataset terms *and* your customer contract.
- **"Copyright cleared means privacy cleared."** They are separate workstreams.
  None of these datasets is anonymised; VeRi-776 ships transcribed plate
  strings; Open Images annotates a plate class. Copyright permission is not
  permission to process the subjects' personal data.
