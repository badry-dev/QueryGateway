# Implementation Progress

**Last updated:** 2026-08-31

## Phase 0: Repository Scaffolding, CI/CD, Docker, Conventions — COMPLETE

**Completed:** 2026-03-04

### Delivered
- Monorepo directory skeleton: `backend/`, `frontend/`, `docker/`, `docs/`
- Backend: FastAPI skeleton, Pydantic Settings v2, `requirements.txt`, `pyproject.toml` (ruff/mypy/pytest)
- Frontend: Vite 6 + React 18 + TypeScript, Tailwind CSS, shadcn/ui CSS vars, ESLint, Prettier, Vitest; `vite.config.ts` (ESM-safe, `import.meta.url`), `vitest.config.ts` (separate to avoid vitest/vite type conflict)
- Docker: `Dockerfile.backend` (python:3.14-slim + curl), `Dockerfile.frontend` (multi-stage + nginx), `docker-compose.yml` (`api`/`web`/`db` + optional `oracle` profile)
- GitHub Actions: `backend.yml` (ruff/mypy/pytest + Postgres service), `frontend.yml` (eslint/prettier/vitest/build), `docker.yml` (image builds + compose config validate)
- Docs: `docs/architecture.md`, `docs/contributing.md`, `docs/conventions.md`, root `Makefile`, `.env.example`, `.gitignore`

### Bug Fixes Applied
- `vite.config.ts`: replaced `__dirname` (undefined in ESM) with `fileURLToPath(new URL(..., import.meta.url))`
- `tsconfig.app.json` / `tsconfig.node.json`: added `"composite": true` for `tsc -b` project reference builds
- `tsconfig.node.json`: added `"types": ["node"]` for Node.js built-in module resolution in config files
- `tsconfig.app.json`: added `"types": ["vitest/globals"]` for test globals without explicit imports
- `vitest.config.ts`: extracted test config from `vite.config.ts` (using `mergeConfig`) to avoid vitest-bundled-vite plugin type conflict
- `Dockerfile.backend`: added `curl` to apt install (required by `docker-compose.yml` healthcheck)
- `requirements.txt`: removed duplicate `httpx` entry and unused `types-passlib`
- `frontend/package-lock.json`: committed so `npm ci` succeeds in CI

---

## Phase 1: Backend Foundation — COMPLETE

**Completed:** 2026-03-04

### Goals
Deliver the core FastAPI service skeleton with configuration, persistence, observability, and migration baseline.

### Deliverables
- [x] App factory with startup lifecycle, middleware pipeline, exception handlers
- [x] Structured logging (structlog) with request correlation IDs
- [x] SQLAlchemy 2.0 async models: 8 domain tables
- [x] Alembic async migration environment + initial schema migration
- [x] PostgreSQL async database layer (asyncpg)
- [x] Health endpoints: `/api/v1/admin/health/live` and `/api/v1/admin/health/ready`
- [x] Repository/service layer boundary patterns
- [x] Full test suite update with pytest-asyncio + httpx.AsyncClient

### Domain Tables Modelled
| Table | Model | Purpose |
|-------|-------|---------|
| `connections` | `OracleConnection` | Oracle data source configs |
| `auth_methods` | `AuthMethod` | Bearer / Basic / API-key auth configs |
| `endpoints` | `ApiEndpoint` | Dynamic REST endpoint definitions |
| `schedules` | `Schedule` | Cron/interval snapshot refresh schedules |
| `job_runs` | `JobRun` | Scheduler execution audit records |
| `snapshots` | `Snapshot` | Cached JSONB query results |
| `access_logs` | `AccessLog` | Per-request access audit trail |
| `app_settings` | `AppSetting` | Key-value application settings |

---

---

## Phase 2: Module 1 - Connections End-to-End — COMPLETE

**Completed:** 2026-03-04

### Goals
Provide complete connection lifecycle management for Oracle data sources.

### Delivered

#### Backend
| File | Purpose |
|------|---------|
| `backend/app/crypto.py` | Fernet symmetric encryption for credentials at rest |
| `backend/app/config.py` | Added `encryption_key` setting (Fernet key) |
| `backend/app/schemas/connection.py` | `ConnectionCreate` / `ConnectionUpdate` / `ConnectionResponse` / `ConnectionTestResult` |
| `backend/app/repositories/connection.py` | Async SQLAlchemy repository (get, list, create, update, delete) |
| `backend/app/services/connection.py` | Business logic: encrypt/decrypt, uniqueness guard, Oracle connectivity test, audit logging |
| `backend/app/routers/connections.py` | REST CRUD + `/test` under `/api/v1/admin/connections/*` |
| `backend/tests/test_connections.py` | Crypto unit tests + schema validation tests + API integration tests |

#### API Surface
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/connections/` | List connections (`?active_only=true`) |
| POST | `/api/v1/admin/connections/` | Create connection (201) |
| GET | `/api/v1/admin/connections/{id}` | Get single connection |
| PUT | `/api/v1/admin/connections/{id}` | Update connection |
| DELETE | `/api/v1/admin/connections/{id}` | Delete connection (204) |
| POST | `/api/v1/admin/connections/{id}/test` | Test Oracle connectivity |

#### Security
- Passwords encrypted with Fernet (AES-128-CBC + HMAC-SHA256) before persistence
- `encrypted_password` never returned in any API response
- `has_password: bool` field indicates credentials are stored
- Audit log entries on create / update / delete / test actions

#### Frontend
| File | Purpose |
|------|---------|
| `frontend/src/types/connection.ts` | TypeScript interfaces matching API contract |
| `frontend/src/lib/api.ts` | Axios-based API client (`connectionsApi`) |
| `frontend/src/lib/queryClient.ts` | React Query `QueryClient` + key factories |
| `frontend/src/lib/utils.ts` | `cn()` Tailwind merge utility |
| `frontend/src/components/ui/` | Button, Input, Label, Badge, Select, Textarea, Dialog, Alert |
| `frontend/src/components/Layout.tsx` | Sidebar + `<Outlet>` shell with nav links |
| `frontend/src/components/connections/ConnectionForm.tsx` | Create/edit form with client-side validation |
| `frontend/src/pages/ConnectionsPage.tsx` | List table + create/edit/delete/test dialogs |
| `frontend/src/pages/DashboardPage.tsx` | Overview dashboard with connection count card |
| `frontend/src/App.tsx` | React Router + QueryClientProvider wiring |

#### Checks
- `ruff check .` — clean
- `mypy .` — clean (alembic/ excluded from strict)
- `pytest -k "not integration"` — 22 passed
- `eslint` — clean
- `prettier --check` — clean
- `tsc -b && vite build` — clean

---

## Phase 3: Module 3 - Auth Configuration End-to-End — COMPLETE

**Completed:** 2026-03-05

### Goals
Deliver configurable endpoint authentication using PyJWT + bcrypt.

### Delivered

#### Backend
| File | Purpose |
|------|---------|
| `backend/app/auth/jwt_utils.py` | JWT creation/verification (PyJWT, HS256/384/512) |
| `backend/app/auth/hashing.py` | bcrypt password hashing, API key generation, signing secret generation |
| `backend/app/models/auth_method.py` | `AuthMethod` model with `AuthMethodType` enum (bearer/basic/api_key) |
| `backend/app/models/access_log.py` | `AccessLog` model for per-request access audit trail |
| `backend/app/schemas/auth_method.py` | `AuthMethodCreate` / `AuthMethodUpdate` / `AuthMethodResponse` / `TokenIssuedResponse` / `ApiKeyIssuedResponse` / `RotateResponse` |
| `backend/app/repositories/auth_method.py` | Async SQLAlchemy repository (get, list, create, update, delete) |
| `backend/app/services/auth_method.py` | Business logic: CRUD, token issuance, credential rotation, verification (bearer/basic/api_key) |
| `backend/app/routers/auth_methods.py` | REST CRUD + `/issue-token` + `/rotate` under `/api/v1/admin/auth/*` |
| `backend/app/routers/data.py` | Auth enforcement infrastructure: `_enforce_auth()` and `_write_access_log()` for Phase 4 integration |
| `backend/tests/test_auth_methods.py` | bcrypt/JWT unit tests + schema validation + API integration tests |

#### API Surface
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/auth/` | List auth methods (`?active_only=true`) |
| POST | `/api/v1/admin/auth/` | Create auth method (201) |
| POST | `/api/v1/admin/auth/with-key` | Create API key method, returns key (201) |
| GET | `/api/v1/admin/auth/{id}` | Get single auth method |
| PUT | `/api/v1/admin/auth/{id}` | Update auth method |
| DELETE | `/api/v1/admin/auth/{id}` | Delete auth method (204) |
| POST | `/api/v1/admin/auth/{id}/issue-token` | Issue JWT for bearer method |
| POST | `/api/v1/admin/auth/{id}/rotate` | Rotate signing secret or API key |

#### Security
- Passwords hashed with bcrypt (never returned in API responses)
- Bearer signing secrets encrypted with Fernet before storage in `config_json`
- API keys shown once only on creation/rotation
- JWT tokens stateless — not stored server-side, verified via signing secret
- Token expiry enforced via `exp` claim
- All three auth types supported: Bearer JWT, Basic Auth, API Key

#### Frontend
| File | Purpose |
|------|---------|
| `frontend/src/types/auth_method.ts` | TypeScript interfaces matching API contract |
| `frontend/src/lib/api.ts` | Axios-based `authMethodsApi` client |
| `frontend/src/components/auth/AuthMethodForm.tsx` | Create/edit form with type-specific fields |
| `frontend/src/pages/AuthMethodsPage.tsx` | List table + create/edit/delete/issue/rotate dialogs |

#### Checks
- `ruff check .` — clean
- `mypy .` — clean
- `pytest -k "not integration"` — all passed
- `eslint` — clean
- `prettier --check` — clean
- `tsc -b && vite build` — clean

---

## Phase 4: Module 2 - API Creation Wizard End-to-End — COMPLETE

**Completed:** 2026-03-05

### Goals
Deliver the core wizard that converts parameterized SQL into deployable versioned data endpoints.

### Delivered

#### Backend
| File | Purpose |
|------|---------|
| `backend/app/schemas/endpoint.py` | `EndpointCreate` / `EndpointUpdate` / `EndpointResponse` / `SqlPreviewRequest` / `SqlPreviewResponse` / `ParamDescriptor` + SQL safety validation + bind parameter extraction |
| `backend/app/repositories/endpoint.py` | Async SQLAlchemy repository (get_all, get_by_id, get_by_name, get_by_path, create, update, delete) |
| `backend/app/services/endpoint.py` | Business logic: CRUD, uniqueness (name + path), connection validation, SQL preview orchestration, column map handling |
| `backend/app/routers/endpoints.py` | REST CRUD + `/preview` under `/api/v1/admin/endpoints/*` |
| `backend/app/sql/__init__.py` | SQL execution module |
| `backend/app/sql/executor.py` | Oracle SQL execution engine via python-oracledb with query timeout, thread delegation, structured logging |
| `backend/app/routers/data.py` | **Upgraded from Phase 3 stub**: Dynamic endpoint resolution, auth enforcement, parameter coercion, column mapping, access logging |
| `backend/tests/test_endpoints.py` | SQL safety unit tests + schema validation + bind parameter extraction + API integration tests |

#### Admin API Surface
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/endpoints/` | List endpoints (`?active_only=true`) |
| POST | `/api/v1/admin/endpoints/` | Create endpoint (201) |
| GET | `/api/v1/admin/endpoints/{id}` | Get single endpoint |
| PUT | `/api/v1/admin/endpoints/{id}` | Update endpoint |
| DELETE | `/api/v1/admin/endpoints/{id}` | Delete endpoint (204) |
| POST | `/api/v1/admin/endpoints/preview` | Preview SQL execution (sample results) |

#### Dynamic Data API
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/data/{path}` | Execute endpoint query, enforce auth, return JSON data with metadata |

#### SQL Safety
- Named bind variables (`:param_name`) extracted and validated
- Unsafe interpolation patterns rejected (string concat, f-strings, template literals, PL/SQL concat)
- Parameters validated and coerced through typed `ParamDescriptor` schemas
- All SQL executed via python-oracledb with configurable query timeout

#### Data Endpoint Features
- Dynamic path-based endpoint resolution (no service restart needed)
- Per-endpoint auth enforcement (bearer/basic/api_key via Phase 3 infrastructure)
- Parameter extraction from query string with type coercion (string/integer/float/boolean)
- Required parameter validation with defaults support
- Column rename mapping (`column_map_json`)
- Deprecation headers (`Deprecation: true`, `Sunset`) for deprecated endpoints
- Access logging for all requests (success, auth failure, parameter errors, query errors)
- Response metadata: row_count, query_duration_ms, endpoint path, version, data_strategy

#### Frontend
| File | Purpose |
|------|---------|
| `frontend/src/types/endpoint.ts` | TypeScript interfaces matching API contract |
| `frontend/src/lib/api.ts` | Axios-based `endpointsApi` client (CRUD + preview) |
| `frontend/src/components/endpoints/SqlEditor.tsx` | CodeMirror 6 SQL editor with syntax highlighting and dark theme |
| `frontend/src/components/endpoints/EndpointWizard.tsx` | Multi-step wizard: Connection → SQL → Parameters → Auth & Config → Review & Publish |
| `frontend/src/pages/EndpointsPage.tsx` | List table + wizard + edit/delete dialogs + URL copy/open actions |
| `frontend/src/pages/DashboardPage.tsx` | Updated with endpoints count card |
| `frontend/src/components/Layout.tsx` | Updated with API Endpoints nav item |

#### Checks
- `ruff check .` — clean
- `mypy .` — clean (50 files, 0 errors)
- `pytest -k "not integration"` — 57 passed
- `eslint` — clean
- `prettier --check` — clean
- `tsc -b && vite build` — clean

---

## Phase 5: Module 4 - Scheduling + Snapshot Cache End-to-End — COMPLETE

**Initial completion:** 2026-03-06

**Scheduler/parameter hardening updated:** 2026-08-31

### Goals
Enable scheduled data refresh with persisted definitions, restart restoration, and filtered cached
response serving.

### Delivered

#### Backend
| File | Purpose |
|------|---------|
| `backend/app/schemas/schedule.py` | `ScheduleCreate` / `ScheduleUpdate` / `ScheduleResponse` / `JobRunResponse` / `SnapshotResponse` / `SnapshotDetailResponse` |
| `backend/app/repositories/schedule.py` | Async SQLAlchemy repository (get_all, get_by_id, get_by_endpoint_id, create, update, delete) |
| `backend/app/repositories/job_run.py` | Async SQLAlchemy repository (get_all with filters, get_by_id, create, update) |
| `backend/app/repositories/snapshot.py` | Async SQLAlchemy repository (get_latest_by_endpoint, get_by_endpoint, create, delete_old with retention) |
| `backend/app/services/scheduler.py` | APScheduler 3.x AsyncIOScheduler integration: lifecycle (start/stop), job execution (Oracle query + snapshot persistence), job management (add/remove/pause/resume) |
| `backend/app/services/schedule.py` | Business logic: CRUD, one-schedule-per-endpoint uniqueness, run-now, pause/resume, job run queries, snapshot queries |
| `backend/app/routers/schedules.py` | REST CRUD + `/run` + `/pause` + `/resume` + job runs + snapshots under `/api/v1/admin/schedules/*` |
| `backend/app/services/data.py` | Snapshot orchestration: required-parameter validation, retained-run coverage selection, typed cached-row filtering, and stable error responses |
| `backend/app/services/snapshot_filtering.py` | Compiled `eq`/`gte`/`lte` filters, coverage checks, range validation, cached date normalization, and row filtering |
| `backend/app/main.py` | **Updated**: APScheduler lifecycle (start on startup, stop on shutdown), schedule router registration |
| `backend/tests/test_schedules.py` | Schema validation unit tests + API integration tests |

#### Admin API Surface
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/schedules/` | List schedules (`?active_only=true`) |
| POST | `/api/v1/admin/schedules/` | Create schedule (201) |
| GET | `/api/v1/admin/schedules/{id}` | Get single schedule |
| PUT | `/api/v1/admin/schedules/{id}` | Update schedule |
| DELETE | `/api/v1/admin/schedules/{id}` | Delete schedule (204) |
| POST | `/api/v1/admin/schedules/{id}/run` | Run schedule now (202) |
| POST | `/api/v1/admin/schedules/{id}/pause` | Pause schedule |
| POST | `/api/v1/admin/schedules/{id}/resume` | Resume schedule |
| GET | `/api/v1/admin/schedules/jobs/` | List job runs (`?schedule_id=&endpoint_id=&limit=`) |
| GET | `/api/v1/admin/schedules/jobs/{id}` | Get single job run |
| GET | `/api/v1/admin/schedules/snapshots/{endpoint_id}` | List snapshots for endpoint |
| GET | `/api/v1/admin/schedules/snapshots/detail/{id}` | Get snapshot with data |

#### Scheduling Features
- APScheduler 3.x with AsyncIOScheduler integration
- Cron (5-field) and interval (seconds) schedule types
- Friendly hourly/daily/weekly/monthly cron controls plus advanced custom cron
- IANA timezone, logical run date, and inclusive reusable calendar windows
- Explicit schedule-owned sources for every SQL bind: literal, SQL `NULL`, run date, relative
  date, window start, or window end
- Preview of upcoming nominal runs, logical dates, windows, and resolved typed parameters
- Job coalescing (max 1 instance per job, 60s misfire grace time)
- Scheduler lifecycle tied to FastAPI startup/shutdown; active database definitions are restored on
  startup in the documented single-process topology
- One schedule per endpoint uniqueness constraint

#### Snapshot Cache Features
- JSONB snapshot storage in PostgreSQL
- Automatic snapshot retention (keeps latest 5 per endpoint)
- Parameterized snapshot endpoints require a final cached-column mapping and allowlisted operator
  for every request parameter
- Data requests enforce required parameters, choose the newest retained snapshot whose job-run
  inputs cover the complete request, and return only typed filtered rows
- Covered requests with no matching rows return `data: []`; invalid ranges or requests outside
  retained coverage return HTTP 422
- Snapshot responses include filtered `row_count`, original `snapshot_row_count`, and
  `snapshot_created_at` metadata
- Fallback: 503 if no snapshot available yet
- Column mapping applied during job execution

#### Job Execution
- Immutable job run audit records including scheduled/logical time, window boundaries, resolved
  parameters, trigger source, binding hash, row count, status, and error detail
- Status tracking: running → success/failed/timeout
- Schedule-owned bindings are resolved for scheduled queries; endpoint request defaults are never
  read by the scheduler
- `(schedule_id, scheduled_for)` uniqueness prevents duplicate logical runs
- Structured logging with job_id, run_id, row_count, duration_ms, success fields

#### Frontend
| File | Purpose |
|------|---------|
| `frontend/src/types/schedule.ts` | TypeScript interfaces matching API contract |
| `frontend/src/lib/api.ts` | Axios-based `schedulesApi` client (CRUD + run/pause/resume + jobs + snapshots) |
| `frontend/src/lib/queryClient.ts` | Schedule query key factories |
| `frontend/src/pages/SchedulesPage.tsx` | List table + create/delete dialogs + run now/pause/resume controls + job runs viewer |
| `frontend/src/components/schedules/ScheduleParameterBindings.tsx` | Schedule-local binding sources, calendar window controls, and resolved-run preview |
| `frontend/src/components/endpoints/SnapshotFilterMappings.tsx` | Required create/edit mappings from request parameters to cached output columns |
| `frontend/src/pages/DashboardPage.tsx` | Updated with schedules count card (4-column grid) |
| `frontend/src/components/Layout.tsx` | Updated with Schedules nav item, version bumped to v0.5.0 |
| `frontend/src/App.tsx` | Updated with /schedules route |

#### Phase completion checks (2026-03-06)
- `ruff check .` — clean
- `mypy .` — clean (58 files, 0 errors)
- `pytest -k "not integration"` — 69 passed
- `eslint` — clean
- `prettier --check` — clean
- `tsc -b && vite build` — clean
- `vitest` — 2 passed

---

## Phase 6: Module 5 - Settings + Health Dashboard End-to-End — COMPLETE

**Completed:** 2026-03-06

### Goals
Provide centralized operational controls and health visibility.

### Delivered

#### Backend
| File | Purpose |
|------|---------|
| `backend/app/schemas/setting.py` | `SettingResponse` / `SettingUpdate` / `SettingBulkUpdate` schemas with value validation |
| `backend/app/repositories/settings.py` | Async SQLAlchemy repository (get_all, get_by_key, upsert, delete) |
| `backend/app/services/settings.py` | Business logic: known settings registry, type validation, restart-required tracking, secret masking, seed-on-first-access |
| `backend/app/services/health.py` | Health aggregation: PostgreSQL probe, scheduler status, recent job outcomes (24h), stale snapshot detection, connection/endpoint counts |
| `backend/app/routers/settings.py` | REST CRUD under `/api/v1/admin/settings/*` |
| `backend/app/routers/health.py` | **Updated**: Added `/dashboard` endpoint for health aggregation |
| `backend/app/main.py` | **Updated**: Registered settings router |
| `backend/tests/test_settings.py` | Schema validation unit tests + known settings tests + API integration tests |

#### Admin API Surface
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/settings/` | List all settings |
| PUT | `/api/v1/admin/settings/` | Bulk update settings |
| GET | `/api/v1/admin/settings/restart-keys` | List settings requiring restart |
| GET | `/api/v1/admin/settings/{key}` | Get single setting |
| PUT | `/api/v1/admin/settings/{key}` | Update single setting |
| GET | `/api/v1/admin/health/dashboard` | Aggregated health dashboard |

#### Known Settings
| Key | Type | Default | Restart Required |
|-----|------|---------|-----------------|
| `log_level` | enum (DEBUG/INFO/WARNING/ERROR) | INFO | Yes |
| `query_timeout_seconds` | integer (1-300) | 30 | No |
| `cors_origins` | string (comma-separated) | `http://localhost:5173` | Yes (wildcard rejected) |
| `snapshot_retention_count` | integer (1-100) | 5 | No |
| `max_job_concurrency` | integer (1-20) | 3 | Yes |

#### Health Dashboard Components
- **Database probe**: PostgreSQL connectivity check with error detail
- **Scheduler status**: Running/stopped, job count, active schedules
- **Recent job outcomes (24h)**: Total, success, failed counts with success rate percentage
- **Stale snapshot detection**: Identifies snapshot-strategy endpoints with missing or outdated snapshots (threshold: 2x schedule interval or 24h default)
- **Connection/endpoint counts**: Total and active counts for connections and endpoints
- **Overall status**: "ok" or "degraded" (auto-set when database probe fails or stale snapshots detected)

#### Frontend
| File | Purpose |
|------|---------|
| `frontend/src/types/setting.ts` | TypeScript interfaces: `Setting`, `SettingUpdate`, `SettingBulkUpdate`, `HealthDashboard` |
| `frontend/src/lib/api.ts` | **Updated**: `settingsApi` (list, get, update, bulkUpdate, restartKeys) and `healthApi` (live, ready, dashboard) |
| `frontend/src/lib/queryClient.ts` | **Updated**: Settings and health query key factories |
| `frontend/src/pages/SettingsPage.tsx` | Form-based settings editor with per-setting save, restart-required badges, secret masking, success/error messages |
| `frontend/src/pages/HealthPage.tsx` | Health dashboard with overall status, component cards, scheduler status, job run stats, stale snapshot table, 30s auto-refresh |
| `frontend/src/pages/DashboardPage.tsx` | **Updated**: Added Settings and Health summary cards (6-card grid layout) |
| `frontend/src/components/Layout.tsx` | **Updated**: Added Settings (Cog icon) and Health (Activity icon) nav items, version bumped to v0.6.0 |
| `frontend/src/App.tsx` | **Updated**: Added `/settings` and `/health` routes |

#### Checks
- `ruff check .` — clean
- `mypy .` — clean
- `pytest -k "not integration"` — 57 passed
- `eslint` — clean
- `prettier --check` — clean
- `tsc -b && vite build` — clean

---

## Phase 7: Integration Hardening — COMPLETE

**Completed:** 2026-03-07

### Goals
Validate production readiness across module boundaries and security controls.

### Delivered

#### End-to-End Smoke Test Suite
| File | Purpose |
|------|---------|
| `backend/tests/test_e2e_smoke.py` | Cross-module lifecycle tests: connection → auth → endpoint → schedule → snapshot → data consumption |

**Test classes:**
- `TestE2ELifecycleSmoke` — Full lifecycle: create connection, configure auth, publish endpoint, verify auth enforcement on data API, deactivate/reactivate, snapshot mode with 503 fallback, schedule creation
- `TestE2EAuthTypes` — All three auth types (bearer, basic, api_key) enforced on data endpoints; no-auth endpoint accessibility
- `TestE2EHealthDashboard` — Liveness, readiness, and dashboard field validation
- `TestE2ESettings` — Settings CRUD, known settings, restart-required keys
- `TestE2EConnectionLifecycle` — Full CRUD lifecycle for connections

#### Security Validation Test Suite
| File | Purpose |
|------|---------|
| `backend/tests/test_security.py` | Negative-path security tests covering SQL injection, auth bypass, credential leakage, path traversal, malformed inputs |

**Test classes:**
- `TestSqlInjectionPrevention` — 8 unsafe SQL patterns rejected, 5 safe patterns accepted, schema-level blocking
- `TestAuthSecurity` — Missing auth headers, malformed bearer tokens, expired JWTs, malformed basic credentials, empty API keys, token rotation invalidation
- `TestCredentialLeakage` — Oracle passwords, signing secrets, password hashes, and config_json never appear in API responses
- `TestMalformedRequests` — Invalid UUIDs, missing required fields, empty bodies, invalid enum values, nonexistent foreign keys
- `TestPathValidation` — Path traversal (`../`), XSS, special characters, SQL injection in paths blocked; valid paths accepted
- `TestDataEndpointParams` — Missing required parameters (422), invalid parameter types (422), nonexistent data paths (404)

#### Migration Upgrade Path Validation
| File | Purpose |
|------|---------|
| `backend/tests/test_migration.py` | Migration file structure, chain integrity, model-migration alignment, Alembic config validation |

**Test classes:**
- `TestMigrationFileStructure` — Migration directory exists, initial migration structure, upgrade/downgrade functions, enum types, table coverage, no duplicate revisions
- `TestModelMigrationAlignment` — All 8 SQLAlchemy model tables present in migration scripts
- `TestAlembicConfig` — alembic.ini and env.py exist and reference Base metadata
- `TestSchemaCreation` — Tables created from models; CRUD operations work on fresh schema

#### Performance Sanity Tests
| File | Purpose |
|------|---------|
| `backend/tests/test_performance.py` | Response time sanity checks for admin and data APIs |

**Test classes:**
- `TestAdminApiLatency` — Connection list/create, endpoint create, health dashboard, settings list all respond within 2-3 seconds
- `TestDataApiLatency` — Data 404, auth rejection, snapshot 503 all respond within 1 second
- `TestBulkOperationPerformance` — Creating 20 connections in under 10 seconds; listing with many rows under 2 seconds

#### Security Checklist
| File | Purpose |
|------|---------|
| `docs/security_checklist.md` | 50-item security validation checklist covering auth, credential storage, SQL injection, input validation, data exposure, transport, scheduler, deployment |

**Summary:** 44/50 verified through code and automated tests; 6 deployment-environment-specific items marked as action required.

#### Deployment & Operations Documentation
| File | Purpose |
|------|---------|
| `docs/deployment.md` | Step-by-step deployment runbook: Docker Compose, bare metal, Kubernetes; environment variables, migrations, health probes, post-deployment verification |
| `docs/operations.md` | Backup/restore procedures, monitoring guide, incident troubleshooting (service start failures, DB issues, Oracle errors, scheduler problems, auth issues), upgrade/rollback procedures, performance tuning |

#### Code Hardening
- Fixed pre-existing `ruff` lint error in `app/sql/executor.py` (UP038: `isinstance` tuple to union type)
- Fixed pre-existing `mypy` error in `app/services/scheduler.py` (`snapshot_retention_count` attribute — now reads from runtime DB settings instead of static config)

### Test Summary

| Area | Unit Tests | Integration Tests | Status |
|------|-----------|-------------------|--------|
| Connections (Phase 2) | Crypto, validation | API CRUD | ✅ Passing |
| Auth Methods (Phase 3) | bcrypt, JWT, schemas | API CRUD, token issuance | ✅ Passing |
| Endpoints (Phase 4) | SQL safety, bind params | API CRUD, preview | ✅ Passing |
| Schedules (Phase 5) | Schema validation | API CRUD, run/pause/resume | ✅ Passing |
| Settings (Phase 6) | Schema validation, known settings | API CRUD, health dashboard | ✅ Passing |
| **E2E Smoke (Phase 7)** | — | **Full lifecycle, auth types, health, settings** | ✅ Passing |
| **Security (Phase 7)** | **SQL injection, path validation** | **Auth bypass, credential leak, malformed input** | ✅ Passing |
| **Migration (Phase 7)** | **File structure, model alignment** | **Schema creation, CRUD on fresh DB** | ✅ Passing |
| **Performance (Phase 7)** | — | **Latency budgets, bulk ops** | ✅ Passing |
| Frontend | Component rendering | — | ✅ Passing (vitest) |

**Total: 113 non-integration tests passing** (unit + Phase 7 new tests)

#### Checks
- `ruff check .` — clean (0 errors)
- `mypy .` — clean (0 errors, 68 files checked)
- `pytest -k "not integration"` — 113 passed
- `eslint` — clean
- `prettier --check` — clean
- `vitest` — 2 passed
- `tsc -b && vite build` — clean

#### Local Testing
1. **Prerequisites**: Docker Desktop, Git, `.env` file with `ENCRYPTION_KEY`
2. **Quick start**: `docker compose up -d` boots PostgreSQL + backend + frontend
3. **Backend only**: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload`
4. **Frontend only**: `cd frontend && npm install && npm run dev`
5. **Run checks**:
   - Backend: `cd backend && ruff check . && mypy . && pytest`
   - Frontend: `cd frontend && npm run eslint && npm run prettier:check && npm run test`
6. **Oracle testing**: Requires reachable Oracle instance; integration tests are skipped without one

#### QA Readiness
- **Modules 1-5**: Feature-complete with admin UI and API
- **Phase 7**: Integration hardening complete — E2E smoke tests, security validation, performance sanity, deployment documentation
- **Blocking for QA**: Oracle connectivity for live query testing
- **Production readiness**: Deployment runbook, operations guide, and security checklist finalized
