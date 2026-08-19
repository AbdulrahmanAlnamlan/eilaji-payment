# DECISIONS — architectural and business decision log

One entry per decision, newest first. Format: date · decision · reasoning · consequences.

---

## 2026-08-19 — ERP front-end direction settled (owner decision)

Mockup canvas ("Al-Thuraiya ERP Screens" artifact) approved as the direction: the ERP extends the
shipped design tool's UI — same tokens, components and density — with new modules as role-gated sidebar
groups. Owner picked and confirmed a **brand-crimson shell**: sidebar and shop-floor/receiving top bars
in `#822626` (borders `#671e1e`, raised chips `#9a2f2f`), active nav rows white with crimson text
(contrast ≈ 9.4:1). Buttons, links and badges keep the app's existing blue primary — a full primary-color
re-theme was not requested. Three UX modes confirmed: dense desktop (office), large-touch Arabic-first RTL
tablet (shop floor + warehouse, offline-tolerant), mobile approvals. Eight screens drawn: inventory items,
work orders, production Gantt (Sun–Thu calendar), cutting plan (kerf 3 mm, min remnant 500 mm — pending
Phase 2 confirmation), HR employee file with document-expiry escalation, GRN receiving, shop-floor
terminal, mobile approvals incl. the price-floor override flow.

---

## 2026-08-18 — RESOLVED: Odoo never went live; the newer markup matrix is current (owner)

`COSTING_AND_PRODUTCS.xlsx` (see `03-REFERENCE-DATA.md`) is an Odoo implementation workbook, but the
owner confirms **Odoo never went live** — the sheets are prepared data only. Consequences: the custom-ERP
path stands unchanged; there is no live Odoo database to import from or integrate with; Phase 2/3 seed
the item master, UoM conversions, compound recipes and per-profile BOMs directly from this workbook
(the best-organised data available — its SKU scheme `RM-*`/`CPD-*`/`TH1-*` and purchase/BoM/stock UoM
split are adopted as the starting design for `items`).

Owner also confirms: **the newer workbook's markup matrix is the current pricing policy** (local retail
white 0.5, color/lamination 0.8; container 0.4/0.7; export 0.3/0.4/0.5; auxiliary 0.7/1.0). The older
FORMUL-file النسبة sheet is superseded. Derived pricing / cost-floor work uses the newer matrix.

---

## 2026-08-18 — Cost-price floor on quotation pricing (owner decision)

**Decision (owner):** Component cost prices (Georgian bars, hardware sets, profiles, glass, …) will be
maintained in the system, the costing engine computes each window's true cost from them, and that computed
cost is a **minimum price**: a salesman cannot save a quote line priced below its cost. Below cost = the
factory loses money.

**What this changes from the audited behaviour:**
- Answers `00-AUDIT.md` §6 Q2: the discount-cap bypass (salesman typing any unit price) **is a hole to
  close**, not intended freedom. Salesman-entered pricing stays, but gains a server-enforced lower bound.
- Upgrades the §4.7 engine bugs (tilt hardware priced 0, Georgian bars free) from "profit-report accuracy"
  to **prerequisite**: a floor computed from a wrong cost is a wrong floor. They must be fixed, and the
  missing components must get real, editable cost prices, before enforcement switches on.
- `bom_rates.hardwarePrices` (display-name-keyed jsonb) becomes untenable — component costs become
  first-class editable data (normalised rate rows), pulled forward from the Phase 2 `bom_rates`
  replacement into Phase 1.

**Implementation shape (Phase 1, roadmap item 1.10 expanded):**
1. Add cost entries for every component the engine emits (incl. Georgian bar per-meter cost, tilt hardware
   set, restrictor stay) — editable in the BOM-rates admin screen; engine refuses silent `?? 0` fallbacks
   (an unpriced component becomes a visible "cost unknown" flag, mirroring the POS `costPrice null =
   UNKNOWN` rule).
2. Fix the engine bugs behind the characterization tests (1.1).
3. Server-side floor check in quote item create/update: entered line price vs computed line cost.
4. Scope note: the floor can only apply where the engine computes a cost — fabricated uPVC items
   (`isFabricated = true`). Wooden doors, dressing rooms and kitchens have **no computed cost by design**
   ("cost is UNKNOWN, never guessed at zero") — no floor is possible there until those products get cost
   data. Flagged to the owner.

**Sub-decisions — CONFIRMED by owner 2026-08-18:**
- a) **Managers can override.** Sales/staff hard-blocked; manager, factory_manager and admin may save
  below the floor, with actor + reason recorded in the activity log.
- b) **Show the minimum price to the salesman** ("minimum price for this item: X QAR") — the floor number
  is visible; the cost breakdown stays behind `canSeeCost`. Note: since the floor = cost × (1 + margin),
  the displayed number does not directly reveal raw cost.
- c) **Floor = cost × (1 + `minProfitPercent`).** Stricter than the audit recommendation, chosen
  deliberately: salesmen can never quote inside the margin band; `minProfitPercent` (report_settings)
  becomes an enforcement input, not just a warning threshold. Its float column type is fixed in 1.4.
- d) **Flag on next edit AND produce a one-time report** of every open quote currently priced below the
  new floor, for manual owner review. Issued documents are never mutated.

**Consequences:** pricing formula + permission model change (protected areas — explicitly owner-initiated
here); roadmap 1.10 re-scoped from "bug fixes" to "cost integrity + floor enforcement"; component cost
maintenance becomes a real admin workflow (who maintains it — decide with (a)–(d)).

---

## 2026-08-18 — Phase 0 baseline

Audit, working guide, target architecture and roadmap produced from the 2026-08-18 snapshot
(`docs/00-AUDIT.md`, `CLAUDE.md`, `docs/01-TARGET-ARCHITECTURE.md`, `docs/02-ROADMAP.md`). Strangler-fig
strategy adopted: generalise `pos_products`/`pos_stock_movements` into the item master and stock ledger;
never build parallel tables; every ledger append-only with derived balances.
