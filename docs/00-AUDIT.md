# 00-AUDIT — Al-Thuraiya configurator + quotation system

> **Scope note.** This audit was produced from the code snapshot `althuraiyadesigntoolonly-2026-08-18.zip`
> (the design tool only — no database attached, no `node_modules`). All `path:line` citations are relative
> to that repo's root. Where a check needs the live database (orphan-row counts), the exact SQL is provided
> here to run on Replit — it could not be executed against a snapshot.

---

## 1. Verdict summary

The codebase is **better than the defect list implied in two places and worse in three**.

Better:
- The fabrication/BOM engine is **not client-only**. It lives in the shared workspace lib `lib/costing`
  and the API server already runs it server-side per request (`artifacts/api-server/src/lib/quoteCost.ts:49-90`,
  called from `routes/quotes.ts:229`). The client consumes the same engine by re-export
  (`artifacts/upvc-configurator/src/lib/fabrication.ts:1-4` → `export * from "@workspace/costing/fabrication"`).
  The real defect is narrower and cheaper to fix: **no immutable fabrication/cost snapshot is ever persisted**
  — every figure is recomputed from live catalog + live `bom_rates`, so historical quotes' costs mutate
  retroactively (`quoteCost.ts:78-84`).
- All transactional money is already `numeric`. Float money exists in exactly two settings singletons
  (`bom_rates`, `report_settings.minProfitPercent`), nowhere in quotes/POS/payments.

Worse:
- **Almost nothing multi-write is transactional.** Item mutations, approval + project creation, and quote
  deletion are sequences of autocommit statements (§4.2). There is a concrete TOCTOU race that can stamp
  `finalApprovedAt` on an unsigned, unapproved quote and flip its project into production (§4.1).
- **The deployment is autoscale but the server assumes a single process**: 14 boot-time DB
  mutation steps run on *every instance start* (§2.7), and all rate limiters are per-process in-memory Maps
  (`sharePublic.ts:74-95`, `designRequestsPublic.ts:38-45`) — N instances = N× the limit.
- **The hottest list endpoints are unbounded with N+1 formatters**: `GET /quotes` loads the whole table and
  runs ~6 queries per row (§4.3).

Per-area verdicts (reasoning in the sections below):

| Area | Verdict |
|---|---|
| `lib/costing` engine (fabrication/bom/quote-cost) | **Keep.** Well-factored shared lib; add characterization tests, fix the three math bugs (§5), persist snapshots. |
| Quote lifecycle / share / sign links | **Keep the design.** The allow-list + tombstone architecture is genuinely good. Fix races/transactions only, with owner sign-off (protected area). |
| POS module | **Keep.** The best-engineered module: pagination, `FOR UPDATE` row locking, movement ledger, clamped inputs. Model for the rest. |
| DB schema | **Refactor in place** via real migrations: baseline → FKs → indexes → status constraints. No rewrite. |
| Authorization (`permissions.ts` + guards) | **Refactor** into one table-driven policy module + per-request user cache. Logic is sound; placement is scattered. |
| Boot seeders (`api-server/src/index.ts`) | **Move** to explicit idempotent commands. Mechanically easy — the file is 75% static seed data with zero route entanglement. |
| God-file pages (configurator/carpentry/quote-detail/3D) | **Decompose gradually** behind tests; one file per session. No behaviour change. |
| `lib/activity.ts` | **Keep.** It is a declarative 51-rule audit catalogue, not spaghetti; its size is data, not logic. |
| e2e harness (`scripts/`) | **Keep** alongside new vitest unit tests. |
| `replit.md` | **Update** — it has drifted (§7). |

---

## 2. The nine claimed defects — verified

### 2.1 No database migrations — **CONFIRMED**
- `lib/db/package.json:10-12` — the only scripts are `push` and `push-force` (`drizzle-kit push [--force]`).
- `lib/db/drizzle.config.ts` has no `out` directory; no migrations folder exists anywhere under `lib/db`.
- **Aggravating:** the post-merge hook is silently broken — `scripts/post-merge.sh:4` runs
  `pnpm --filter db push`, but the package is named `@workspace/db` (`lib/db/package.json:2`), so the filter
  matches nothing and the push never runs. The correct invocation (`pnpm --filter @workspace/db run push`)
  appears in `replit.md:10`.
- Severity: **Critical for ERP.** Blocks every schema change the roadmap needs; `push --force` can drop data.

### 2.2 Almost no referential integrity — **CONFIRMED, exactly 8**
- Exactly 8 `.references()` calls, in 5 of the 35 table files (grep-verified). All are `onDelete: "cascade"`;
  no other referential action exists anywhere:
  1. `chase_digests.userId` → users — `schema/chaseDigests.ts:18`
  2. `design_request_follow_ups.requestId` → design_requests — `schema/designRequestFollowUps.ts:18`
  3. `quote_follow_ups.quoteId` → quotes — `schema/quoteFollowUps.ts:17`
  4. `quote_handovers.quoteId` → quotes — `schema/quoteHandovers.ts:21`
  5. `quote_handovers.toUserId` → users — `schema/quoteHandovers.ts:25`
  6. `design_share_links.quoteId` → quotes — `schema/shareLinks.ts:21`
  7. `design_share_links.quoteItemId` → quote_items — `schema/shareLinks.ts:24`
  8. `quote_sign_links.quoteId` → quotes — `schema/shareLinks.ts:47`
- Confirmed bare integers: `quotes.projectId` (`schema/quotes.ts:7`, nullable, **no FK, no index**),
  `quoteItems.quoteId` (`schema/quoteItems.ts:7`, notNull, **no FK, no index**),
  `posStockMovements.productId` (`schema/posProducts.ts:71`, notNull, no FK, *indexed* at `:83`).
- Beyond those three: **~20 actor columns** (`createdBy`, `*ApprovedBy`, `assignedBy`, `archivedBy`,
  `recordedBy`, `handledBy`, `convertedBy`, `cancelledBy`) are all bare integers to `users`, and
  `customerId` on quotes/projects/design_requests/pos_sales is bare to `customers`. Deleting a user or
  customer dangles silently everywhere except the 8 cascades — and two of those cascades are themselves
  aggressive (deleting a user cascades away his handover and chase-digest history).
- Note two comment-enforced-only invariants: `designRequests.convertedQuoteId` "never twice"
  (`schema/designRequests.ts:58` — no unique), and `pos_sales.shareToken` is indexed but **not unique**
  (`schema/posSales.ts:54`) while both link tables do enforce token uniqueness.
- **Orphan-row check could not be run here (no DB attached).** Run this on Replit *before* the FK migration
  and report the counts:

```sql
SELECT 'quote_items→quotes' k, count(*) FROM quote_items i LEFT JOIN quotes q ON q.id=i.quote_id WHERE q.id IS NULL
UNION ALL SELECT 'quotes→projects', count(*) FROM quotes q LEFT JOIN projects p ON p.id=q.project_id WHERE q.project_id IS NOT NULL AND p.id IS NULL
UNION ALL SELECT 'quotes→customers', count(*) FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id WHERE q.customer_id IS NOT NULL AND c.id IS NULL
UNION ALL SELECT 'quote_payments→quotes', count(*) FROM quote_payments qp LEFT JOIN quotes q ON q.id=qp.quote_id WHERE q.id IS NULL
UNION ALL SELECT 'pos_stock_movements→pos_products', count(*) FROM pos_stock_movements m LEFT JOIN pos_products p ON p.id=m.product_id WHERE p.id IS NULL
UNION ALL SELECT 'pos_sale_items→pos_sales', count(*) FROM pos_sale_items i LEFT JOIN pos_sales s ON s.id=i.sale_id WHERE s.id IS NULL
UNION ALL SELECT 'pos_payments→pos_sales', count(*) FROM pos_payments p LEFT JOIN pos_sales s ON s.id=p.sale_id WHERE s.id IS NULL
UNION ALL SELECT 'projects→customers', count(*) FROM projects pr LEFT JOIN customers c ON c.id=pr.customer_id WHERE pr.customer_id IS NOT NULL AND c.id IS NULL
UNION ALL SELECT 'quotes.created_by→users', count(*) FROM quotes q LEFT JOIN users u ON u.id=q.created_by WHERE q.created_by IS NOT NULL AND u.id IS NULL
UNION ALL SELECT 'design_requests→customers', count(*) FROM design_requests d LEFT JOIN customers c ON c.id=d.customer_id WHERE d.customer_id IS NOT NULL AND c.id IS NULL;
```

- Severity: **Critical for ERP.** A stock ledger or payroll table without FKs is unauditable.

### 2.3 Zero unit tests on money/fabrication math — **CONFIRMED**
- No vitest/jest anywhere (grep over every `package.json`: zero hits).
- ~19 `e2e-*.ts` scripts exist under `scripts/src/`; **correction to the claim**: they are *not* mostly
  Playwright. The API e2e scripts (e.g. `e2e-pos.ts`, `e2e-quote-cost.ts`) are raw `fetch` against the live
  API with real Clerk users minted via the Clerk Admin API (`e2e-pos.ts:53-66`), hand-rolled
  `check(name, ok)` assertions, seeded-prefix data and cleanup in `finally`. `playwright-core` is used only
  by 4 browser scripts (`e2e-sign-scroll.ts`, `e2e-design-phone.ts`, the two `capture-*-screenshots.ts`).
- `.replit` wires only 8 of them as workflows; the run button "Project" is a *parallel validation
  meta-workflow*, not an app launcher (`.replit:12-49`).
- Hazard worth knowing: `e2e-quote-cost.ts` mutates the production-shared singleton
  `report_settings.minProfitPercent` and restores it in `finally` (`e2e-quote-cost.ts:377-380`) — a crash
  mid-run leaves live settings altered.
- Severity: **Critical.** Every refactor in this plan is unsafe until characterization tests lock
  `fabrication.ts`, `bom.ts`, `quote-cost.ts`, `quoteMoney.ts`, `posMoney.ts`, `billedDims()`.

### 2.4 "Fabrication and BOM run client-side" — **PARTLY WRONG, and the truth is better**
- The engine is a shared workspace lib: `lib/costing/src/{fabrication.ts, bom.ts, quote-cost.ts}`.
  The client files are one-line re-exports (`upvc-configurator/src/lib/fabrication.ts:1-4`, `bom.ts:1-4`).
- The server **already calls it**: `quoteCostSummary` (`api-server/src/lib/quoteCost.ts:49-90`) computes
  cost/profit server-side on quote detail (gated by `canSeeCost`).
- What *is* true and must be fixed:
  1. **Nothing is persisted.** Per quote item the DB stores only sale-price columns, geometry and the
     `extraConfig` design snapshot (`schema/quoteItems.ts:15-26`); BOM/cut-lists are recomputed from
     *live* catalog + *live* `bom_rates` on every request (`quoteCost.ts:78-84`). Historical cost/profit
     figures therefore change retroactively when a profile price or rate is edited. A factory floor cannot
     take a cut list from that.
  2. Client-side PDF generation (`@react-pdf/renderer`, `upvc-configurator/package.json:91`) recomputes the
     BOM in the browser for the execution-plan/BOM reports (`lib/quote-reports.ts:333-380`).
- Fix shape: **persist an immutable fabrication + BOM + rate snapshot per quote item at final approval**,
  have both server reports and client PDFs render the snapshot. The engine itself does not need to move.
  The engine's only workspace dependency is two React-free subpaths of `lib/window-designer`
  (`custom-grid`, `door-leaves` — `fabrication.ts:6-7`), so it is already server-safe.
- Severity: **Critical for Manufacturing** (work orders and cutting optimisation consume the snapshot), but
  the work is smaller than "move the engine".

### 2.5 God files — **CONFIRMED, with corrections and additions**
Measured (`wc -l`):

| File | Lines |
|---|---|
| `artifacts/upvc-configurator/src/pages/configurator.tsx` | 3,128 (one component, ~40 useState) |
| `artifacts/upvc-configurator/src/components/dressing-room-3d.tsx` | 3,005 |
| `lib/dressing-model/src/index.ts` | 2,609 (geometry + pricing parsing + v1→v2 migration in one file) |
| `artifacts/upvc-configurator/src/pages/carpentry.tsx` | 2,506 |
| `lib/window-designer/src/window-svg.tsx` | 2,351 (18-type render switch at `:1142-1928`) |
| `artifacts/upvc-configurator/src/components/dressing/dressing-designer.tsx` | 1,966 |
| `artifacts/upvc-configurator/src/components/wardrobe-contents.tsx` | 1,800 |
| `artifacts/upvc-configurator/src/pages/quote-detail.tsx` | 1,656 |
| `artifacts/api-server/src/lib/activity.ts` | 1,331 — **but see below** |
| `artifacts/upvc-configurator/src/pages/share.tsx` | 1,296 |
| `artifacts/api-server/src/routes/quotes.ts` | ~1,450 (64 kB) |

- **Correction — `api-server/src/index.ts` (550 lines) is not a route/middleware god file.** It contains
  zero route handlers; ~75% is static bilingual seed data. The Express app is a separate 81-line `app.ts`.
  Decomposition = extract 9 seeder functions into `src/boot/`; trivial.
- **Correction — `activity.ts` is a declarative rule catalogue** (51 route-regex rules at `:387-927` + a
  10-table one-time backfill at `:1054-1322`), not tangled logic. Leave it; splitting the rules from the
  backfill is optional hygiene.
- The internal structure of each god file (line ranges per section) was mapped and is preserved in the
  audit working notes; each is decomposable along its existing section boundaries.

### 2.6 Rates use `doublePrecision` — **CONFIRMED, complete list**
- `bom_rates`: 9 float columns (`schema/bomRates.ts:30-38`) + jsonb `hardwarePrices` keyed by **display
  name strings** that "must stay in sync with lib/bom.ts" (`:5-6, 39-42`) — a rename silently orphans a price.
- `report_settings.minProfitPercent` (`schema/reportSettings.ts:33`) — the only other float in the repo.
- Everything transactional is `numeric`: (12,2) quotes/POS/payments, (5,2) percents, (10,4) per-meter
  profile prices. So the standardisation is two tables, not a sweep.

### 2.7 Startup seeders mutate production data — **CONFIRMED, and larger than claimed**
Boot performs **14 sequential DB-mutation steps before `app.listen`** (`index.ts:433-541`), each in a
try/catch that only logs (boot continues on failure):
1. `ensureCarpentryCatalog` (+7 window_types rows) `:434`
2. `ensureFabricatedTypologies` (TL-01) `:440`
3. `ensureLabMedia` + 11 one-time media reclassification UPDATEs `:446`
4. `removeSeededDemoExportProjects` (3 conditional DELETEs) `:452`
5. `ensureRealReferenceProjects` — deletes fictional seeds, inserts 11 real projects, backfills images
   (`:149-292`, called `:458`)
6. `ensureSeededCertificates` (8 rows if empty) `:464`
7. `ensureSeededTeamMembers` (9 real names if empty) `:470`
8. `ensurePosPriceList` (seeds `pos_products` from the 423-line hardcoded price list) `:476`
9. `reconcileSiteSettingsFromProfile` — inserts/patches the `site_settings` singleton with hardcoded
   real contact data (`:299-327`, called `:482`)
10. `backfillCustomers` — **full-table scans** of quotes/design-requests/projects `:490`
11. `backfillActivity` — full scans of 10 tables, gated by `activityBackfillNeeded` `:502-504`
12. `pruneActivity` (3-year retention) + daily interval `:512-520`
13. `cleanupExpiredShareLinks` + hourly interval `:524-532`
14. `pruneChaseDigests` + `startDailyChaseDigest` (hourly tick, inserts digests) `:537-541`

Aggravating factors:
- Deployment target is **autoscale** (`.replit:5`): every new instance replays all 14 steps; the interval
  jobs run on every instance concurrently. Idempotence is by `onConflictDoNothing`/old-value guards, not
  by locks — mostly safe but unserialised.
- Boot-time full-table scans (steps 10–11) delay readiness linearly with data size.
- A seeded reference project re-created by an admin with the old name+image is **deleted again on next
  boot** (`:452`, acknowledged in `replit.md`).
- Severity: **High.** An ERP must not patch rows on boot; move to explicit, logged, idempotent commands.

### 2.8 Auth: per-request DB round-trip + scattered authorization — **CONFIRMED, worse than claimed**
- `getCurrentUser` (`api-server/src/lib/permissions.ts:45-52`) is an uncached
  `db.query.usersTable.findFirst` per **call**, and a single mutating request calls it **2–4 times**
  (activityLog middleware → `requireApproved` → handler(s), e.g. `routes/quotes.ts:591` + `:597`).
- `permissions.ts` mixes four concerns: discount caps (`MAX_DISCOUNT` `:9-15`), price-edit rights
  (`canEditPrice` `:34`), approval rights (`canApproveQuotes` `:29` — admin|factory_manager **only**;
  ordinary managers cannot approve), and identity resolution itself (`getCurrentUser`/`getCurrentRole`).
- `requireAdmin` is defined (`middlewares/requireApproved.ts:65-83`) but **never mounted anywhere**; every
  admin check is inline (`routes/quotes.ts:800-802`, `routes/users.ts` deactivate/erase).
- Role storage is free text — no pgEnum, no CHECK (`schema/users.ts:11`); unknown roles degrade to staff.
- **The discount cap is largely symbolic on quotations**: item pricing is salesman-entered with explicitly
  no role gating (`routes/quotes.ts:954-956` — "no catalog prices, no automatic supplements, no role
  gating"), so a 5%-capped staff member can simply type a lower `unitPrice`. `MAX_DISCOUNT` constrains
  only the visible discount field. (Decision needed: is that intended policy?)
- Also found: `vatPercent` unclamped/unvalidated on quotes (`routes/quotes.ts:594`); POS sale PATCH has no
  ownership scoping (any approved user can edit any draft sale, `routes/posSales.ts:462-476`); a sales-role
  carve-out lets `sales` PATCH `profiles.pricePerMeter` despite failing `canEditPrice`
  (`routes/profiles.ts:8-20`); `PUT /auth/me` is reachable by deactivated users (`routes/auth.ts:176-232`).
- Severity: **High.** Centralise into one table-driven policy module + a per-request cached context before
  any new roles (`storekeeper`, `hr`, `accountant`, …) are added.

### 2.9 Production schedule is a fixed jsonb array — **CONFIRMED**
- `STAGE_DAYS = [["preparation",3],["fabrication",14],["quality",3],["delivery",7]]`
  (`api-server/src/lib/production.ts:17-24`), written as untyped jsonb (`schema/projects.ts:27` — the only
  jsonb column in the schema with no `$type`) at **final** approval only, guarded so re-approval keeps an
  existing schedule (`routes/quotes.ts:1411-1428`).
- Plain calendar days — **no Sunday–Thursday logic exists anywhere**, and no Hijri anywhere (the "working
  week" claim in the project brief is aspiration, not code). Chase digests fire on Fridays too
  (`chaseDigest.ts:26-40`).
- This is the stub the Manufacturing module replaces. Keep until work orders are live.

---

## 3. Claim corrections beyond the defect list

Things the project brief / `replit.md` state that the code contradicts:

1. **`artifacts/factory-website` is absent from this snapshot** — `artifacts/` contains only `api-server`
   and `upvc-configurator`, while `replit.md:28,33-35,43,52` references it extensively and the site CMS
   tables + `/api/site` + `/api/site-admin` (19 paths) exist to serve it. Confirm it exists in the live
   Replit repo before touching anything site-related.
2. **Carpentry door designs are TD-01..TD-10**, not TD-01..09 (`wooden-door-svg.tsx:37-39, 66-77`; the
   file's own header comment is stale). WD-01..04 are DB rows ensured at boot, chosen by rule
   (`carpentry.tsx:749-756`), not a drawing catalog.
3. **"15+ window types"** is true only at the renderer level (18 codes in `window-svg.tsx:1142-1928`);
   the seeded staff catalog is 12; shaped types (ARC/FAN/TRAP/TRI/CIRC) are public-designer-only unless an
   admin creates rows.
4. **Quote numbers are `Q-<year>-NNNN`**, not `QT-` (`routes/quotes.ts:142`); POS is `POS-<year>-NNNN`;
   design requests `DR-<year>-NNNN`. All three generators **scan every row** and take max+1 with a
   unique-violation retry — no sequences (`designRequestsPublic.ts:194-204`, `posSales.ts:42-53`).
5. **`PRICING_KEY_RE` guards only the public design-request intake** (`designRequestsPublic.ts:136,161`).
   Share-link edits are protected by a different, stronger mechanism: structural patch appliers + the
   `*_DESIGN_KEYS` allow-lists (`lib/designSnapshot.ts:53-160`, "Allow-list only, never a denylist").
   Outbound share/sign payloads never touch the regex.
6. **Sign-link durations 7/14/30 are UI-only** — the server accepts any 1–30 days
   (`api-zod generated api.ts:2079-2081`); share links' 3/4 days *are* server-enforced (zod literals).
7. **Pricing mutations tombstone sign links only** (`quotes.ts:71-83`); design share links are tombstoned
   by approval/replacement/revoke/expiry — intentional (quote back in negotiation), but the brief's
   "tombstones live links" is precise only for sign links.
8. **Zod: the installed package is 3.25.76**; `zod/v4` is the v4-API compat subpath and is used **only in
   `lib/db` schema files** (29 files). The generated contract schemas use classic `import * as zod from
   'zod'` (`api-zod/src/generated/api.ts:8`).
9. **"Port 8080 proxied at /api" is documentation-only** — the string 8080 appears nowhere in code; both
   servers require `PORT` env (`index.ts:404-416`, `vite.config.ts:7-19`); `/api` is mounted inside
   Express itself (`app.ts:79-82`); no Vite proxy exists. Routing is Replit-infra behaviour.
10. **`replit.md`'s workflow list has drifted**: no "web" or "API Server" workflow exists in `.replit`;
    the run button is a parallel validation suite. Also `replit.md:68` says python3 is unavailable while
    `.replit:1` loads `python-3.11`.
11. **No Hijri, no working-week logic, no invoice concept** anywhere in code. Documents are quotation
    (عرض سعر) and payment receipt (سند القبض). All date logic is Asia/Qatar via `qatarDay()`
    (`lib/qatarDate.ts:1-30`).
12. **Color/pricing-rule `sqmDelta` surcharges are display-only** — pricing is 100% salesman-entered;
    deltas appear as UI badges only (`configurator.tsx:1714-1715`; server comment `routes/quotes.ts:957-959`).

---

## 4. What the defect list missed — ranked

### 4.1 CRITICAL — lifecycle race: final-approve can fire on an unsigned quote
`POST /:id/final-approve` checks `customerSignedAt` on the **pre-loaded row** (`routes/quotes.ts:1387`) but
the UPDATE (`:1393-1402`) has no WHERE guard on `customerSignedAt`/`managerApprovedAt`. A pricing edit
committing between read and write nulls the chain; final-approve then stamps `finalApprovedAt` on an
unsigned, unapproved quote — `lifecycleOf` reports "final-approved" (checked first, `:87`) and the project
flips to production. The customer-sign path shows the correct pattern (guarded UPDATE,
`sharePublic.ts:886-891`); `POST /:id/approve` (`:897`) has the same hole. **Protected area — fix needs
owner sign-off, but the fix is a one-line WHERE clause per endpoint.**

### 4.2 CRITICAL — multi-write mutations are not transactional
- Item add/update/delete: item write + subtotal recompute + approval reset + `invalidateSignLinks` +
  `ensureProjectForApprovedQuote` are 4–6 sequential autocommit statements
  (`routes/quotes.ts:962-993, 1085-1097, 1112-1120`). Crash mid-sequence leaves stale subtotals or a live
  sign link on a reprised quote.
- Approval + project creation: project INSERT, quote UPDATE, compensating DELETE are separate statements
  (`quotes.ts:106-131`); crash orphans a project.
- Quote DELETE: three sequential deletes, no transaction (`quotes.ts:804-806`) — and no FKs to backstop it.
- Share/sign link creation is delete-then-insert with no transaction and no unique constraint on
  `quoteItemId` (`quotes.ts:1171-1178`) — two concurrent creates leave two active links.
- Counter-example that proves the team knows how: POS deliver/cancel wraps everything in a transaction
  with ordered `FOR UPDATE` row locks (`posSales.ts:665-694`), and payments POST uses
  `SELECT ... FOR UPDATE` overshoot-guard (`quotePayments.ts:148-181`).

### 4.3 HIGH — unbounded lists + N+1 formatters on the hottest endpoints
- `GET /quotes`: `db.select().from(quotesTable)` — whole table, role/status/archived filtered **in JS**,
  no LIMIT (`quotes.ts:467-478`); then `formatQuote` issues up to 5 queries per row (project + 4 user
  lookups, `:204-218`) → ~5N+1. (Paid totals, to its credit, are one grouped query for the page, `:478`.)
- Same shape: `GET /projects` (all rows + one COUNT per project, `projects.ts:41-50`),
  `GET /design-requests` (all rows including jsonb design snapshots, `designRequests.ts:115-121`),
  `GET /templates` (all rows incl. extraConfig, `templates.ts:32`), `GET /site-admin/submissions` + CSV
  export (public-form-fed, `siteAdmin.ts:496-513`).
- Anonymous N+1: the sign-page payload does 4 `findFirst`s per item (`sharePublic.ts:653-679`).
- Counter-examples: POS list paginates (limit 1..500, `posSales.ts:314,341`); activity log clamps at 200
  with offset+total (`activity.ts:87-100`); the shared libs batch with `inArray` almost everywhere.

### 4.4 HIGH — `quote_items` has zero indexes
The hottest child table (fetched by `quoteId` on every quote open) defines no index callback at all
(`schema/quoteItems.ts:5-29`). Its POS twin indexes `saleId` (`schema/posSales.ts:92`). Also unindexed:
`quotes.projectId`, `quotes.status`, `quotes.createdBy`, `templates.*`, `profiles.*` (and `profiles.code`
is not unique despite being the natural key with `systemId`).

### 4.5 HIGH — single-process assumptions on an autoscale deployment
All rate limiting is fixed-window in-memory Maps (`sharePublic.ts:74-95`, `designRequestsPublic.ts:38-45`,
`sitePublic.ts:27-47`, `carpentry.ts:23-41`) — resets on restart, multiplies by instance count. Rate-limit
keying trusts the rightmost non-private XFF hop (`lib/clientIp.ts:26-38`) — safe only behind Replit's edge.
Boot seeders + interval jobs run per instance (§2.7). No graceful shutdown (no SIGTERM handler,
`app.listen` return discarded); no Express error handler or 404 handler; no helmet; `cookie-parser` is a
dead dependency.

### 4.6 MEDIUM — anonymous-surface gaps (the overall pattern is genuinely good)
The honeypot + per-IP limits + allow-list snapshot pattern is real and consistently applied
(`designRequestsPublic.ts:28-49, 231`; `sharePublic.ts:196-214`; 192-bit tokens everywhere;
magic-byte photo sniffing; no IDOR anywhere — all anonymous reads are token- or slug-scoped). Gaps:
- **pos-share tokens never expire** (no `expiresAt` on `pos_sales`, `posPublic.ts:24` checks only
  not-cancelled) and `/pos-share/:token` has **no rate limiting at all** — the only anonymous endpoint
  with zero throttle. It also discloses the salesman's name (`posPublic.ts:55`).
- **Anonymous customer-record pollution**: the public design-request POST calls `ensureCustomerFor`
  (`designRequestsPublic.ts:295`) — a submitter using a victim's phone attaches spam to that customer's
  file and can write `location`/`email` into empty fields of the victim's record (`customers.ts:56-57`).
- **Full-table scan per anonymous submission**: `buildRequestNumber` scans all design requests on every
  public POST (`designRequestsPublic.ts:194-196`).
- Archived quotes remain **customer-editable via design share links** — the share PUT checks
  `managerApprovedAt` but never `archivedAt` (`sharePublic.ts:408-413`); sign links do check.
- Sitemap reflects attacker-controlled `x-forwarded-host` into cached output (`sitePublic.ts:270-278, 338`).
- `/site/*` reads and public object serving have no throttle; site-contact zod leaves email/phone/company
  unbounded (`api.ts:3033-3047`).

### 4.7 MEDIUM — money-math correctness bugs (fix with the characterization tests)
1. **Tilt hardware priced at 0**: `hardwareFor("tilt")` emits "Bottom-hung hinge set" and "Restrictor
   stay" (`bom.ts:181-182`) but neither key exists in any hardware price map — `?? 0` silently zeroes them
   (`bom.ts:245`). TL-01 cost understated, profit overstated.
2. **Georgian bars**: counted as galvanized-steel reinforcement meters when ≥700mm (`bom.ts:226` filter),
   yet contribute **zero material price** because `"GEORGIAN-BAR"` never matches a profile def
   (`fabrication.ts:771`). Decorative bars are free but inflate steel.
3. **Two different `roundMoney` implementations**: quote's `Math.round(n*100)/100` (`quoteMoney.ts:24`) vs
   POS's epsilon-hardened version (`posMoney.ts:12`). `calcTotals` returns **unrounded** `subtotal` and
   `total` (`quoteMoney.ts:16,20`) — float dust reaches the JSON list payload (`quotes.ts:323`); stored
   header `subtotal` is written from an unrounded float reduce (`quotes.ts:990-991`) and only agrees with
   the numeric column because unit prices are 0.5-multiples today.
4. `SL-02` dead conditional: `typeCode === "SL-02" ? 2 : 2` (`bom.ts:141`).
5. Cost figures are rate-live (no snapshot) — see §2.4.

### 4.8 MEDIUM — schema smells beyond FKs
- **jsonb doing a table's job, ranked**: `projects.productionStages` (untyped; the Manufacturing stub),
  `quote_items.extraConfig` (the system's most valuable payload, `Record<string, unknown>`, ~150
  occurrences across 40 files, carries **megabytes of base64 3D snapshots** — the 6 MB JSON body limit
  exists for it, `app.ts:64-67`), `design_requests.items` (a child table flattened), `chase_digests.quoteIds`
  (join table in jsonb), `bom_rates.hardwarePrices` (display-name-keyed price list).
- **Five different soft-delete conventions** (archivedAt / cancelled status / status "archived" /
  `isActive` / `isPublished`) and customers have none.
- `quotes.customerSignature` stores a base64 PNG **in the main quotes row** (`schema/quotes.ts:33-34`) —
  row bloat on the most-read table.
- No pgEnum anywhere; `quotes.status` is client-writable free text (PATCH copies any string,
  `quotes.ts:588`) — a salesman can set `status: "accepted"` on a draft.
- `GET /quotes/:id` has a write side effect (clears `customerEditedAt`, `quotes.ts:536-538`).
- Two singleton tables rely on `id=1` by convention, unenforced.
- The hardcoded 423-line price list (`lib/db/src/data/price-list-2026.ts`) duplicates `pos_products`'
  bar/pack model with no linking key — two unreconciled catalogs feeding a future item master.

### 4.9 LOW — dead code and drift
- The entire image/audio/batch surface of `lib/integrations-openai-ai-server` has zero consumers; the only
  AI call in the product is the wardrobe-photo reader (`lib/wardrobePhoto.ts:217`, model `gpt-5.6-terra`,
  two vision passes, 30/hr in-memory limit).
- `activity.ts` exports `fieldLabel`/`fmtNumber`/`fmtValue`/`RULES` unused; `scripts/src/tmp-sign-signature-check.ts`
  self-declares "delete after use"; 4 scripts have no package.json entry; `@assets` vite alias points at a
  missing directory; dead workspace glob `lib/integrations/*`; TODO/FIXME census: **zero hits** — debt is
  documented in prose comments, not markers, so grep-for-TODO finds nothing.

---

## 5. What is genuinely good (do not break these)

- **The allow-list discipline at every anonymous boundary** (`lib/designSnapshot.ts` "Allow-list only,
  never a denylist"; `publicReportSettings` omits `minProfitPercent` by construction).
- **Cost-visibility firewall**: `canSeeCost` + "carpentry cost is UNKNOWN, never guessed at zero"
  (`lib/quoteCost.ts:1-22`, `lib/costing/quote-cost.ts:6-8`).
- **POS stock movement ledger semantics**: stock moves only on delivery; cancelling a delivered sale
  writes the mirror row (`schema/posSales.ts:12-13`) — the seed of the ERP-wide immutable stock ledger.
- **Customer printed-snapshot rule**: quote/project customer columns are frozen copies by design
  (`schema/quotes.ts:8-12`) — keep this pattern for invoices later.
- **The signing race guard** (`sharePublic.ts:886-891`) — the template for fixing §4.1.
- **192-bit tokens, magic-byte upload sniffing, CSV formula-injection neutralisation, logger redaction of
  cookies/authorization** — real security craftsmanship exists here.
- **Money rounding is a documented business rule**: floor-to-0.5-QAR on quotes, plain 2dp on POS, kept
  deliberately different (`posMoney.ts:8-14`), with server/client copies marked "keep in sync"
  (`lib/pricing.ts:1-10` both sides).

---

## 6. Questions to answer before Phase 1

1. **Orphan rows**: run the SQL in §2.2 on the live DB and share the counts — they decide whether the FK
   migration needs a data-repair step.
2. **Is the discount-cap bypass** (staff typing arbitrary unit prices, §2.8) intended pricing freedom or a
   hole to close? It changes the authorization redesign.
3. **`factory-website`**: does it exist in the live repo? Everything under `/api/site*` assumes it.
4. **May I add the two one-line WHERE guards** to `final-approve`/`approve` (§4.1) in Phase 1? It touches
   the protected approval path, so it needs your explicit yes.
5. **pos-share expiry**: OK to add an `expiresAt` (e.g. 30 days) to POS share links, or must old receipt
   links stay valid forever?
6. **Fabrication snapshot timing**: snapshot at *final approval* (my recommendation — matches "any pricing
   mutation resets the chain") or at *customer signature*?
7. **The three BOM bugs** (§4.7): fixing them changes cost/profit figures on open quotes. Fix now with the
   characterization tests, or freeze current behaviour and fix behind a flag?
8. **Migration baseline window**: introducing `drizzle-kit generate`+`migrate` needs one maintenance moment
   where the live schema is stamped as migration 0000. When?
