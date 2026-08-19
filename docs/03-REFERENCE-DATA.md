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
