# QueryGateway Phased Refactor Plan

> **Historical implementation plan.** The refactor described here has been superseded by the
> current repository structure. Use [Architecture](architecture.md),
> [Implementation progress](progress.md), and [Endpoint, scheduler, and snapshot parameter
> contracts](scheduler_parameter_bindings.md) as the current source of truth. Line numbers and
> pre-refactor helper names below are retained only as execution history.

## Context

A code-health audit of the QueryGateway monorepo (FastAPI + React, Oracle query gateway) scored **66/100**. Findings include one critical security gap — `/api/v1/admin/*` is fully unauthenticated, with no User model, login endpoint, dependency, or middleware — plus architecture leakage (`routers/data.py` bypasses the service layer), per-request Oracle client init, hand-rolled param coercion, ~6 near-identical repositories and routers, monolithic frontend pages (350-450 LOC), no frontend login UI, and 1 frontend test for 4,173 LOC. Existing utilities (JWT helpers, bcrypt helpers, ServiceContext patterns, FastAPI lifespan) are reusable and should be the foundation.

A Phase-1 exploration also corrected the audit on one point: `tests/test_security.py`, `test_e2e_smoke.py`, `test_performance.py`, `test_health.py`, `test_migration.py` all contain real class-based tests — they are not stubs.

User intent (confirmed via AskUserQuestion):
- Single env-seeded admin (no users table).
- Sequenced PRs by phase (each independently mergeable).
- Address all audit findings.

Outcome target: ship admin auth first (closes the only critical security exposure), then refactor architecture and duplication, then frontend abstractions, then CI hardening — taking the score from 66 → ~88.

---

## Phase 1 — Critical Security Hygiene

**Goal**: Remove the two zero-cost security findings before any auth work.

**Files modified**
- `backend/app/config.py` — drop the default for `jwt_secret_key` (line 29). Mirror `encryption_key` (no default → fail-fast at import).
- `backend/app/crypto.py:48` — narrow `except (InvalidToken, Exception)` to `except InvalidToken`.
- `.env.example` — document `JWT_SECRET_KEY` requirement.
- `.github/workflows/backend.yml` — `JWT_SECRET_KEY` is already set for tests; verify.

**Tests added**
- `backend/tests/test_config.py` — settings build fails when `JWT_SECRET_KEY` unset.
- `backend/tests/test_crypto.py` — `InvalidToken` returns wrapped `ValueError`; non-Fernet errors propagate.

**Reuse**: existing `Settings` (Pydantic v2) pattern.

**Dependencies**: none. **Risk**: deploy crash if ops misses env; mitigate via `.env.example` + release note.

**PR title**: `security: require JWT_SECRET_KEY env, narrow crypto exception clause`

---

## Phase 2 — Backend Admin Authentication

**Goal**: Protect every `/api/v1/admin/*` route with JWT bearer auth backed by an env-seeded admin.

**Files created**
- `backend/app/auth/admin.py` — `AdminPrincipal` dataclass; `authenticate_admin(username, password)`; `get_current_admin` FastAPI dependency that verifies bearer tokens via `verify_access_token`.
- `backend/app/routers/auth.py` — `POST /api/v1/auth/login` (returns JWT + expiry); `GET /api/v1/auth/me`.
- `backend/app/schemas/auth.py` — `LoginRequest`, `TokenResponse`, `MeResponse`.

**Files modified**
- `backend/app/config.py` — add `admin_username: str` and `admin_password_hash: str` (no defaults; bcrypt hash, not plaintext).
- `backend/app/main.py` — register the new `auth` router (line 89-97 router block).
- `backend/app/routers/connections.py`, `auth_methods.py`, `endpoints.py`, `schedules.py`, `settings.py` — add `dependencies=[Depends(get_current_admin)]` to each `APIRouter(...)` constructor. Leave `routers/data.py` alone (it already enforces per-endpoint auth).
- `.github/workflows/backend.yml` — set `ADMIN_USERNAME` and a known-hash `ADMIN_PASSWORD_HASH` for tests.

**Reuse**
- `backend/app/auth/jwt_utils.py` — `create_access_token`, `verify_access_token`, `TokenError`.
- `backend/app/auth/hashing.py` — `verify_password`, `hash_password`.

**Tests added**
- `backend/tests/test_auth_login.py` — success, wrong password, missing creds, malformed body.
- `backend/tests/test_admin_protection.py` — for each admin router: 401 without token, 401 with expired token, 200 with valid token.

**Migration impact**: none (env-only).

**Dependencies**: Phase 1 (clean JWT secret). **Risk**: existing API integrations that hit admin endpoints break — document in release notes. **Rollback**: revert dependencies array.

**PR title**: `feat(auth): seeded admin login + JWT-protected admin routes`

---

## Phase 3 — Frontend Login & Auth Plumbing

**Goal**: Login page, auth context, axios interceptor, 401 redirect. Wraps existing routes in `frontend/src/App.tsx` (current routes at lines 19-27).

**Files created**
- `frontend/src/pages/LoginPage.tsx`
- `frontend/src/lib/auth.tsx` — `AuthProvider`, `useAuth`, `localStorage`-backed token storage. Document the storage choice in a header comment (XSS trade-off vs sessionStorage; cookie path deferred).
- `frontend/src/components/RequireAuth.tsx` — route guard.

**Files modified**
- `frontend/src/lib/api.ts` — request interceptor adds `Authorization: Bearer <token>`; response interceptor on 401 clears token and redirects to `/login`.
- `frontend/src/App.tsx` — wrap `<Routes>` in `<AuthProvider>`; add `/login` route; wrap protected layout in `<RequireAuth>`.
- `frontend/src/components/Layout.tsx` — add logout action that clears token via `useAuth`.

**Reuse**: `frontend/src/lib/queryClient.ts`, existing axios instance in `lib/api.ts`, `components/ui/{button,input,label,alert}.tsx`.

**Tests added**
- `frontend/src/pages/LoginPage.test.tsx` — happy path, error display.
- `frontend/src/lib/auth.test.tsx` — token persistence, logout, 401 redirect.
- `frontend/src/lib/api.test.ts` — interceptor adds header, 401 clears.

**Dependencies**: Phase 2 (login endpoint must exist). **Risk**: token-storage XSS posture — mitigate with short TTL + documented decision. **Rollback**: revert routing wrap.

**PR title**: `feat(frontend): login page, auth context, 401 redirect`

---

## Phase 4 — Backend Architecture: DataService, Access-Log, Oracle Init, Param Pydantic

**Goal**: Address findings 4–7 from the audit. Independent of Phases 2/3 (different files), so can run in parallel by another developer.

**Files created**
- `backend/app/services/data.py` — `DataService` orchestrating endpoint resolution, snapshot/live dispatch, param coercion, executor invocation, and access-log emission. Slims `routers/data.py` from 492 → ~150 LOC.
- `backend/app/services/access_log.py` — `async with log_access(...)` context manager. Times the block, captures status code, writes to a **dedicated `AsyncSessionLocal()` session** (not the request session) so log failures or rollbacks never poison request transactions.
- `backend/app/sql/param_models.py` — `build_param_model(param_schema_json) -> Type[BaseModel]` using `pydantic.create_model` (replaces `_coerce_param` at `routers/data.py:181-199`).

**Files modified**
- `backend/app/main.py` — extend `lifespan` (line 44-56): if `settings.oracle_client_lib_dir`, call `oracledb.init_oracle_client(lib_dir=...)` once at startup.
- `backend/app/sql/executor.py` — delete the per-request `init_oracle_client` call at line 50. Drop `thick`/`lib_dir` parameters from `_execute_sync`.
- `backend/app/routers/data.py` — replace 10 inline `_write_access_log` calls (lines 229, 248, 272, 294, 348, 369, 390, 413, 439, 475) with one `async with log_access(...)`. Delegate body to `DataService`. Delete `_apply_column_map`, `_coerce_param`, `_enforce_auth` if relocated.

**Reuse**: existing repositories, `AuthMethodService`, `app.database.AsyncSessionLocal`, FastAPI lifespan in `main.py:44`.

**Tests added**
- `backend/tests/test_data_service.py` — golden-tests against current `_coerce_param` outputs (run BEFORE deletion to capture expected behavior, then assert parity from Pydantic path).
- `backend/tests/test_access_log_session.py` — verifies access log persists even when the request session rolls back.
- `backend/tests/test_executor_startup.py` — `init_oracle_client` invoked at startup once.

**Migration impact**: none.

**Dependencies**: Phase 1. Independent of Phases 2/3/5. **Risk**: behavioral drift in param coercion edge cases (None defaults, optional booleans, empty strings) — mitigate with golden tests. **Rollback**: PR is self-contained to `data.py` + new service files.

**PR title**: `refactor(backend): extract DataService, lift Oracle init, Pydantic param models`

---

## Phase 5 — Repository & Router Cleanup

**Goal**: Address findings 8 and 9. Reduce ~250 LOC of CRUD/factory boilerplate.

**Files created**
- `backend/app/repositories/base.py` — `BaseCrudRepository[ModelT]` generic with `get_all(active_only)`, `get_by_id(id)`, `get_by_name(name)`, `create(obj)`, `update(obj, changes)`, `delete(obj)`. Subclasses set the model class.

**Files modified**
- `backend/app/repositories/connection.py`, `endpoint.py`, `auth_method.py`, `schedule.py` — inherit `BaseCrudRepository`; keep specialized methods.
- `backend/app/repositories/snapshot.py`, `job_run.py`, `settings.py` — these have specialized shapes (snapshot retention, job filters, settings upsert); inherit from base where possible, keep specialized methods. `settings.py` does NOT use `delete`, so it stays as-is or inherits a narrower `BaseReadRepository`.
- All 5 admin routers — replace inline `XService(XRepository(db))` re-instantiations (audit found 7 inline cases in `auth_methods.py`, 3 in `connections.py`, plus more) with the existing `_service` Depends factory pattern. Standardize the `_service` factory shape across all routers.

**Reuse**: existing `_service` factories where present.

**Tests added**
- `backend/tests/test_base_repo.py` — generic CRUD against a fixture model.
- Existing per-router tests must pass unchanged (this is the behavior-preservation signal).

**Dependencies**: best **after Phase 4 merges** to avoid `data.py` and router merge conflicts. Otherwise independent of Phases 2/3.

**PR title**: `refactor(backend): generic BaseCrudRepository, standardized Depends factories`

---

## Phase 6 — Frontend Form, List, and Wizard Abstractions

**Goal**: Address findings 11, 12, 13. Collapse ~600 LOC of duplication across pages and forms.

**Files created**
- `frontend/src/lib/hooks/useFormState.ts` — generic `<T>` form state with validation + dirty tracking + submit pipeline.
- `frontend/src/lib/hooks/useResourceList.ts` — wraps `useQuery` with active-only filter.
- `frontend/src/lib/hooks/useResourceMutation.ts` — wraps `useMutation` + invalidation pattern shared across pages.
- `frontend/src/components/forms/BaseForm.tsx` — generic form scaffolding (label/input/error, submit/cancel footer).
- `frontend/src/components/endpoints/wizard/ConnectionStep.tsx`, `SqlQueryStep.tsx`, `ParametersStep.tsx`, `AuthConfigStep.tsx`, `ReviewStep.tsx`.

**Files modified**
- `frontend/src/components/connections/ConnectionForm.tsx` — rebuilt on `useFormState` + `BaseForm`.
- `frontend/src/components/auth/AuthMethodForm.tsx` — same.
- `frontend/src/pages/ConnectionsPage.tsx` (365 LOC), `AuthMethodsPage.tsx` (453 LOC), `SchedulesPage.tsx` (435 LOC) — refactored to use `useResourceList` + `useResourceMutation`. Target ~150-200 LOC each.
- `frontend/src/components/endpoints/EndpointWizard.tsx` (453 LOC) — orchestrator only; ~100 LOC. Steps live in `wizard/`.

**Reuse**: `lib/api.ts`, `lib/queryClient.ts`, all primitives in `components/ui/` (`button`, `dialog`, `input`, `label`, `select`, `textarea`, `alert`, `badge`).

**Tests added**
- `frontend/src/lib/hooks/useFormState.test.tsx`
- `frontend/src/lib/hooks/useResourceList.test.tsx`
- `frontend/src/components/endpoints/wizard/*.test.tsx` — one per step.
- Page-level smoke tests for each refactored page.

**Dependencies**: Phase 3 (auth must wrap pages first — avoids double-refactor). **Risk**: form/page regressions — mitigate by committing tests **before** the refactor in the same PR. **Rollback**: per-file revert is possible.

**PR title**: `refactor(frontend): shared form/list hooks, decompose EndpointWizard`

---

## Phase 7 — Coverage, CI Hardening, Migration Discipline

**Goal**: Address findings 14, 16, plus the audit's note on a single Alembic migration with no rollback exercise.

**Files modified**
- `backend/pyproject.toml` — add `--cov-fail-under=N` where N = (current measured % − 2). Plan to ratchet by +5 each quarter.
- `.github/workflows/backend.yml` — upload `coverage.xml` as an artifact; optional Codecov action.
- `.github/workflows/frontend.yml` — `npm run test -- --coverage`; upload artifact.
- `frontend/vitest.config.ts` — enable coverage with `v8` provider; threshold per `lib/`, `components/`, `pages/` directories.
- `Makefile` — add `make migrate-down-up` target running `alembic downgrade -1 && alembic upgrade head` against a throwaway DB.

**Files created**
- `frontend/src/lib/api.test.ts` — interceptor + each `*Api` wrapper (mocked axios).
- Per-page smoke tests if not already added in Phase 6.
- `.github/workflows/migration-roundtrip.yml` (optional) — runs `make migrate-down-up` on PRs that touch `backend/alembic/`.

**Dependencies**: Phase 6 (test the refactored components). **Risk**: red CI on threshold; mitigate by measuring first. **Rollback**: trivial.

**PR title**: `ci: coverage thresholds + xml upload + alembic roundtrip check`

---

## Phase 8 — Optional: Tighten Public Data Endpoint Auth Policy

**Goal**: Currently `routers/data.py:262` only enforces auth when `ep.auth_method_id is not None`. Schema allows `auth_method_id IS NULL`, so admins can create open endpoints. The audit didn't explicitly flag this, but it's adjacent to the security work.

**Files modified**
- New Alembic migration making `endpoints.auth_method_id` `NOT NULL`.
- `backend/app/schemas/endpoint.py` — make `auth_method_id` required.
- `backend/app/routers/data.py` — drop the `if ep.auth_method_id is not None` branch.

**Dependencies**: Phases 2 + 5. **Open user decision**: ship this or leave it as documented configuration. Default recommendation: ship — defense-in-depth.

**PR title**: `security(data): require auth_method on every endpoint`

---

## Parallelization Map

| After merging | Can start in parallel |
|---|---|
| Phase 1 | Phase 2 (Dev A), Phase 4 (Dev B) |
| Phase 2 | Phase 3 (Dev A), Phase 5 (Dev B, after Phase 4 merges) |
| Phases 3 + 5 | Phase 6 |
| Phase 6 | Phase 7 |
| Phase 7 | Phase 8 (optional) |

---

## Verification

End-to-end checks per phase, run from repo root unless noted.

**Phase 1**
```
cd backend && ruff check . && mypy . && JWT_SECRET_KEY=test pytest tests/test_config.py tests/test_crypto.py -v
unset JWT_SECRET_KEY && python -c "from app.config import settings"   # must raise ValidationError
```

**Phase 2**
```
cd backend && pytest tests/test_auth_login.py tests/test_admin_protection.py -v
# Manual: curl -X POST :8000/api/v1/auth/login -d '{"username":"admin","password":"..."}'
# Manual: curl :8000/api/v1/admin/connections   # → 401
# Manual: curl -H "Authorization: Bearer <jwt>" :8000/api/v1/admin/connections   # → 200
```

**Phase 3**
```
cd frontend && npm run eslint && npm run prettier:check && npm run test
npm run dev   # browser: visit /, expect redirect to /login; log in; verify token in localStorage; force 401 from devtools, expect redirect to /login.
```

**Phase 4**
```
cd backend && pytest tests/test_data_service.py tests/test_access_log_session.py tests/test_executor_startup.py -v
cd backend && pytest tests/test_endpoints.py tests/test_security.py -v   # behavior preservation
# Manual: hit a live endpoint, kill DB mid-request, confirm access log row still written.
```

**Phase 5**
```
cd backend && ruff check . && mypy . && pytest -v   # all existing tests must still pass
```

**Phase 6**
```
cd frontend && npm run test -- --coverage
npm run dev   # smoke each page: list, create, edit, delete; run the endpoint wizard end-to-end.
```

**Phase 7**
```
cd backend && pytest --cov=app --cov-fail-under=<threshold>
cd frontend && npm run test -- --coverage
make migrate-down-up
```

**Phase 8**
```
cd backend && alembic upgrade head && pytest tests/test_endpoints.py -v
# Manual: try to create an endpoint with auth_method_id=null → 422
```

---

## Critical Files

- `backend/app/config.py` — Phases 1, 2.
- `backend/app/main.py:44-67, 89-97` — Phase 2 (router include), Phase 4 (lifespan Oracle init).
- `backend/app/auth/{jwt_utils.py,hashing.py}` — reuse only; do not modify.
- `backend/app/dependencies.py` — Phase 2 (extend with `get_current_admin`).
- `backend/app/routers/data.py` — Phase 4 (slim to ~150 LOC), Phase 8.
- `backend/app/sql/executor.py:50` — Phase 4 (drop per-request init).
- `backend/app/repositories/*.py` — Phase 5.
- `frontend/src/App.tsx:14-33` — Phase 3.
- `frontend/src/lib/api.ts` — Phase 3 (interceptors).
- `frontend/src/components/endpoints/EndpointWizard.tsx` — Phase 6.
- `.github/workflows/{backend,frontend}.yml` — Phases 1, 2, 7.

## Reused Utilities

- `backend/app/auth/jwt_utils.py` — `create_access_token`, `verify_access_token`, `TokenError`.
- `backend/app/auth/hashing.py` — `hash_password`, `verify_password`.
- `backend/app/database.py` — `AsyncSessionLocal` (Phase 4 access-log session).
- `backend/app/main.py` — existing `lifespan` context (Phase 4 startup hook).
- `frontend/src/components/ui/*` — all primitives (Phases 3, 6).
- `frontend/src/lib/queryClient.ts` — Phases 3, 6.

## Score Trajectory (estimated)

| Phase complete | Overall | Driver |
|---|---|---|
| Baseline | 66 | as audited |
| 1 | 70 | crypto + JWT default |
| 2 | 79 | admin auth (security 45 → 78) |
| 3 | 82 | full auth flow end-to-end |
| 4 | 85 | architecture cleaned, complexity down |
| 5 | 87 | duplication down |
| 6 | 89 | frontend duplication down, testable |
| 7 | 91 | coverage + CI thresholds enforced |
| 8 | 92 | defense-in-depth on data plane |
