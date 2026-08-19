# 03-REFERENCE-DATA — real company data received during planning

Profiles of real data files the owner has shared, so module build sessions design against reality
instead of guesses. Raw files are NOT committed here (they contain supplier/employee contact details);
the owner re-supplies them at import time.

---

## Approved Suppliers List — `2.1_Approved_Suppliers_List.xlsx` (received 2026-08-18)

QMS form **ATPF-FIN-FM-03 Rev.00**, one sheet, header block + signature rows (PREPARED BY / APPROVED BY /
DATE). **71 supplier rows, account codes `ATPF-SUP-01`…`ATPF-SUP-71`, sequential, no gaps, no duplicates.**

**Columns:** S.No · Date Registered · Supplier Account Code · Supplier Name · Items · Address (country
only) · Contact Person · Landline/Mobile · Email · Credit Period (days) · CR Expiration Date · CC
Expiration Date.

**What this settles for Phase 4.1 (supplier master):**
- **Numbering scheme exists and is owned by Finance**: `ATPF-SUP-NN`. Keep it — migrate codes as-is,
  continue the sequence via `doc_sequences`.
- **Credit period is a real field**: 66 of 71 suppliers at 0 days (cash/advance); a handful at 30/60/90.
  Payment-terms column confirmed for the master + AP aging.
- **CR/CC expiry columns exist on paper but are 0% filled** (0 of 71 rows) — the strongest possible
  argument for the roadmap's "document expiry tracking with escalating alerts": the current process has
  the columns and nobody maintains them. The system must attach dated documents, not optional text cells.
- **Import-heavy supply base**: Turkey 35 · Qatar 24 · UAE/Dubai 4 · Korea 2 · KSA 2 · Germany 1 ·
  Vietnam 1 · Pakistan 1 (+2 unusable values). Two thirds of spend crosses a border → import shipments +
  landed-cost allocation (roadmap 4.4) is core procurement, not an add-on.
- **"Items" is free text needing a category table**: ~30 distinct values with spelling variants
  ("Color Masterbatch" vs "Color Master Batch", "Accessories" vs "Accessories /Hardware", "Coil Steel" vs
  "Galvanized Steel Coil"). Biggest groups: PVC Resin 11 · Machineries 5 · Accessories/Hardware 7 ·
  Glass 3 · steel coil 3. Normalise into supplier categories at import; map to item categories.
- **Registration dates**: 2020 (17) → 2023 (22) → 2025 (1); 13 rows missing the date, one stored as the
  text "Dec.2021" among real dates.

**Data-quality repairs needed at import** (do in the import script, show the owner the diff):
- 20 rows missing email, 14 missing contact person, 13 missing phone, 3 missing items/address/credit.
- One country value corrupted ("ler" — ATPF-SUP-12 Boyys, Titanium & Impact; likely Turkey), "Dubai" vs
  "UAE" inconsistent.
- Email irregularities: one address containing a space (`Ergun YILDIZ@esc.web.tr`), one cell holding two
  comma-separated addresses, one with a trailing comma → master needs multiple-contacts support
  (contact person + emails as child rows, not one cell).
- Phone formats mixed (with/without `+`, country codes inconsistent) → normalise to E.164 at import,
  same digits-folding philosophy as the customer `phoneKey`.

**Implication for the target schema** (refines `01-TARGET-ARCHITECTURE.md` suppliers entity): suppliers ×
supplier_contacts (1:N) × supplier_categories (N:M) × supplier_documents (CR, CC, ISO … with expiry +
alert escalation) + payment_terms_days + country + registered_on + account_code (unique, `ATPF-SUP-NN`).

---

## Factory costing workbook — `ALTHURAIYA_FORMUL_SPARE2.xls` (received 2026-08-18)

**This is the factory's cost engine living in Excel** — 12 sheets covering raw materials, extrusion
formulas, pricing policy, profile catalogs and lamination costs. It is the source-of-truth the ERP's
Inventory (Phase 2), Manufacturing (Phase 3), Procurement landed-cost (Phase 4) and the cost-floor
decision (`DECISIONS.md`) must absorb. Currency mix: USD for materials, QAR for outputs.

**Sheet map and what each feeds:**

1. **`1.MATERIAL COST` / `2.MATIREAL PRICE` — raw material master + landed cost + LIVE STOCK.**
   ~14 raw materials with brands that cross-reference the supplier register (PVC resin "1091",
   CALCITE AY WIN calcium carbonate, KRONOS/TI-PURE titanium, BAEROPAN MC 92577 stabiliser,
   Kaneka / LG IM 812 impact modifier, BRM masterbatch, HYUNDAI + RENOLIT FX/MX foils, NEOFLEX
   adhesive/hardener/primer, Egesembols gasket, SMG Plast soft PVC). Two price columns per material:
   original USD/ton and **"WITH EXPENS"** — a landed-cost uplift, ≈+10% on most materials (calcium
   260→286, titanium 3768→4144.8, stabiliser 2800→3080), PVC computed differently. → Confirms Phase 4.4
   landed-cost allocation is already practiced manually; the uplift basis is a business input to capture.
   **Sheet 2 also carries current raw-material stock** ("Current Quantity / Ton": PVC 24 t, calcium
   22.5 t, titanium 3.6 t, stabiliser 0) — raw-material inventory is tracked in this spreadsheet today,
   so Phase 2 should include a raw-materials warehouse from day one, not just POS goods.

2. **`4.FOURMUL PRICE` — three extrusion compound formulas (the recipes).** Per-batch kg and cost:
   - **Formula 1 (LOCAL/white)**: PVC 200 + CaCO₃ 90 + TiO₂ 11 + stabiliser 10 + impact 12 +
     **granule/regrind 40** = 363 kg batch, **3% scrap**, ≈$787/ton ≈ QR 2,871/ton.
   - **Formula 2 (COLOR local)**: PVC 200 + CaCO₃ 80 + masterbatch 1% (3 kg) + stabiliser 8.6 +
     impact 12 = 303.6 kg batch (no TiO₂, no regrind), ≈$808/ton ≈ QR 2,948/ton.
   - **Formula 3 (EXPORT)**: same composition as Formula 1.
   → These are the BOMs for Phase 3.8 extrusion batch tracking; regrind-as-input and the 3% scrap factor
   are already formalised. Formula → `compound_formulas` + `formula_lines` tables when Manufacturing lands.

3. **`3.النسبة` — the pricing ratio matrix (markup policy).** Ratio by **channel × colour × size**:
   local retail (مفرق): white 0.30 / colour 0.70 / lamination 0.70 (auxiliary 0.50/0.85); local
   wholesale-container (جملة): 0.25 / 0.60 / 0.60 (auxiliary 0.45/0.75); export container: 0.30 / 0.40 /
   0.50 (60/S60: 0.20/0.20/0.30, annotated "هذي لا توثر في السعر"); export retail: zeros. → A formal
   **margin-over-cost policy already exists** for profile bar sales. Directly relevant to the cost-floor
   decision and to POS `pos_products` pricing: floor and list prices can be *derived* (cost × (1+ratio))
   instead of hand-maintained. Confirm with owner how ratios are applied before encoding.

4. **`5–8` — per-system profile catalogs (April 2026)**: AL-RAYYAN 70 (36 TH-codes), AL-WAJBA 60 (28),
   AL-JAZEERA S60 (21), auxiliary profiles (40). White / COLORE (`TH1-C-`) / LAMINATED (`TH1-C2-`)
   variants, pieces per package, meters per package (6 m bars), **weight kg per meter**. Same vintage as
   the app's hardcoded `price-list-2026.ts` — this is its upstream source. Weight-per-meter cross-checks
   `profiles.weightPerMeter`; packaging figures feed item UoM conversions (Phase 2.4: bar ↔ package ↔ kg).

5. **`9–12` — lamination (foil) cost per profile** (dated 2023-02-01): per TH-code, foil strips consumed
   (outside FX / inside MX widths in cm per meter of profile) × foil price per m² → foil cost USD + QAR
   per meter. 45 profile-level entries. → The real cost basis for laminated variants (today the app
   treats colour/lamination as display-only `sqmDelta` badges); needed for honest cost of `TH1-C2-*`
   items and the cost floor on laminated products.

**Data-quality notes for import**: weight units mixed in text ("1530 gm", "0.300 kg", one "0.150 km");
"MASTER BATCH"/"MASTER PATCH" spelling variants; impact-modifier brand differs between sheets
(Kaneka vs LG IM 812 — likely a supplier switch, confirm which is current); one date stored as Excel
serial 44958; formulas reference NEW vs OLD price columns — confirm which column is authoritative.

**Cross-file consistency win**: material brands here match supplier rows in the approved-suppliers
register (Vinmar→PVC resin, Mars→calcium carbonate, Reda→stabilizers …) — supplier ↔ item links can be
seeded from real data on day one of Phase 4.
