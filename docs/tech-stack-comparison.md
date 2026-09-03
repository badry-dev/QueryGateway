# IntakeGateway + QueryGateway — Tech Stack Comparison and Consolidation Assessment

**Date:** 2026-09-03
**Scope:** `badry-dev/IntakeGateway` @ `main` (125 commits), `badry-dev/QueryGateway` @ `main` (169 commits)
**Question:** Should these two projects be combined under one product?

---

## 1. Verdict

**Yes — combine them, but not by merging the two codebases as they stand.**

The two systems are the inbound and outbound halves of the same product: IntakeGateway pulls data
from HTTP APIs into databases; QueryGateway publishes database queries as HTTP APIs. Same operator,
same credentials, same scheduling problem, same observability problem, same admin console problem.
Keeping them separate means maintaining two connection managers, two schedulers, two auth models,
two credential vaults, and two admin SPAs forever.

The catch: they share almost no *implementation*. Every foundational choice diverged —
sync vs. async SQLAlchemy, SQLite vs. PostgreSQL, loguru vs. structlog, Ant Design vs.
Tailwind/shadcn, static shared token vs. JWT, Python 3.11 vs. 3.14. There is roughly
**~16,700 backend LOC and ~14,200 frontend LOC** across both, with near-zero directly reusable
overlap despite ~60% conceptual overlap.

**Recommended path: converge onto QueryGateway's platform, port IntakeGateway's domain logic onto
it, ship as a monorepo with two deployables and one admin console.** Estimated 16–30 developer-weeks
to full convergence. See §7 for the staged plan and §8 for the cheaper alternatives.

---

## 2. What each project actually is

| | **IntakeGateway** | **QueryGateway** |
|---|---|---|
| **Direction** | HTTP API → database (ingestion) | Database → HTTP API (publication) |
| **Core artifact** | A *Task*: source endpoint + auth + field mapping + upsert rules + cron | An *Endpoint*: parameterized Oracle SQL + auth policy + live/snapshot strategy |
| **Destinations / sources** | Oracle, PostgreSQL, MySQL (claimed) | Oracle only |
| **Execution model** | Async, queued, long-running batch jobs | Synchronous request/response + scheduled snapshot refresh |
| **Key differentiator** | Connector/normalizer/validator/mapper/runner pipeline, OAuth2 token cache, cursor-based incremental fetch, SSRF guard, rate-limit handling | Bind-parameter-only SQL execution, schedule-owned parameter bindings, snapshot coverage/filter semantics, per-endpoint auth policies |
| **Backend LOC** | 8,649 (38 modules) | 8,055 (64 modules) |
| **Frontend LOC** | 5,797 (35 files) | 8,452 (71 files) |
| **Backend test LOC** | 7,368 (30 files) | 7,741 (28 files) |
| **First / last commit** | 2025-09-24 / 2026-09-02 | 2026-03-03 / 2026-09-02 |

Both are actively developed and were last touched the same day. Neither is abandoned.

---

## 3. Stack comparison

### 3.1 Backend runtime

| Concern | IntakeGateway | QueryGateway | Compatible? |
|---|---|---|---|
| Python | **3.11** (`target-version = "py311"`) | **3.14** (`requires-python`, mypy `python_version = "3.14"`) | ⚠️ One-way |
| Web framework | FastAPI 0.141.1 | FastAPI 0.141.1 | ✅ Identical |
| ASGI server | uvicorn[standard] 0.32.1 | uvicorn[standard] 0.52.3 | ✅ Bump |
| Validation | pydantic 2.10.6 / pydantic-settings 2.7.1 | pydantic-settings 2.15.0 | ✅ Bump |
| ORM | SQLAlchemy 2.0.36, **sync** (`create_engine`, `Session`) | SQLAlchemy 2.0.52, **async** (`create_async_engine`, `AsyncSession`) | ❌ Structural |
| App-state DB | **SQLite** (`sqlite:///./intakegateway_app.db`) | **PostgreSQL** (asyncpg + psycopg2-binary) | ❌ Structural |
| Schema mgmt | Alembic (4 revisions) **and** `Base.metadata.create_all()` at startup | Alembic only (5 revisions), enforced one-shot `migrate` container | ⚠️ IG is inconsistent |
| Oracle driver | `oracledb==3.4.2`, imported eagerly | `oracledb>=4.0.2,<5`, isolated in `requirements-oracle.txt`, imported lazily | ⚠️ Major version gap |
| Async job execution | **Celery 5.4.0 + Redis 5.0.8** (separate worker process) | None — in-process only | ❌ Different topology |
| Scheduler | APScheduler 3.10.4, **separate process** (`python app/services/scheduler.py`) | APScheduler 3.11.3, **in-process** via FastAPI lifespan | ⚠️ Reconcilable |
| Cron parsing | `croniter==2.0.7` | APScheduler `CronTrigger` + custom builder | ⚠️ Reconcilable |
| Logging | **loguru 0.7.2** (f-string style) | **structlog 26.1.0** (JSON, mandated correlation fields) | ❌ Structural |
| Crypto | `cryptography==50.0.1`, Fernet, **str in / str out** | `cryptography==50.0.0`, Fernet, **str in / bytes out** | ⚠️ Serialization differs |
| HTTP client | httpx 0.27.2 (core dependency — it *is* the product) | httpx 0.28.1 (health checks only) | ✅ Bump |
| JSON path | `jsonpath-ng==1.6.1` | — | ✅ IG-only |
| Auth libs | — (no JWT, no bcrypt) | `PyJWT==2.13.0`, `bcrypt==5.0.0` | ❌ IG has no identity layer |

### 3.2 Frontend

| Concern | IntakeGateway | QueryGateway | Compatible? |
|---|---|---|---|
| React | 18.2 | 18.3 | ✅ |
| Build | **Vite 8.2** | **Vite 6.4** | ⚠️ Two majors apart |
| Router | react-router-dom **6.20** | react-router-dom **7.18** | ⚠️ One major apart |
| Data fetching | @tanstack/react-query 5 + axios | @tanstack/react-query 5 + axios | ✅ Identical pattern |
| Client state | **zustand 4.4** | React context (`AuthProvider`) only | ⚠️ |
| **UI system** | **Ant Design 6.3 + @ant-design/icons** | **Tailwind 3.4 + shadcn/ui (Radix) + lucide-react** | ❌ **Highest-cost conflict** |
| Styling | antd tokens, inline styles, `theme.ts` | Tailwind + `class-variance-authority` + `tailwind-merge` | ❌ |
| Editor | — | CodeMirror 6 (`@uiw/react-codemirror`, `@codemirror/lang-sql`) | ✅ QG-only |
| Dates | date-fns 4 + dayjs 1.11 (both) | — | ⚠️ IG carries two date libs |
| Lint | ESLint **8** (legacy `.eslintrc`, `--ext` flags) | ESLint **9** (flat config, `typescript-eslint`) | ⚠️ |
| Format | **none** | Prettier 3.4 + `prettier-plugin-tailwindcss`, `prettier:check` in CI | ❌ IG has no formatter gate |
| Test | vitest 4 + Testing Library + jsdom 29 | vitest 4 + Testing Library + jsdom 25 + axios-mock-adapter | ✅ |

### 3.3 Quality gates and engineering discipline

| Gate | IntakeGateway | QueryGateway |
|---|---|---|
| Ruff rule set | `E, F, W, I, UP` | `E, W, F, I, B, C4, UP, **S** (bandit), **T20**` |
| Type checking | **none** | **mypy `strict = true`** + pydantic plugin |
| Coverage gate | `fail_under = 50` | coverage reported, no hard floor |
| CI workflows | **1** (`ci.yml`) | **6** (backend, frontend, docker, security-scan, dependency-review, actions-lint) |
| Dependabot | ❌ | ✅ |
| CODEOWNERS | ❌ | ✅ |
| SHA-pinned actions | ✅ | ✅ |
| `docs/` files | 1 | 15 |
| Root governance docs | README, SECURITY.md (27KB), AGENTS.md, AI_WORKFLOW.md, SECURITY_AI.md, CLAUDE.md | README, per-area `.github/instructions/*`, CLAUDE.md |

**QueryGateway enforces a materially higher bar.** Not by a little — strict mypy plus bandit rules
plus six gated workflows versus one workflow with no type checking is a different class of rigor.

### 3.4 Deployment topology

**IntakeGateway** (`docker-compose.yml`) — 4 services: `redis`, `api`, `worker`, `scheduler`.
No database container (SQLite on a bind mount). Backend bind-mounted with `--reload`. Redis
password-gated and unpublished. This is a **development** compose file with production-ish
hardening bolted on; there is a separate `compose.production.yml`.

**QueryGateway** (`docker-compose.yml`) — 5 services: `db` (postgres:16), `migrate` (one-shot),
`api`, `web` (nginx), optional `oracle` (XE, profile-gated). **Two segmented networks**: `edge`
(nginx↔api, fixed `10.31.0.0/24` so `FORWARDED_ALLOW_IPS` can be scoped to exactly that hop) and
`backend` (api↔data tier). API is not published to the host. Postgres and Oracle bound to
`127.0.0.1` only.

QueryGateway's compose is the more defensible production topology by a wide margin.

---

## 4. Where the two genuinely overlap

These are the modules that would be written once instead of twice:

| Capability | IntakeGateway today | QueryGateway today | Consolidation value |
|---|---|---|---|
| **DB connection registry** | `connection_storage.py` (encrypted `connections.enc` file, fcntl/msvcrt locking) + `connection_pool.py` (engine cache, Oracle/PG/MySQL URL builder) | `models/connection.py` + `repositories/connection.py` + `services/connection.py` (Postgres rows, Fernet `LargeBinary`) | **High.** Same entity, two incompatible stores. |
| **Credential encryption** | `core/encryption.py` — Fernet, singleton, str→str, dev-mode key generation | `crypto.py` — Fernet, str→bytes, no dev fallback | **High.** ~identical, 5-minute unification. |
| **Scheduling** | APScheduler + croniter, separate process, cron string only, auto-pause after N failures | APScheduler in-lifespan, friendly cron builder + IANA timezones + schedule-owned parameter bindings + next-3-run preview | **High.** QG's model is strictly richer. |
| **Run / job history** | `task_run`, `task_run_log`, `task_log` tables + Runs/RunDetail pages | `job_run`, `access_log` tables + health dashboard | **High.** One observability model. |
| **Admin identity** | `API_TOKEN` shared secret, no UI login | JWT admin login, `RequireAuth`, bcrypt, per-endpoint auth methods | **High.** IG has no real identity story. |
| **Settings & health** | `/health` returning `{status, env}` | Settings table + full health dashboard (API/Postgres/Oracle/scheduler/recent jobs/stale snapshots) | **Medium.** QG's is production-grade. |
| **Oracle metadata introspection** | `oracle_metadata.py` (`USER_TAB_COLUMNS` for mapping targets) | `sql/executor.py` (`cursor.description` for output schema) | **Medium.** Complementary. |
| **Admin SPA shell** | antd Layout/Sider/Menu + react-query | shadcn Layout + RequireAuth + react-query | **High**, but expensive (§5.4). |
| **API client layer** | `api/client.ts` class wrapping axios | `lib/api.ts` module + `useResourceMutations` | **Medium.** Same pattern, different shape. |

Roughly **40–50% of each backend is platform plumbing that would be shared**. The remaining
50–60% is genuinely distinct domain logic worth keeping separate regardless.

---

## 5. Conflicts, ranked by cost to resolve

### 5.1 ❌ Python 3.11 vs. 3.14 — with a Celery blocker underneath
QueryGateway *requires* 3.14 (asyncpg ≥0.31 CPython 3.14 wheels). IntakeGateway targets 3.11 and
depends on **Celery 5.4.0**, whose supported-interpreter matrix does not extend to 3.14.
**This must be validated before any shared-runtime decision.** If Celery cannot run on 3.14, the
choices are: (a) upgrade Celery and validate, (b) replace the queue with an async-native
alternative (`arq`, `dramatiq`), or (c) keep the intake worker on a separate 3.11/3.12 image.
Option (b) aligns better with an async codebase; option (c) is the low-risk fallback.

### 5.2 ❌ Sync vs. async SQLAlchemy
IntakeGateway's routes, services, and runner are synchronous end to end (`Session`, `def` handlers,
Celery workers). QueryGateway is async end to end (`AsyncSession`, `async def`, `anyio.to_thread`
for the blocking Oracle driver). These do not compose in one process. Porting IntakeGateway to
async touches every route, every service, and the entire runner pipeline — **this is the single
largest backend line item.**

*Mitigation:* QueryGateway already demonstrates the correct pattern for blocking drivers
(`anyio.to_thread.run_sync` around `oracledb`). The intake runner can keep its blocking write path
inside a thread while the surrounding API becomes async. That reduces the port to the route/service
boundary rather than the whole pipeline.

### 5.3 ❌ SQLite + `create_all` vs. PostgreSQL + Alembic
IntakeGateway calls `Base.metadata.create_all()` in its lifespan **while also shipping four Alembic
revisions** — schema is managed twice, by two mechanisms, and SQLite needs WAL pragmas and a
`JSONText` shim (`db/types.py`) to emulate what Postgres does natively. QueryGateway is
Alembic-only and gates API startup on `migrate` completing.

Merging means: one Postgres instance, one Alembic revision graph (the two graphs must be merged or
branched — they cannot both target one `alembic_version` table as-is), delete `create_all`, delete
the `JSONText` shim in favor of `JSONB`.

### 5.4 ❌ Ant Design vs. Tailwind + shadcn/ui
~5,800 LOC of IntakeGateway frontend is coupled to antd components, antd theme tokens, and inline
styles. QueryGateway is Tailwind + Radix primitives with its own `components/ui/*` kit and a
Prettier/Tailwind class-ordering gate.

There is no automated migration. Shipping both in one bundle means two CSS systems, two icon sets,
and ~800KB of avoidable payload. **This is the most expensive single item and the one most safely
deferred** — it can be staged behind a route boundary and paid down page by page.

### 5.5 ❌ Incompatible authentication models
IntakeGateway: one static `API_TOKEN` compared with `hmac.compare_digest`, checked as a router
dependency, fail-closed in production, **no UI login and no user concept.**
QueryGateway: env-seeded single admin, bcrypt hash, JWT with `sub`/`exp`/`iat`, `HTTPBearer`
dependency, `RequireAuth` route guard, plus a separate per-endpoint auth-method system
(Bearer/Basic/API key) for the data plane.

QueryGateway's model is the only one that survives a merge. IntakeGateway's management routes
would move behind `get_current_admin`. Note that **neither project has multi-user support** —
both are single-admin. If the combined product needs teams or RBAC, that is net-new work in both
scenarios and is a reason to build it once, in the merged product.

### 5.6 ⚠️ Configuration collision
IntakeGateway: `case_sensitive=True`, `UPPER_SNAKE` names, `.env`.
QueryGateway: `case_sensitive=False`, `lower_snake` names, `.env`.
Both consume `ENCRYPTION_KEY` and both define an environment flag (`APP_ENV`) with different
allowed values and different production-gating behavior. Both read the same `.env` filename.
In one process these collide. One `Settings` class, one naming convention, one `.env` schema.

### 5.7 ⚠️ Route namespace divergence
IntakeGateway: `/api/v1/tasks`, `/api/v1/runs`, `/api/v1/schedules`, `/api/v1/connections`.
QueryGateway: strict `/api/v1/admin/*` (console) and `/api/v1/data/*` (consumers), documented as a
hard convention with versioned breaking changes.

QueryGateway's split is the better contract and is already load-bearing for its security model
(every `/data/*` request is authenticated, no exceptions). Intake routes move under
`/api/v1/admin/intake/*`.

### 5.8 ⚠️ Logging: loguru vs. structlog
QueryGateway mandates structured JSON with `request_id`, `user`, `endpoint`, `status`,
`duration_ms`, `method`, `client_ip`, `event` — and scheduler jobs add `job_id`, `run_id`,
`row_count`, `success`. IntakeGateway uses loguru f-strings with ad-hoc redaction helpers.
Mechanical to port, but it touches every log call site (~hundreds).

### 5.9 ⚠️ Credential storage: encrypted file vs. database
`connections.enc` with cross-process advisory locking (fcntl/msvcrt) exists specifically because
IntakeGateway's API, worker, and scheduler are three processes with no shared transactional store.
Once there is a shared PostgreSQL, that file — and its locking code, and its
"refuse to run on platforms without a locking primitive" branch — is deleted outright. **This is a
concrete, immediate win from consolidation.**

---

## 6. Defects and debt surfaced during review

These are worth fixing regardless of the merge decision.

| # | Repo | Finding |
|---|---|---|
| 1 | IntakeGateway | **`backend/app/services/connection_pool.py:36` hardcodes `C:\oracle\instantclient_23_0`** as the Oracle thick-mode client path. Non-configurable and Windows-only; thick mode is silently unavailable in the Linux containers the project ships. QueryGateway does this correctly via `ORACLE_CLIENT_LIB_DIR`. |
| 2 | IntakeGateway | **PostgreSQL and MySQL destinations are advertised but undeliverable.** `connection_pool.py` builds `postgresql+psycopg2://` and `mysql+pymysql://` URLs, but **neither `psycopg2` nor `PyMySQL` appears in any requirements file or the Dockerfile.** Both destination types fail at engine creation with `ModuleNotFoundError`. The README claims all three. |
| 3 | IntakeGateway | Two stale requirements files — `requirements-minimal.txt` (FastAPI 0.104.0) and `requirements-simple.txt` (FastAPI 0.100.0) — pin releases four years out of date next to the real `requirements.txt` (0.141.1). Delete or document. |
| 4 | IntakeGateway | Schema managed twice: `create_all()` in lifespan **and** four Alembic revisions. Divergence is a matter of time. |
| 5 | IntakeGateway | No type checking and no formatter gate. QueryGateway runs strict mypy + Prettier in CI. |
| 6 | IntakeGateway | Duplicated comment line in `core/config.py` (`# Auto-pause a schedule after...` appears twice). Cosmetic. |
| 7 | IntakeGateway | Ships both `date-fns` and `dayjs`; antd already depends on dayjs. Drop one. |
| 8 | Both | `oracledb` major-version split (3.4.2 vs. ≥4.0.2). One version in a merged runtime; note that oracledb 4.x thick mode requires Oracle Client 19+, which QueryGateway's image already bundles (Instant Client 19.32). |
| 9 | Both | Single hardcoded admin identity, no multi-user, no RBAC, no audit of *who* changed configuration. Acceptable for a self-hosted single-operator tool; a blocker for team or multi-tenant use. |

---

## 7. Recommended plan — converge onto QueryGateway's platform

### 7.1 Direction of travel, and why

**Adopt QueryGateway's foundations. Port IntakeGateway's domain logic onto them.**

| Dimension | Winner | Why |
|---|---|---|
| Runtime | QG (async, 3.14) | Async is required for the request-serving data plane; sync is not required for anything IG does that a thread pool cannot cover. |
| Data tier | QG (PostgreSQL) | SQLite forces the encrypted-file connection store, the `JSONText` shim, and WAL workarounds. All three vanish. |
| Migrations | QG (Alembic-only + gated `migrate`) | IG's dual mechanism is a latent production incident. |
| Logging | QG (structlog) | Mandated correlation fields; already documented as a project convention. |
| Identity | QG (JWT + bcrypt + per-endpoint policies) | IG has no UI login at all. |
| UI | QG (Tailwind + shadcn) | Prettier-gated, no runtime theme provider, smaller payload, already the larger surface (8.4k vs. 5.8k LOC). |
| CI / typing | QG (6 workflows, strict mypy, bandit) | Strictly higher bar; adopting it raises IG, not the reverse. |
| Container topology | QG (segmented networks, nginx, one-shot migrate) | Defensible in production. |
| **Async job execution** | **IG (Celery + Redis worker)** | **QG has none.** Long-running, retryable, parallelizable imports need a real queue. Snapshot refresh should move onto it too. |
| **Domain pipeline** | **IG (connector/normalizer/validator/mapper/runner)** | Genuinely valuable and fully portable — no framework coupling beyond `Session` and loguru. |
| **SSRF guard, OAuth2 token cache, rate-limit handling, cursor watermarks** | **IG** | Net-new capability QG does not have. Keep all of it. |

The asymmetry is clear: QueryGateway wins on *platform*, IntakeGateway wins on *domain logic and
execution topology*. That is exactly the split that makes a merge worthwhile — you keep the best
half of each.

### 7.2 Target architecture

```
                       ┌──────────────────────────────┐
                       │   Admin SPA (one console)     │
                       │   React 18 · Vite · TS        │
                       │   Tailwind + shadcn/ui        │
                       │   react-query + axios         │
                       │   JWT session (RequireAuth)   │
                       └──────────────┬───────────────┘
                                      │ /api/v1/admin/*
                       ┌──────────────▼───────────────┐
                       │   nginx (edge network)        │
                       └──────────────┬───────────────┘
                                      │
             ┌────────────────────────┴────────────────────────┐
             │                                                  │
   ┌─────────▼──────────┐                          ┌────────────▼─────────┐
   │  Query plane (API) │                          │  Intake plane (API)  │
   │  FastAPI · async   │                          │  FastAPI · async     │
   │  /api/v1/data/*    │                          │  /admin/intake/*     │
   │  /admin/endpoints  │                          │  /admin/tasks        │
   └─────────┬──────────┘                          └────────────┬─────────┘
             │                                                  │
             └──────────────┬───────────────────────────────────┘
                            │  shared packages
        ┌───────────────────▼────────────────────┐
        │  core: config · crypto · logging(JSON) │
        │  auth: JWT admin + endpoint policies   │
        │  connections: registry + engine pool   │
        │  scheduling: APScheduler + bindings    │
        │  runs: job_run · access_log · health   │
        └───────────────────┬────────────────────┘
                            │
        ┌───────────────────▼────────────────────┐
        │  PostgreSQL 16  (state, snapshots,     │
        │  encrypted credentials, run history)   │
        │  Redis  (queue broker)                 │
        │  Worker (imports + snapshot refresh)   │
        │  Oracle / PostgreSQL / MySQL (external)│
        └────────────────────────────────────────┘
```

One console, one identity, one Postgres, one credential vault, one scheduler, one run-history model.
Two backend deployables, because the scaling profiles genuinely differ: the query plane is
request-latency-bound; the intake plane is worker-throughput-bound.

### 7.3 Staged plan

| Phase | Work | Effort | Exit criterion |
|---|---|---|---|
| **0. Monorepo, no code change** | Merge both repos into one with `apps/query`, `apps/intake`, `packages/`. Adopt QG's CI matrix over both. Turn on mypy for IG in non-blocking mode; add Prettier. Freeze new antd surface area. | 1–2 wks | Both apps build, test, and deploy exactly as before, from one repo, under one CI. |
| **1. Identity and shell** | One `Settings` class and `.env` schema. One JWT admin auth; IG management routes move behind `get_current_admin`. One SPA shell with a login; IG pages mounted inside it (antd temporarily allowed behind a route boundary). Route namespaces normalized to `/api/v1/admin/*`. | 3–5 wks | One login, one nav, both feature sets reachable. |
| **2. Data tier** | IG app state SQLite → PostgreSQL. Merge the two Alembic graphs. Delete `create_all()` and `db/types.JSONText`. Migrate `connections.enc` → `connections` table; **generalize QG's `OracleConnection` into a `Connection` with a `db_type` discriminator** (Oracle/PostgreSQL/MySQL) and ship the missing `psycopg2`/`PyMySQL` drivers (fixes §6 #2). Retire the file-locking module. | 4–8 wks | One database, one migration graph, one credential store, three destination types actually working. |
| **3. Execution** | One scheduler service. Decide the queue (validate Celery on 3.14, else `arq`/`dramatiq`, else pin the worker to its own image). Move snapshot refresh onto the queue. Unify `task_run`/`job_run` into one run model + one health dashboard. Port loguru → structlog. | 4–8 wks | One scheduler, one queue, one run-history table, one JSON log stream. |
| **4. UI convergence** | Port IG's 8 pages from antd to Tailwind/shadcn, page by page. Drop antd, `@ant-design/icons`, and one of date-fns/dayjs. Align Vite 6↔8 and react-router 6↔7. | 4–8 wks | One design system; bundle size down materially. |
| **Ongoing** | Fix §6 findings; decide multi-user/RBAC. | — | — |

**Total: 16–31 developer-weeks (≈4–7 months at one focused engineer).**
Phases 0–1 alone (4–7 weeks) deliver the single most visible win: one product, one login, one console.

### 7.4 Sequencing rules

1. **Phase 0 must not change behavior.** Repo topology and CI only. Anything else invites a
   multi-month rewrite with no shippable intermediate.
2. **Resolve the Python/Celery question before Phase 3, not during it.** It determines whether the
   queue is a port or a replacement — a several-week swing.
3. **Defer the UI (Phase 4) to last.** It is the most expensive and the least risky to postpone;
   two design systems behind one login is ugly but shippable.
4. **Do not merge the two Alembic graphs by hand under time pressure.** Two revision trees against
   one `alembic_version` table is a data-loss shape. Branch labels or a squashed baseline, decided
   deliberately.

---

## 8. Alternatives, honestly costed

| Option | What it is | Cost | Value | Verdict |
|---|---|---|---|---|
| **A. Full single application** | One FastAPI app, one deployable, one SPA | 20–35 dev-wks | Maximum coherence | **Over-merged.** Request-latency and worker-throughput planes want independent scaling and deploy cadence. |
| **B. Monorepo + shared packages, two deployables, one console** ⭐ | §7.2 | **16–31 dev-wks** | ~85% of A's value | **Recommended.** Kills all duplication that matters; keeps the planes independently scalable. |
| **C. Monorepo, shared CI/conventions only** | Same repo, no shared code | 2–4 dev-wks | Low | Cheap coherence, zero compounding benefit. Connections/auth/scheduler stay duplicated forever. |
| **D. Status quo — two repos** | Nothing changes | 0 | 0 | Every capability gets built twice. IG's missing identity layer and PG/MySQL drivers never get QG's rigor applied to them. |

**If budget is the constraint: do C now, and A/B's Phase 0 + Phase 1 next quarter.** Even the
identity unification alone (Phase 1) is worth its cost — IntakeGateway currently has no admin
login, which is the most significant single gap between the two projects.

---

## 9. Open decisions requiring your input

1. **Queue technology on Python 3.14.** Validate Celery 5.4→latest on 3.14. If it fails: `arq`
   (async-native, Redis, small) is the natural fit for an async codebase; `dramatiq` if you want
   Celery-like semantics. Fallback: pin the intake worker to its own 3.12 image.
2. **Multi-user / RBAC.** Both projects are single-admin. If the combined product needs teams,
   build it once during Phase 1 — retrofitting after Phase 4 costs several times more.
3. **Product name and namespace.** "Gateway" with Intake and Query planes is the obvious framing,
   but this is a positioning decision, not a technical one.
4. **Destination breadth.** Does the query plane also need PostgreSQL/MySQL sources (matching
   intake's advertised breadth), or does Oracle-only remain the query-plane contract? This changes
   the shape of the shared `Connection` entity in Phase 2.
5. **Snapshot storage.** Query-plane snapshots are PostgreSQL JSONB today. If intake volumes push
   the shared Postgres hard, snapshots are the first thing to move to object storage.

---

## 10. Summary

- The two projects are **complementary halves of one product**, not competitors. Combining is
  strategically correct.
- They share **~60% of concepts and near-0% of implementation**. Every foundational choice diverged.
- **QueryGateway has the better platform** (async, PostgreSQL, structlog, JWT, strict mypy, bandit,
  6 CI workflows, segmented container networks). **IntakeGateway has the better execution topology
  and the more valuable domain logic** (Celery worker, connector/normalizer/mapper/runner pipeline,
  SSRF guard, OAuth2 token cache, cursor watermarks).
- **Converge onto QueryGateway's platform; port IntakeGateway's domain logic onto it.**
  Monorepo, shared packages, one admin console, two backend deployables.
- **16–31 developer-weeks** for full convergence; **4–7 weeks** for the visible win (one product,
  one login, one console).
- Two IntakeGateway defects should be fixed regardless: the **hardcoded Windows Oracle client path**
  and the **PostgreSQL/MySQL destinations that ship without their drivers**.
