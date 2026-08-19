# 02-ROADMAP — phased plan with resumable status

Companion to `01-TARGET-ARCHITECTURE.md`. Every phase is independently shippable and useful on its own.
A future session resumes by scanning the Status columns top-to-bottom and picking the first non-done item
whose dependencies are met.

Status vocabulary: `todo` · `in-progress` · `blocked(<on what>)` · `awaiting-decision` · `done(<date>)`.
Effort: **S** ≤ 1 session · **M** 2–4 sessions · **L** 5–10 · **XL** 10+.
🔶 = needs a business decision from the owner before or during the item (listed in §11).

---

## Phase 0 — audit & plan *(this delivery)*

| # | Item | Effort | Status |
|---|---|---|---|
| 0.1 | `docs/00-AUDIT.md` — verified defect audit | M | done(2026-08-18) |
| 0.2 | `CLAUDE.md` — working guide | S | done(2026-08-18) |
| 0.3 | `docs/01-TARGET-ARCHITECTURE.md` + `docs/02-ROADMAP.md` | M | done(2026-08-18) |
| 0.4 | Owner reviews Phase 0 + answers `00-AUDIT.md` §6 questions | — | awaiting-decision 🔶 |

## Phase 1 — defect fixes (nothing below is safe until these land)

Sequenced — the order matters (tests before everything; migrations before FKs; snapshot before Manufacturing).

| # | Item | Deps | Effort | Status |
|---|---|---|---|---|
| 1.1 | Vitest + characterization tests golden-filing `fabrication.ts`, `bom.ts`, `quote-cost.ts`, `quoteMoney.ts`, `posMoney.ts`, `billedDims()` against real fixtures (incl. arch tops, Georgian bars, tilt, door leaves, dressing L/U/full, mixed pricing). Keep the e2e scripts. | — | M | todo |
| 1.2 | Migration toolchain: `drizzle-kit generate`+`migrate`, baseline current live schema as `0000`, fence `push` to local dev, fix broken `post-merge.sh` filter (`--filter db` → `@workspace/db`) | 1.1 | S | todo 🔶 (maintenance window) |
| 1.3 | Orphan scan on live DB (SQL in `00-AUDIT.md` §2.2) → repair plan → FK migrations in batches with explicit `onDelete` (children of quotes: cascade; actor columns: set null; POS; catalog). Index every FK + filter column — `quote_items.quote_id` first. Unique: `profiles(system_id,code)`, `pos_sales.share_token`, `design_requests.converted_quote_id` | 1.2 | M | todo 🔶 (orphan counts) |
| 1.4 | `numeric` conversion: `bom_rates` 9 cols + `report_settings.min_profit_percent`; goldens prove output unchanged | 1.1, 1.2 | S | todo |
| 1.5 | Fabrication/BOM/rate **snapshot** persisted per quote item at final approval; server reports + client PDFs render snapshot when present, recompute for historical quotes. Byte-identical proof via 1.1 before the client switches | 1.1, 1.2 | M | todo 🔶 (snapshot timing) |
| 1.6 | Boot seeders → explicit idempotent logged commands (`db-seed`, `db-backfill`); boot becomes read-only; interval jobs get a single-instance guard (advisory lock) | 1.2 | S–M | todo |
| 1.7 | `lib/authz.ts`: one table-driven policy module (roles × actions), per-request cached user context (kills the 2–4× `getCurrentUser` round-trips); routes migrate guard-by-guard; role becomes a checked enum | 1.1 | M | todo 🔶 (discount-cap bypass policy) |
| 1.8 | Transactions around item mutations / approval+project creation / quote delete / link create; WHERE guards on `approve` + `final-approve` (TOCTOU, `00-AUDIT.md` §4.1) | 1.1 | M | todo 🔶 (**protected area — explicit owner yes required**) |
| 1.9 | Pagination + DB-side filtering on `GET /quotes`, `/projects`, `/design-requests`, `/templates`, `/site-admin/submissions`; batch the `formatQuote` N+1 with `inArray` | 1.1 | M | todo |
| 1.10 | **Cost integrity + price floor** (owner decision 2026-08-18, see `DECISIONS.md`): editable cost prices for every engine component (Georgian bars, tilt hardware, …); fix engine bugs behind goldens (tilt hardware, Georgian-bar reinforcement/material); unify `roundMoney`, round stored subtotal/total; then server-enforced minimum price = computed cost on fabricated uPVC quote lines (no floor possible on carpentry — cost is UNKNOWN there by design) | 1.1 | M | todo 🔶 (sub-decisions a–d in DECISIONS.md) |
| 1.11 | Anonymous-surface patches: pos-share expiry + rate limit, archived-quote check on share PUT, `ensureCustomerFor` hardening on public route, request-number generators → `doc_sequences` or indexed max | 1.2 | S–M | todo 🔶 (pos-share expiry) |
| 1.12 | God-file decomposition, one file per session, behaviour-frozen by tests/goldens: `configurator.tsx` → panels/hooks; `carpentry.tsx`+dressing cluster; `quote-detail.tsx`; `routes/quotes.ts` → lifecycle/items/links/format modules; `window-svg.tsx` → per-type renderers; `dressing-model` → geometry/billing/migration; extract `index.ts` seeders (part of 1.6) | 1.1 | L (ongoing) | todo |
| 1.13 | Server hygiene: Express error handler + 404, helmet, graceful shutdown, drop dead `cookie-parser`, restore `replit.md` accuracy | — | S | todo |

**Phase 1 exit criteria**: migrations are the only schema path · FKs+indexes live · goldens green ·
snapshots written at final approval · boot is read-only · one authz module · hot lists paginated.

## Phase 2 — Inventory & Warehouse *(first module: everything else posts to its ledger)*

| # | Item | Deps | Effort | Status |
|---|---|---|---|---|
| 2.1 | Platform primitives: `doc_sequences` (new doc types only), soft-delete convention, notification skeleton (in-app), new roles in authz | 1.7 | M | todo |
| 2.2 | `pos_products` → `items` rename + compatibility view; item kinds (good/profile/steel/accessory/offcut/spare/consumable, **+ raw_material** — raw-material stock is currently tracked in the costing workbook, see `03-REFERENCE-DATA.md`); price-list-2026.ts retired into data | 1.2, 1.3 | M | todo (risky cutover #3) |
| 2.3 | `stock_moves` generalisation: warehouse/bin/lot/base-UoM/source-doc/idempotency key; POS posts unchanged via defaults | 2.2 | M | todo |
| 2.4 | UoM conversions (bar ↔ metre ↔ kg ↔ piece), absorbing `barMeters`/`packageQty`/`unitFactor` | 2.2 | M | todo 🔶 (kg conversions per profile) |
| 2.5 | Warehouses + bin locations + QR labels; storekeeper UI (large-touch, Arabic-first) | 2.3 | M | todo |
| 2.6 | On-hand becomes ledger-derived (reconciliation job → drift zero → flip); storekeeper adjustment flow with reasons + approval | 2.3 | M | todo (risky cutover #4) |
| 2.7 | Cycle counts + stock takes with variance approval; offline-tolerant count screen | 2.6 | M | todo |
| 2.8 | Weighted-average valuation layers; aging + slow-mover + dead-stock reports | 2.6 | M | todo 🔶 (valuation method sign-off) |
| 2.9 | Reorder rules (generalised `lowStockAt`) + low-stock notifications | 2.6, 2.1 | S | todo |
| 2.10 | Offcut/remnant as first-class stock (kind=offcut, parent item + length) | 2.3 | S | todo 🔶 (min usable remnant length) |
| 2.11 | Lot/batch tracking (receiving side; extrusion batches arrive in Phase 3) | 2.3 | M | todo |

## Phase 3 — Manufacturing & Production

| # | Item | Deps | Effort | Status |
|---|---|---|---|---|
| 3.1 | Work centres + machines register (shared with Maintenance) | 2.x core | S | todo |
| 3.2 | Work orders from final-approved quotes (`WO-` numbering); routing extrusion→cutting→machining→welding→cleaning→glazing→assembly→QC→packing | 1.5, 3.1 | L | todo |
| 3.3 | Dual-write WO ↔ `production_stages` view; retire jsonb after acceptance | 3.2 | S | todo (risky cutover #5) |
| 3.4 | Shift calendars (Sunday–Thursday becomes code) + finite scheduling + Gantt | 3.2 | L | todo 🔶 (shift patterns) |
| 3.5 | Shop-floor terminal: tablet, Arabic-first, big targets, QR start/stop, scrap w/ reason codes, downtime capture, operator clock-in; offline-tolerant | 3.2 | L | todo |
| 3.6 | Material issue against WO → posts `stock_moves` | 3.2, 2.6 | M | todo |
| 3.7 | `@workspace/nesting`: deterministic 1D bar nesting (kerf, min remnant) fed by fabrication snapshots; offcuts written back to inventory; exhaustive unit tests | 1.5, 2.10 | L | todo 🔶 (kerf mm, grouping policy) |
| 3.8 | Extrusion batch tracking: compound lot, line speed, output kg, scrap %, regrind — **the three real compound formulas received** (incl. 3% scrap + 40 kg regrind per batch; see `03-REFERENCE-DATA.md`) | 3.2, 2.11 | M | todo |
| 3.9 | Actual vs estimated cost roll-up per WO against `quote-cost.ts` figures | 3.6 | M | todo |
| 3.10 | QC: inspection plans per operation, defect catalogue, hold/rework/scrap disposition | 3.2 | M | todo |

## Phase 4 — Procurement

| # | Item | Deps | Effort | Status |
|---|---|---|---|---|
| 4.1 | Supplier master + document expiry alerts + scorecards — **real register received** (71 suppliers, `ATPF-SUP-NN` codes, credit terms; profile + import repairs in `docs/03-REFERENCE-DATA.md`) | 2.1 | M | todo |
| 4.2 | Requisition → RFQ → supplier-quote comparison → PO | 4.1 | L | todo 🔶 (PO approval thresholds) |
| 4.3 | GRN posts the stock ledger; 3-way match; supplier invoice capture | 4.2, 2.6 | M | todo |
| 4.4 | Import shipments + landed-cost allocation into item cost | 4.3, 2.8 | M | todo (risky cutover #6) 🔶 (allocation basis) |

## Phase 5 — HR & Payroll *(independent track; can start after 1.7 in parallel with 2–4)*

| # | Item | Deps | Effort | Status |
|---|---|---|---|---|
| 5.1 | Employee master (QID, passport, visa, work permit, health card, contract, sponsor, nationality) + expiry tracking with escalating alerts; PDPPL controls built-in (classification, access logging, retention, export/erasure) | 1.7, 2.1 | L | todo |
| 5.2 | Org structure + cost centres (shared with Finance) | 5.1 | S | todo |
| 5.3 | Attendance: biometric import, shift rosters + rotation, overtime rules | 5.1, 3.4 | L | todo 🔶 (biometric device/format) |
| 5.4 | Leave per Qatar Labour Law: accrual brackets, sick tiers, maternity, ticket entitlement, encashment | 5.1 | L | todo 🔶 (policy specifics) |
| 5.5 | `@workspace/payroll-qa`: allowances, Labour-Law overtime, loans/advances per **ATPF-HR-FIN-CA-01** with the Article 70 deduction cap enforced in code; exhaustive edge-case suite BEFORE any UI | 5.3, 5.4 | XL | todo 🔶 (policy doc + edge rulings) |
| 5.6 | Bilingual payslip PDFs (Amiri/Naskh shaping, real Arabic name fixtures); WPS SIF generation validated strictly against the bank spec with fixture files | 5.5 | M | todo 🔶 (bank + SIF spec) |
| 5.7 | End-of-service gratuity: service brackets, resignation vs termination, unused leave, notice pay — exhaustive tests | 5.5 | L | todo 🔶 (edge rulings) |
| 5.8 | Appraisals, disciplinary records, training/certifications | 5.1 | M | todo |
| 5.9 | Employee self-service: payslip, leave request, documents, letters (mobile) | 5.5 | M | todo |
| 5.10 | First live payroll run parallel to the manual process for ≥1 cycle | 5.6 | — | todo (risky cutover #7) |

## Phase 6 — Finance

| # | Item | Deps | Effort | Status |
|---|---|---|---|---|
| 6.1 | Sales invoices + credit notes (bilingual, tax-configurable, VAT-ready, `INV-` numbering) layered on quotes | 2.1 | L | todo 🔶 (VAT registration status) |
| 6.2 | AR ledger + aging wrapping `quote_payments` (kept); SkipCash payment links | 6.1 | M | todo 🔶 (SkipCash account) |
| 6.3 | AP ledger + aging from supplier invoices; expense claims | 4.3 | M | todo |
| 6.4 | Cost centres + job costing per project; budget vs actual | 5.2, 3.9 | M | todo |
| 6.5 | Fixed assets + depreciation | 6.3 | M | todo |
| 6.6 | **Decision: light GL vs clean export.** For: in-house GL closes the loop, no re-keying, one audit trail. Against: statutory accounting, closing discipline and the accountant's toolchain live in the external package; a half-GL becomes two ledgers that disagree. **Recommendation: sub-ledgers here (AR/AP/inventory/payroll journals), clean posting export to the external package; revisit a full GL after two audited cycles.** | before 6.1 | — | awaiting-decision 🔶 |

## Phase 7 — Maintenance

| # | Item | Deps | Effort | Status |
|---|---|---|---|---|
| 7.1 | PM schedules (calendar/hours/cycles) on the machines register | 3.1 | M | todo |
| 7.2 | Breakdown work orders consuming spares from inventory | 7.1, 2.6 | M | todo |
| 7.3 | MTBF/MTTR; downtime linked to production loss (shares `op_events`) | 7.2, 3.5 | M | todo |

## Phase 8 — Projects & Installation

| # | Item | Deps | Effort | Status |
|---|---|---|---|---|
| 8.1 | Site surveys + measurement sheets (feed the configurator) | 1.x | M | todo |
| 8.2 | Installation crew scheduling | 3.4 | M | todo |
| 8.3 | Snag lists + handover documents | 8.2 | M | todo |
| 8.4 | Warranty registration + claims | 8.3 | S | todo |

## Phase 9 — Core platform completions *(woven in as needed, listed for tracking)*

| # | Item | Deps | Effort | Status |
|---|---|---|---|---|
| 9.1 | Configurable N-step approval workflows + delegation (quotes keep their bespoke chain until owner opts in) | 2.1 | L | todo 🔶 |
| 9.2 | Notification engine full: email + WhatsApp Business API (today: wa.me deep links only — a genuine API integration is new build) | 2.1 | M | todo 🔶 (WABA account) |
| 9.3 | Soft delete + restore on master data (one convention) | 1.2 | M | todo |
| 9.4 | Saved views + bulk actions on every list | 1.9 | M | todo |
| 9.5 | QR/barcode everywhere: items, bins, WOs, employees | 2.5 | S each | todo |

## Phase AI — the AI layer *(foundation after Phase 1; features attach to their module)*

| # | Item | Attaches to | Effort | Status |
|---|---|---|---|---|
| A.0 | `lib/ai` service: provider-agnostic, streaming, tool-use, schema-validated JSON, retries, per-call cost logging, graceful degradation + `ai_calls` audit console. **Recommendation: add Anthropic (`claude-sonnet-4-6`) alongside OpenAI** — structured tool-use quality and Arabic handling justify a second provider, and the abstraction makes it a config choice; keep OpenAI for the existing Replit-integration image/vision paths. | 1.7 | M | todo 🔶 (provider approval) |
| A.1 | Quotation copilot: RFQ (PDF/image/WhatsApp text/Excel) → window schedule → mapped draft quote lines, ambiguities flagged, never auto-sent. **Highest value — build first.** | A.0, sales | L | todo |
| A.2 | Ask-your-ERP (AR+EN): constrained tool-use over whitelisted read queries, caller's permissions enforced per result, answer + numbers + report link. Never free-form SQL | A.0, 1.7 | L | todo |
| A.3 | Document intelligence: supplier invoices/GRNs/customs/IDs → structured records + confidence + human review queue | A.0, 4.3, 5.1 | L | todo |
| A.4 | Cutting-optimiser explanation (nesting stays deterministic; AI explains + suggests cross-order grouping) | 3.7 | S | todo |
| A.5 | Demand & inventory forecasting, reorder suggestions with reasoning, dead-stock/overstock alerts | 2.8 | M | todo |
| A.6 | Morning brief (bilingual, extends chase-digest pattern) | A.0, 3.x | M | todo |
| A.7 | HR assistant: RAG over bilingual HR manual, letters/contracts drafts citing Labour Law articles, always draft | 5.x | M | todo |
| A.8 | Anomaly detection from `activity_log` (discounts, stock adjustments, overtime spikes, duplicate supplier invoices, out-of-hours) — review items, never blocking | A.0 | M | todo |
| A.9 | Predictive maintenance on downtime/scrap patterns | 7.3 | M | todo |

## Non-functional gates (apply to every phase; checked at each phase exit)

- Every new string through `lib/translations/*` (`{en, ar}` per key); RTL verified.
- Arabic PDFs: Amiri/Naskh registered + `pdf-text` splitter used; **fix the existing gap: BOM and
  execution-plan PDFs have no Arabic font today**; test with real Arabic names/addresses. Hijri alongside
  Gregorian where documents need it (first appears: HR letters, payslips).
- Desktop dense/keyboard for office roles; large-touch Arabic-first for shop floor/warehouse;
  mobile-responsive approvals/dashboards/ESS; offline-tolerant sync-on-reconnect for shop-floor and
  stock-count screens.
- Honeypot + per-IP rate limit (shared store, not in-memory) + allow-list snapshot pattern on every new
  anonymous surface; never expose cost or personal data publicly.
- Qatar PDPPL: personal-data classification, access logging, retention, export + erasure — HR is the
  sensitive set and ships with the controls.
- Index every FK and filter column; paginate every list; background-job anything slow; no unbounded queries.

## §11 — Consolidated business decisions needed (🔶 index)

| When | Decision |
|---|---|
| Now (Phase 0 gate) | `00-AUDIT.md` §6: orphan counts, discount-cap policy, factory-website existence, approve-guard sign-off, pos-share expiry, snapshot timing, BOM bug fix-vs-freeze, migration window |
| Phase 2 | Valuation method (weighted average proposed), UoM kg conversions per profile, minimum usable remnant length |
| Phase 3 | Shift patterns/calendar, kerf mm, nesting grouping policy |
| Phase 4 | PO approval thresholds, landed-cost allocation basis |
| Phase 5 | ATPF-HR-FIN-CA-01 text + Article 70 interpretation, leave policy specifics, biometric device/format, bank + WPS SIF spec, gratuity edge rulings |
| Phase 6 | GL keep-vs-export (recommendation in 6.6), VAT registration status, SkipCash account |
| Phase 9/AI | Approval-workflow adoption for quotes, WhatsApp Business account, Anthropic provider approval |
