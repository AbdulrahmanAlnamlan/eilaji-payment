# Al-Thuraiya company profile — page updates

Updated version of the 20-page company profile. The theme, logos, colours,
header band, footers and page numbering are unchanged; only three pages differ
from the original.

**Output:** `althuraiya_profile_updated.pdf` (20 pages, A4)

## What changed

| Page | Before | After |
|------|--------|-------|
| 16 | PVC Luxe Door — frame profile drawings | **DRESSING ROOM / غرف الملابس** |
| 17 | LUX01–LUX08 door models | **KITCHEN / المطابخ** |
| 20 | Back cover, stock window-and-cat photo | Back cover, the factory building on New Industrial Area |

Pages 1–15, 18 and 19 are byte-for-byte the originals — verified by rendering
every page of both PDFs and diffing them pixel by pixel.

## How the theme is preserved

Pages 16 and 17 are not redrawn from scratch. The original PDF pages are kept
and new content is overlaid onto them, so the following come through untouched:

- the orange/slate diagonal striped band at the top
- the "Qatari Industry with German Quality" mark and Qatar Product seal (left)
- the Al-Thuraiya Plastic Factory UPVC logo (right)
- the footer bar with `www.althuraiyaupvc.qa`, the page number and `AL-Thuraiya`

Only the body area and the centre sub-brand logo are replaced. The centre logo
changes from **Al-ThuraiyaDoor** to **Al-Thuraiya Wardrobes and Kitchen**, since
these two pages now belong to that sub-brand.

Brand values used for all new elements, sampled from the original artwork:

| | |
|---|---|
| Orange | `#F05A2B` |
| Slate | `#556467` |
| Maroon | `#A32B37` |
| Body grey | `#595A5C` |
| Margins | 38 pt / 557 pt, matching the page 17 swatch strip |

## Reused artwork

Everything in `assets/` was lifted out of the original PDF, not recreated:

| File | Source |
|------|--------|
| `logo_wardrobes_kitchen.png` | Back cover (page 20), rendered at 1200 dpi and lifted off its maroon background |
| `logo_watermark.png` | Same logo, faded to 4 % for the page watermark |
| `strip_icons.png` | Feature icon row from the original page 16 |
| `strip_swatch.png` | Wood finish swatches + labels from the original page 17 |
| `backcover_photo.png` | Factory building photo from the cover, cropped to the back-cover frame (249 dpi at print size, against 103 dpi for the photo it replaces) |

## Photographs still needed

The seven photo positions are branded placeholders. Supply images and drop them
in; each slot is labelled with what it expects.

**Page 16 — Dressing room** (4 slots, each 253 × 126 pt, roughly 2:1 landscape)

1. `DRESSING ROOM 01` — walk-in / corner layout
2. `DRESSING ROOM 02` — sliding-door wardrobe
3. `DRESSING ROOM 03` — internal fittings detail
4. `DRESSING ROOM 04` — hinged-door wardrobe

**Page 17 — Kitchen** (4 slots)

1. `KITCHEN 01` — full kitchen, wide view (519 × 196 pt, wide landscape)
2. `KITCHEN 02` — island / worktop (157 × 128 pt)
3. `KITCHEN 03` — tall & wall units (157 × 128 pt)
4. `KITCHEN 04` — drawer / door detail (157 × 128 pt)

For print, supply at 300 dpi — about 1050 × 525 px for the page 16 slots,
2160 × 820 px for the kitchen hero and 650 × 535 px for the three small ones.

## Fonts

The original artwork sets Latin in **Myriad Pro** and Arabic in **GE SS Text**.
Both are licensed fonts and are only present in the source PDF as subsets, so
they cannot be used for new text. The new pages use **Noto Sans** and **Noto
Sans Arabic** as close open substitutes. If you have the original licences, a
designer can restyle the new text to the exact faces.

Note that Noto Sans Arabic carries no Latin letters, so Latin inside Arabic
sentences ("PVC") is measured and drawn with the Latin face run by run — see
`_runs()` / `draw_ar()` in the build script.

## Copy

The Arabic and English body copy on both pages is a first draft written to match
the voice of the existing profile. It should be read and approved before
printing — in particular the claims about walk-in layouts, soft-close hardware,
worktop suppliers and the survey-to-installation service.

## Rebuilding

```bash
pip install pypdf reportlab pillow arabic-reshaper python-bidi
python3 build_profile.py
```

The script reads the original PDF and writes `althuraiya_profile_updated.pdf`.
Edit the `AR_DRESS` / `EN_DRESS` / `AR_KITCHEN` / `EN_KITCHEN` strings to change
the copy, and swap `photo_slot(...)` for `c.drawImage(...)` as photos arrive.
