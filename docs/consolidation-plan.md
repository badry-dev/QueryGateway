# Consolidation Plan — Module-by-Module Adoption

**Companion to** `docs/tech-stack-comparison.md`. That document answers *whether* to combine.
This one answers *what gets adopted from where*, at implementation level, and *how long it takes
under AI-assisted development*.

**Rule applied throughout:** take the better implementation regardless of which repo it lives in.
The verdict is per module, not per project. Neither codebase wins across the board.

---

## 1. Backend — module-by-module

### 1.1 Foundations (QueryGateway wins outright)

| Module | Adopt | Why | Action for IntakeGateway |
|---|---|---|---|
| **Declarative base / PK strategy** | **QG** `models/base.py` — `UUIDPrimaryKeyMixin`, `TimestampMixin` with `server_default=func.now()` + `onupdate` | IG uses integer autoincrement plus an `ID_TYPE` shim that exists only to paper over SQLite. UUIDs are correct when rows are minted by API, worker, and scheduler processes independently. | Migrate all IG tables to UUID PKs. Delete `db/types.py`. |
| **Repository layer** | **QG** `repositories/base.py` — `BaseCrudRepository[ModelT]` (PEP 695 generics), `__init_subclass__` validation that fails at class-definition time, mapper-introspection allow-list on `update()`, `_IMMUTABLE_AUDIT_FIELDS` | Genuinely good code. The `inspect(self.model).column_attrs` allow-list is materially safer than a `hasattr` check, and the comment explains why. IG has **no repository layer** — routes touch `Session` directly. | Build IG's entities on this base. ~6 new repositories. |
| **Engine / session** | **QG** `database.py` — async engine, `async_sessionmaker`, `expire_on_commit=False` | — | Port IG's sync `SessionLocal` usage. |
| **Global error handling** | **QG** `exceptions.py` — three handlers; `jsonable_encoder` on 422 so a `ValueError` in a validator can't turn a 422 into a 500; generic 500 body with detail only in logs | IG has **no global handlers**. Unhandled exceptions leak framework detail. | Register QG's three handlers on the intake app. |
| **Request correlation** | **QG** `middleware.py` — pure-ASGI (not `BaseHTTPMiddleware`), request-ID allow-list regex, 64-char cap matching the DB column | The docstring records why `BaseHTTPMiddleware` was rejected: it wraps `call_next` in a new task, which breaks task-bound asyncpg connections. That is hard-won knowledge; do not re-derive it. | Adopt as-is. |
| **Migrations** | **QG** — Alembic only, gated by the one-shot `migrate` compose service | IG runs `create_all()` in lifespan **and** ships four Alembic revisions. | Delete `init_app_database()`. Merge revision graphs (see §3.3). |
| **Container topology** | **QG** — `edge`/`backend` network split, fixed `10.31.0.0/24` so `FORWARDED_ALLOW_IPS` scopes to exactly the nginx hop, API unpublished, data tier on loopback | IG's compose bind-mounts source with `--reload`. | Adopt QG's; add `worker` + `redis` services to it. |

### 1.2 Configuration and secrets (split verdict)

| Module | Adopt | Detail |
|---|---|---|
| **Settings class** | **QG's shape, IG's content** | Take QG's `SettingsConfigDict`, lower_snake naming, and — importantly — its **fail-fast validators that actually probe**: `_validate_bcrypt_hash` runs `bcrypt.checkpw(b"probe", value)` at startup so a malformed hash is a boot failure rather than a 500 on every login; `_validate_fernet_key` constructs a `Fernet` for the same reason; `_reject_wildcard_origin` refuses to boot with `CORS_ORIGINS=*` under `allow_credentials=True`. Then carry over IG's operational settings: `HTTP_TIMEOUT_SECONDS`, `HTTP_MAX_RESPONSE_MB`, `OAUTH_TOKEN_REFRESH_SKEW_SECONDS`, `HTTP_RETRY_AFTER_MAX_SECONDS`, `BACKFILL_MAX_WINDOW_DAYS`, `ALLOWED_SOURCE_HOSTS`, `SCHEDULE_MAX_CONSECUTIVE_FAILURES`. |
| **Crypto** | **QG's `crypto.py` + IG's `rotate_key`** | QG's is 40 lines, no singleton, no dev fallback. IG's `EncryptionService` **generates a temporary key when `APP_ENV=dev-only`** — a footgun that silently produces undecryptable data. Drop it. But IG has `rotate_key(old, new, ciphertext)` and QG has **no key rotation at all**; a merged product storing credentials for three database types needs it. Port that one method onto QG's module. |
| **Log redaction** | **IG** | QG has nothing comparable. Keep IG's `mask_headers`, `_is_secret_header` (substring matching, so *user-configured* API-key header names get masked too), `_redact_url_for_log` (parser-based, drops query and userinfo), and `_redact_cursor` (length + SHA-256 prefix rather than the value). Re-implement on structlog processors. |

### 1.3 Authentication (QueryGateway wins; keep one IG piece)

| Module | Adopt | Detail |
|---|---|---|
| **Admin identity** | **QG** | JWT + bcrypt + `HTTPBearer(auto_error=False)`, router-level `dependencies=[Depends(get_current_admin)]`, constant-time username comparison (bcrypt runs even on username mismatch), and `verify_password` handling bcrypt 5.0's *raise* on >72-byte input in both directions. IG has no UI login and no user concept. |
| **Machine-to-machine token** | **IG** (keep, demoted) | IG's `hmac.compare_digest` static-token path is genuinely useful for CI and automation calling the intake API. Keep it as an **optional secondary credential** alongside JWT — not as the primary auth. |
| **Data-plane auth policies** | **QG** | `auth_method` per endpoint (Bearer/Basic/API key), `generate_api_key` with ~192 bits entropy, rotation endpoints. Extends naturally to intake webhooks later. |

### 1.4 Database connectivity (merge required — neither is complete)

| Concern | Adopt | Detail |
|---|---|---|
| **Where connections live** | **QG** (Postgres rows, Fernet `LargeBinary`, repository + service) | This **deletes `connection_storage.py` entirely** — the encrypted file, the fcntl/msvcrt dual-platform locking, the `_file_lock` context manager, and the "refuse to run on platforms without a locking primitive" branch. All of it exists solely because IG's three processes share no transactional store. Best single code-deletion win in the merge. |
| **What a connection can be** | **IG** (`db_type` discriminator) | Generalize QG's `OracleConnection` → `Connection` with `db_type ∈ {oracle, postgresql, mysql}`, keeping QG's `pool_min/max/timeout`, `query_timeout`, `mode`, `is_active`, and the service-name/SID exclusivity rule. **Ship `psycopg2-binary` and `PyMySQL`** — IG builds those URLs today but neither driver is in any requirements file (see companion doc §6 #2). |
| **Engine caching** | **IG** (`connection_pool.py` engine/session-factory cache) | QG opens a fresh `oracledb.connect` per query. IG's per-connection engine cache is the better pattern for a system that will now serve both planes. Rebuild it on the DB-backed registry. |
| **Oracle client init** | **QG** | `ORACLE_CLIENT_LIB_DIR`, called once in lifespan, logs a warning rather than crashing on failure. IG hardcodes `C:\oracle\instantclient_23_0` at `connection_pool.py:36` — Windows-only, so thick mode is dead in the Linux containers it ships. Straight replacement. |
| **Driver version** | **QG** (`oracledb>=4.0.2,<5`, lazy import, isolated `requirements-oracle.txt`) | IG pins 3.4.2 and imports eagerly. QG's image already bundles Instant Client 19.32, which satisfies 4.x thick mode. |

### 1.5 SQL execution (clean split — read vs write)

| Direction | Adopt | Detail |
|---|---|---|
| **Read path** | **QG** `sql/executor.py` + `sql/param_models.py` | Bind-parameters-only, `conn.call_timeout`, `anyio.to_thread.run_sync` so the blocking driver never touches the event loop, and `build_param_model()` constructing a **dynamic Pydantic model per endpoint** so request params are typed and coerced before they reach the driver. IG has nothing comparable. |
| **Write path** | **IG** `runner.py` | `_build_insert_statement`, `_quote_column_name`, `_clean_identifier` (whitelist regex on identifiers), batched binds via `_rows_for_bind_aliases`, and `process_rows_with_upsert`'s bulk SELECT → bulk INSERT/UPDATE. QG is read-only; this is IG's core value. **Keep it synchronous inside a thread** using QG's own `anyio.to_thread` pattern — the driver blocks either way, and rewriting it to async buys nothing while risking the batching logic. |
| **Schema introspection** | **IG** `oracle_metadata.py` | `USER_TAB_COLUMNS` queries for mapping targets. Generalize per `db_type`. |

### 1.6 Ingestion pipeline (IntakeGateway — unique, port with upgrades)

| Module | Verdict |
|---|---|
| `api_connector.py` | **Keep.** Auth methods, fetch, header masking, Retry-After parsing. |
| `normalizer.py` | **Keep.** `jsonpath-ng` record selection + nested flattening. |
| `validator.py` | **Keep,** but the hand-rolled `ValidationError` class and `type_validators` dict duplicate what Pydantic does. **Consider rebuilding on QG's `build_param_model` approach** — one dynamic model per mapping instead of a validator registry. |
| `mapper.py` | **Keep.** Transform registry. |
| `transform_suggester.py` | **Keep.** Type-aware transform suggestions — good UX, no equivalent. |
| `runner.py` | **Keep** the pipeline and batching. Port logging to structlog. |
| `url_guard.py` | **Keep — and this is a gap in QG.** Scheme + resolved-IP validation, metadata-service (169.254.169.254) blocking, `ALLOWED_SOURCE_HOSTS` escape hatch, and an honest docstring about the residual DNS-rebinding window. The merged product needs this the moment it fetches any user-supplied URL. |
| `oauth_token_service.py` | **Keep, with a required fix.** Grant types, expiry skew, encrypted token cache. **But `_get_lock` returns an `asyncio.Lock` keyed by task_id, which serializes refreshes only within one process.** With multiple workers, concurrent refreshes race. Replace with a Postgres advisory lock or a Redis lock **during the port**, not after — the merge is when this becomes exploitable. |
| Rate-limit / cursor logic | **Keep.** Retry-After parsing, backoff caps, and watermarks that advance only on non-backfill non-replay success. Subtle and correct. |

**Port condition:** these modules are the weakest-typed code in either repo — `def trim(x)`, bare `dict` returns, no annotations. They go into a **strict-mypy** codebase. Annotate on the way through; mypy strict will surface real bugs here.

### 1.7 Scheduling and execution (split verdict — this is the interesting one)

| Concern | Adopt | Detail |
|---|---|---|
| **Scheduler placement** | **QG** (in-lifespan APScheduler) | IG's separate `python app/services/scheduler.py` process exists because SQLite can't coordinate. Once there's a shared Postgres, it collapses into the API lifespan. |
| **Schedule semantics** | **QG** — decisively | `schedule_bindings.resolve_schedule_parameters` (fixed / SQL NULL / logical run date / relative date / calendar-window boundaries), IANA timezones, `preview_schedule_runs` showing the next three resolved runs, and a `_binding_hash` for change detection. IG is a raw cron string plus `croniter`. **Drop croniter** — APScheduler's `CronTrigger` covers it. |
| **Failure safety valve** | **IG** | Auto-pause after `SCHEDULE_MAX_CONSECUTIVE_FAILURES`, with the pause persisted *before* the job is removed (a fix visible in IG's history). QG has no equivalent. Real operational value — port it. |
| **Job queue** | **IG** — QG has none | Celery with `autoretry_for`, `retry_backoff`, `retry_backoff_max=600`, `retry_jitter`, and `on_failure`/`on_success`/`on_retry` hooks. **Snapshot refresh should move onto this queue too** — QG currently runs Oracle queries inside the API process, which is fine at low volume and not fine later. |
| **Queue technology** | **Decide empirically in Phase 0** | Celery 5.4 does not support 3.14. Options: upgrade Celery and validate; swap to `arq` (async-native, Redis, small — the natural fit for an async codebase); `dramatiq` for Celery-like semantics; or pin the worker to its own 3.12 image. **Test this on day one** (§3.1). |

### 1.8 Observability (merge — neither is complete)

| Concern | Adopt |
|---|---|
| **Log format** | **QG** — structlog JSON, contextvar binding, mandated `request_id`/`user`/`endpoint`/`status`/`duration_ms`/`method`/`client_ip`/`event` plus `job_id`/`run_id`/`row_count`/`success` on jobs. Port IG's loguru call sites; keep IG's redaction (§1.2). |
| **Run history** | **Merge.** QG's `JobRun` shape (UUID, status enum, structured, survives schedule deletion) + IG's counters (`rows_fetched/inserted/updated/skipped`, `error_count`, `warning_count`, `cursor_start/end`, `is_backfill`, `is_replay`, `replay_of_run_id`). One `Run` table, `kind ∈ {import, snapshot_refresh}`, union of columns. |
| **Row-level errors** | **IG** — `task_run_log` with bounded staging (`ROW_ERROR_FLUSH_SIZE = 1000`). Unique; the bound matters on large imports. |
| **Access audit** | **QG** — `access_logs`, deliberately no FK so rows survive endpoint deletion, written by middleware. Extend to the intake admin plane. |
| **Health** | **QG** — component probes (API/Postgres/Oracle/scheduler), recent job outcomes, stale-snapshot detection. IG returns `{status, env}`. Add queue depth and worker liveness. |

### 1.9 Snapshot caching — QueryGateway only, keep entirely

`compile_snapshot_filters`, `snapshot_covers_request`, `validate_snapshot_parameter_ranges`,
`filter_snapshot_rows`, `validate_snapshot_rows_match_resolved_parameters`. Coverage is checked
against **persisted job-run parameters** before cached rows are filtered — the correct design, and
subtle enough that it should not be touched during the merge.

---

## 2. Frontend — module-by-module

| Module | Adopt | Detail |
|---|---|---|
| **Design system** | **QG** — Tailwind + shadcn/Radix, `components/ui/*` | IG's ~5,800 LOC of antd gets rewritten. No automated path. |
| **Shell / routing / auth** | **QG** — `Layout`, `RequireAuth`, `AuthProvider`, `tokenStorage`, react-router 7 | IG has no login. |
| **API client** | **QG** — module-style `lib/api.ts` (290 LOC) + per-domain `types/*.ts` + `getApiError` | IG has a 302-LOC monolithic `ApiClient` class and a 442-LOC single `types/index.ts`. |
| **CRUD page pattern** | **QG** — `useResourceMutations` (107 LOC, replaces ~40 LOC of boilerplate per page) | Directly replaces IG's hand-rolled 484-LOC `hooks/api.ts`. |
| **Wizard architecture** | **QG's structure, IG's content** | QG: `EndpointWizard` 266 LOC + five step components + **pure logic extracted and unit-tested separately** (`bindParams.ts`, `parameterDefaults.ts`, `cronSchedule.ts`, `scheduleBindings.ts`). IG: **one 692-LOC `TaskWizard.tsx`**. Restructure IG's six steps into QG's step-component shape during the port — this is the single highest-value frontend refactor. |
| **Domain editors** | **IG** — `ColumnMappingEditor` (442 LOC), `UpsertConfigEditor`, transform-suggestion UI | Unique functionality. Rewrite presentation, preserve logic. |
| **SQL editor** | **QG** — CodeMirror 6 via `@uiw/react-codemirror` | — |
| **Build tool** | **IG — Vite 8** | IG is two majors ahead of QG's Vite 6. Take the newer one. |
| **Lint / format** | **QG** — ESLint 9 flat config, `typescript-eslint`, Prettier + `prettier-plugin-tailwindcss` | IG has ESLint 8 legacy config and **no formatter**. |
| **Coverage floor** | **IG** — `fail_under = 50` in `pyproject.toml` | QG reports coverage but sets no floor. Take IG's gate, then raise it. |
| **Client state** | **Neither** — drop `zustand` | react-query + context covers everything both apps do. |
| **Date libraries** | **Drop both** where possible | IG ships `date-fns` *and* `dayjs`; removing antd removes the dayjs requirement. |

**Net frontend direction:** QueryGateway's architecture and tooling, IntakeGateway's domain
features and build tool.

---

## 3. Revised timeline for AI-assisted development

The companion document's 16–31 developer-weeks assumed hand-written code. That is the wrong unit
here. Under AI-assisted development, code production stops being the constraint and three other
things become it:

1. **Review throughput.** Every diff still has to be read. This merge touches roughly 18–20k of the
   ~30k combined LOC. At a sustainable 1,500–2,500 reviewed LOC/day that is **8–13 days on its own**,
   and it does not compress.
2. **Validation wall-clock.** CI runs, integration tests against real Oracle and Postgres, a data
   migration verified row-for-row, soak time on a new queue. Bounded by machines and by how long
   you are willing to watch, not by typing speed.
3. **Irreducible empirical unknowns.** Does the queue run on 3.14? Does the merged Alembic baseline
   apply cleanly to a populated database? Did the antd→shadcn port preserve every interaction? AI
   drafts the answer in minutes; only running it settles it.

### 3.1 Compression by work category

| Category | Examples in this merge | Speedup |
|---|---|---|
| **Mechanical / pattern-following** | loguru→structlog call sites, route renames, config unification, sync→async signature churn, antd→shadcn page ports, repository scaffolding, type annotations on IG's pipeline, test generation | **8–15×** |
| **Design-carrying** | merged `Connection` entity, unified `Run` model, Alembic baseline strategy, queue selection, distributed OAuth lock | **2–3×** |
| **Empirical / wall-clock** | queue-on-3.14 validation, data-migration verification, visual QA, security review of merged auth, load testing | **~1×** |

### 3.2 Revised estimate

| Phase | Hand-written | **AI-assisted** | What actually gates it |
|---|---|---|---|
| **0. Monorepo + CI + queue spike** | 1–2 wks | **0.5–1 day** | Config only, no behavior change |
| **1. Identity + shell + config** | 3–5 wks | **2–3 days** | Review, plus a security pass on merged auth |
| **2. Data tier** | 4–8 wks | **3–5 days** | **Migration verification, not the code** |
| **3. Execution** | 4–8 wks | **3–6 days** | The queue answer from Phase 0 |
| **4. UI convergence** | 4–8 wks | **3–5 days** | Per-page visual QA — not skippable |
| **Total** | **16–31 wks** | **12–20 working days**, over **3–6 calendar weeks** | |

**Phases 0–1 — one product, one login, one console — is 3–4 days.**

### 3.3 What changes about the *approach*, not just the estimate

**Resolve the queue question on day one, not in Phase 3.** It costs about an hour to settle
empirically: build a 3.14 image, install the candidate, run a trivial task. It determines whether
Phase 3 is a port or a rewrite — the largest single variance in the estimate. Under a multi-month
hand-written plan you could defer it; under a 12–20-day plan it goes first.

**Write characterization tests before each port — this is what got cheap.** IG's pipeline has
7.4k LOC of tests but no type annotations, and it is about to be moved to async + structlog +
strict mypy. Generating a behavioral test suite against the *current* implementation before
touching it is now half a day's work, and it converts the riskiest phase into a mechanical one.
Previously this was the first thing cut for time. Don't cut it.

**The phasing matters more with AI assistance, not less.** AI makes a big-bang merge feel
affordable. It isn't, for exactly the reason above: the gate is review, and a 20k-line
unreviewable diff closes it. Keep every phase independently shippable and independently revertible.

**Plan for the Alembic merge as a design task, not a code task.** Two revision trees against one
`alembic_version` table is a data-loss shape. Decide deliberately between branch labels and a
squashed baseline, and verify the chosen path against a *populated* copy of the database. AI writes
the migration in minutes; the verification is the work.

**Budget review capacity explicitly.** At 12–20 days of production, review is the binding
constraint on all but one phase. If review time is limited, the correct response is to lengthen the
calendar, not to shrink the phases.

---

## 4. What to do first

1. **Queue spike** (1 hr) — settle 3.14 compatibility empirically.
2. **Phase 0** (0.5–1 day) — monorepo, QG's CI matrix over both apps, mypy on IG in non-blocking
   mode, Prettier added, no behavior change.
3. **Characterization tests** for IG's pipeline (0.5 day) — before anything is ported.
4. **Phase 1** (2–3 days) — one `Settings`, one JWT auth, one SPA shell, routes under
   `/api/v1/admin/*`.

That is roughly one week to a single product with one login, one console, and both feature sets
reachable — with the two highest-variance unknowns already retired.
