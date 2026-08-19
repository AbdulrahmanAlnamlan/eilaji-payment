# CLAUDE.md — Al-Thuraiya design tool → ERP

Working guide for any Claude session in this repository. Written for a session with no memory of previous
ones. Verified against the 2026-08-18 snapshot; `docs/00-AUDIT.md` holds the full evidence.

## What this is

A pnpm workspace monorepo on Replit for **Al-Thuraiya Plastic Factory** (Doha, Qatar — the country's only
uPVC profile manufacturer; brands QatarPlast, DohaPlast, Al-Thuraiya Door Panel; flagship system Al Rayyan 70).
Today it is a visual window/door configurator + quotation system with POS, being grown into a full ERP.
Currency QAR. Bilingual EN/AR with RTL. Deployed at `design.althuraiyaupvc.qa` (CORS allowlist:
`api-server/src/app.ts:42-47`).

## Stack

Node 24 · TypeScript 5.9 (composite project references) · pnpm workspaces with `catalog:` versions
(`pnpm-workspace.yaml`) · React 19 + Vite 7 + Tailwind 4 + shadcn/ui + wouter + TanStack Query 5 ·
Express 5 (all routes under `/api`, mounted in `app.ts`) · PostgreSQL 16 + Drizzle ORM 0.45.2 (pinned) ·
Zod 3.25.x (the DB layer uses the `zod/v4` compat subpath; generated contract code uses classic `zod`) ·
Orval 8 codegen · `@react-pdf/renderer` (client-side PDFs) · React Three Fiber (3D) · Clerk auth
(cookie sessions; Frontend-API reverse proxy at `/api/__clerk`) · Replit Object Storage via
`@google-cloud/storage` + sidecar credentials.

## Package map

| Package | Path | What |
|---|---|---|
| `@workspace/api-server` | `artifacts/api-server` | Express 5 API. `app.ts` = middleware/mounting; `index.ts` = boot + seeders; `routes/` per domain; `lib/` domain services |
| `@workspace/upvc-configurator` | `artifacts/upvc-configurator` | React SPA: configurator, carpentry, quotes, POS, dashboards, public share/sign/design-request pages |
| *(referenced, may be absent)* | `artifacts/factory-website` | Public marketing site — in `replit.md` but **not in the 2026-08-18 snapshot**; verify before touching `/api/site*` consumers |
| `@workspace/api-spec` | `lib/api-spec` | `openapi.yaml` (6,400+ lines, 123 paths) — **the contract source of truth** + `orval.config.ts` |
| `@workspace/api-client-react` | `lib/api-client-react` | **Generated** react-query hooks + `custom-fetch.ts` (hand-written mutator — the only editable file) |
| `@workspace/api-zod` | `lib/api-zod` | **Generated** zod contract schemas used by route validation |
| `@workspace/db` | `lib/db` | Drizzle schema (35 files → 39 tables) + `data/price-list-2026.ts` |
| `@workspace/costing` | `lib/costing` | `fabrication.ts` / `bom.ts` / `quote-cost.ts` — the money+fabrication engine, consumed by BOTH client (re-export) and server |
| `@workspace/window-designer` | `lib/window-designer` | `window-svg.tsx` (18-type renderer) + React-free subpaths `custom-grid`, `door-leaves`, `fan-hole` |
| `@workspace/dressing-model` | `lib/dressing-model` | Dressing-room geometry + billing (`billedDims`) — 2,609-line single file |
| `@workspace/integrations-openai-ai-server` | `lib/integrations-openai-ai-server` | OpenAI client (Replit integration); only real consumer is `wardrobePhoto.ts` |
| `@workspace/scripts` | `scripts` | Seeds + ~19 `e2e-*.ts` scripts (raw fetch + Clerk Admin API; 4 use playwright-core) |

## Commands

```bash
pnpm run typecheck                                  # MUST pass before anything is called done
pnpm --filter @workspace/api-spec run codegen       # openapi.yaml → api-client-react + api-zod (+ lib typecheck)
pnpm --filter @workspace/db run push                # drizzle-kit push (local dev only — see rules)
pnpm --filter @workspace/scripts run e2e-<name>     # e2e scripts: e2e-quote-cost, e2e-pos, e2e-sign-flow,
                                                    #   e2e-quote-payments, e2e-design-requests, e2e-site-content, …
pnpm --filter @workspace/scripts run seed           # seed catalog data
```

- Replit workflows (`.replit`): the run button "Project" is a **parallel validation suite** (typecheck +
  6 e2e workflows), not an app launcher. Restart the **API Server workflow in the live Replit workspace**
  after touching server routes (the API dev script is build-then-run, no watch mode). Note: the snapshot's
  `.replit` defines no app-start workflow; the live workspace does — trust the live workspace.
- Both servers require `PORT`; Vite also requires `BASE_PATH`. Other env: `DATABASE_URL`,
  `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY`, `PUBLIC_OBJECT_SEARCH_PATHS`, `BOOTSTRAP_ADMIN_EMAIL`.
- `python3` may be unavailable in the agent shell — use `node`/`tsx` for scripted math checks.

## The contract-first rule (always)

1. Edit `lib/api-spec/openapi.yaml`.
2. Run `pnpm --filter @workspace/api-spec run codegen`.
3. Then typecheck artifacts.

**Never hand-write a client hook or a zod contract schema.** The only hand-edited file in the generated
packages is `lib/api-client-react/src/custom-fetch.ts`.

**Validation order in route handlers stays as it is**: generated `@workspace/api-zod` contract schema
first, then the drizzle-zod insert schema.

**Schema changes**: Drizzle schema → generated migration → review the SQL → apply. Never `push-force`
against anything real. (Until the migration toolchain from Phase 1 lands, `push` is all there is — treat
any shared DB as production.)

## Domain glossary (EN / AR)

| Term | Arabic | Notes |
|---|---|---|
| Quotation | عرض سعر | The only customer document today (no invoices). Numbering `Q-<year>-NNNN` |
| Payment receipt | سند القبض | |
| Discount / VAT | الخصم / ضريبة القيمة المضافة | `vatPercent` is configurable, default 0 — no hardcoded rate |
| Outer frame | الإطار الخارجي | profileType `OUTER_FRAME` |
| Sash | الدرفة | `SASH` (door-sash preferred for `DR-*` products) |
| Glazing bead | حلية التزجيج | `GLAZING_BEAD` |
| Mullion (vertical) | العارض الرأسي | `MULLION` — mullion/transom substitute for each other if one is missing |
| Transom (horizontal) | العارض الأفقي | `TRANSOM` |
| Threshold | العتبة | `THRESHOLD` — no catalog profile carries it; always falls back to the outer frame |
| (aux) Coupler / Panel / Reinforcement | الوصلة / اللوح / التقوية | Extra profileTypes in the real catalog (TH-codes, systems Al-Rayyan 70 / Al-Wajba 60 / Al-Jazeera S60) |
| Wardrobe cabinet | خزانة | |
| Vanity | تسريحة | Billed separately (`vanityAreaSqm`), never part of `billedDims` |
| Mabkhara drawer | درج مبخرة | Incense drawer at cabinet bottom; rendering/description only — no billing; never on vanities |
| Signed | موقّع | |
| In production | قيد الإنتاج | |

**Quote lifecycle** — two parallel systems, do not conflate:
- Derived `lifecycle` (from timestamps, `lifecycleOf` in `routes/quotes.ts:86-92`):
  `draft` (مسودة) → `manager-approved` (اعتماد مدير المصنع) → `sent-to-customer` (أُرسل للعميل) →
  `customer-signed` (وقّع العميل) → `final-approved` (الاعتماد النهائي).
- Coarse free-text `status` column: `draft | sent | signed | accepted | rejected`.
- **Only `admin` and `factory_manager` can approve** (`canApproveQuotes`) — ordinary managers cannot.
- Any pricing mutation resets the whole signing chain and tombstones **sign** links (not design share links).
- Final approval requires a customer signature and writes the 27-day production plan
  (preparation 3 → fabrication 14 → quality 3 → delivery 7 calendar days).

**Roles**: `admin | manager | factory_manager | sales | staff`. Discount caps: admin 100 / manager &
factory_manager 10 / sales & staff 5 (`permissions.ts:9-15`). `isManagerLevel` (manager, factory_manager,
admin) sees costs and edits prices.

**`billedDims()`** (`lib/dressing-model`): billed linear run = cabinet coverage summed over every side that
carries cabinets (or a built corner unit) × the tallest column height; vanities and islands billed
separately at their own salesman-entered rates. Billed area = `(lengthMm + widthMm) × heightMm / 1e6`.

**Document numbering**: `Q-<year>-NNNN` (quotes), `POS-<year>-NNNN` (POS sales), `DR-<year>-NNNN`
(design requests). All scan-max+1 with unique-violation retry — no DB sequences.

## Gotchas

- **Arch tops**: body height = total height − arch rise; rise clamps to `[80mm, height/2]`, default 30% of
  height, **no width cap** (elliptical heads). Shaped types (ARC/FAN/TRAP/TRI/CIRC-01) can never take an
  arch. The rule lives in `lib/costing/src/fabrication.ts:262-271` and is duplicated in
  `configurator.tsx:623-624` — keep in sync.
- **Money rounding is a business rule with two regimes**: quotes floor every computed amount to the nearest
  0.5 QAR (`floorToHalf`, duplicated server+client in `lib/pricing.ts` — marked "keep both in sync"); POS
  uses plain 2-decimal rounding *on purpose*. Never "unify" them without asking.
- **POS `costPrice` null means UNKNOWN** — never treat as zero, or the profit figure lies (`posMoney.ts:36-38`).
- **Never switch web auth to bearer tokens.** The Clerk cookie + one-shot 401 retry
  (`setUnauthorizedRetryHandler` in `custom-fetch.ts:56-69, 393-403`, registered in `App.tsx:184-199`)
  exists because idle tabs' session cookies go stale; `setAuthTokenGetter` is deliberately unused on web.
- **`extraConfig` is the design snapshot and carries megabytes of base64 3D renders** — the 6 MB JSON body
  limit exists for it (`app.ts:64-67`). The server accepts it unvalidated from staff, so every reader must
  clamp; anonymous boundaries use the `lib/designSnapshot.ts` allow-lists ("Allow-list only, never a
  denylist"). `PRICING_KEY_RE` guards only the public design-request intake.
- **Cost data is firewalled**: `canSeeCost` gates it; it must never reach a salesman payload, a signing
  page, or any public route (`lib/quoteCost.ts:1-22`).
- **Boot mutates data**: `api-server/src/index.ts` runs 14 seed/backfill steps on every start (until
  Phase 1 moves them) — deleting a seeded reference project without editing the seeder list resurrects/
  re-deletes it.
- **Date logic is Asia/Qatar** via `qatarDay()`/`qatarHour()` — between midnight and 3am local, a UTC date
  is still "yesterday". No working-week (Sun–Thu) or Hijri logic exists yet.
- **Legacy browsers are a hard requirement**: build targets es2015 / chrome ≥ 49 for old office PCs; the
  showroom rule is ONE WebGL canvas per page, with 2D fallbacks.
- **Windows/dressing only** can have design share links; share durations 3/4 days are server-enforced,
  sign-link 7/14/30 is UI convention (server accepts 1–30).
- **Customer identity is the digits-only phone** (`phoneKey`, Arabic-Indic digits folded, +974 stripped);
  quote/project customer columns are a frozen printed snapshot by design — correcting a customer record
  must never rewrite an issued document.
- Zero TODO/FIXME markers exist — debt is documented in prose comments; grep for prose, not markers.

## Working rules

- Plan → confirm → implement. Never start a module without showing the data model and the plan.
- Tests with the code, not after. Unit tests (vitest) on all calculation logic; one new `e2e-*` script per
  workflow, wired as a Replit workflow with `isValidation = true`.
- `pnpm run typecheck` passes before anything is called done.
- Small, reviewable increments. One coherent change per commit, conventional messages, plus a note on what
  to test manually.
- When touching existing logic, show before/after behaviour and prove with a test that output is unchanged.
- When a business rule is ambiguous — a Qatar Labour Law edge case, a deduction rule, a valuation method,
  a rounding rule — stop and ask. List the options, give a recommendation. Never guess, never silently
  default.
- Never change the quote lifecycle, approval logic, share/sign-link behaviour or any pricing formula
  without asking first.
- Log every architectural decision in `docs/DECISIONS.md` with the reasoning.
- Say plainly when you think a request is a mistake.
- Keep `docs/` and `replit.md` current — `replit.md` has known drift (see `docs/00-AUDIT.md` §3.10);
  fix it as you touch each area.
