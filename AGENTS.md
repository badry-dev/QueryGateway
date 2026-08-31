# QueryGateway Agent Guide (Canonical)

## Mission
Build and maintain a secure, testable monorepo for dynamic SQL-to-API exposure with:
- Backend: Python 3.14+, FastAPI, SQLAlchemy 2.0, Alembic, APScheduler 3.x, Pydantic Settings v2, PyJWT, bcrypt, structlog.
- Frontend: Vite + React SPA, TypeScript, shadcn/ui, Tailwind.
- Infra: Docker + docker-compose, GitHub Actions CI.

## Repo Map and Boundaries
- `backend/` owns API contracts, DB schema, migrations, auth, scheduler, SQL execution safety.
- `frontend/` owns admin UI only (wizard, connections, auth config, schedules, settings, health dashboard).
- `docker/` owns images, compose support assets, runtime container config.
- `docs/` owns architecture notes, API version/deprecation notes, runbooks.
- Do not move logic across boundaries without updating docs and tests.

## Non-Negotiable Rules
- API versioning is required from day one.
- Admin routes must be under `/api/v1/admin/*`.
- Data routes must be under `/api/v1/data/*`.
- All data endpoints require authentication.
- All user SQL must use bind parameters only.
- Never string-concatenate SQL.
- Alembic migration is required for every schema change.
- Never edit an already-applied migration; create a new revision.
- Password hashing must use `bcrypt`.
- JWT must use `PyJWT` and include expiration (`exp`).
- Logging must be structured via `structlog`.

## SQL Safety Contract
- Allowed bind style: `:param_name`.
- Parameter mapping source: validated request inputs -> typed schema -> bind dict.
- Reject queries containing interpolated values from raw strings.
- Execute user SQL through SQLAlchemy Core `text()` with bound params.
- Bind markers inside single-quoted SQL literals are text, not parameters; never quote a bind
  placeholder (use `column = :value`, not `column = ':value'`).

## Parameter Ownership Contract
- SQL preview values are temporary samples only; they are never persisted as endpoint or schedule
  defaults.
- Live and snapshot HTTP requests enforce every descriptor marked `required`, even when the
  endpoint descriptor contains a default.
- Optional live-request parameters may use a typed literal default, explicit SQL `NULL`, or the
  supported dynamic date defaults `today` and `yesterday`.
- Scheduled snapshot execution never reads endpoint defaults. Every SQL bind is owned by the
  schedule through exactly one validated binding source: `literal`, `null`, `run_date`,
  `relative_date`, `window_start`, or `window_end`.
- Date inputs accept `YYYY-MM-DD` and `DD-MM-YYYY`. Schedule calendar math is evaluated from the
  persisted nominal run time in the schedule's IANA timezone.

## Snapshot Request Contract
- Every parameterized snapshot endpoint must map every request parameter to a cached output
  column and one operator: `eq`, `gte`, or `lte`.
- Mappings target the final cached column name after `column_map` renaming. They filter rows; they
  are not tenant authorization. Authentication remains mandatory and independent.
- Select the newest retained snapshot whose persisted resolved schedule parameters cover the
  request, then apply typed row filtering. Never return an unfiltered parameterized snapshot.
- Missing/invalid required parameters, reversed ranges, incomplete mappings, unavailable mapped
  columns, and out-of-coverage requests return explicit HTTP 422 responses. No retained snapshot
  returns HTTP 503; an in-coverage request with no matching rows returns HTTP 200 with `data: []`.
- `null_means_all` is valid only for an optional `eq` mapping and means a scheduled SQL `NULL`
  covers every requested value for that parameter.
- Snapshot mappings are stored in the existing endpoint parameter JSON and do not require a
  relational migration. Schedule-owned bindings and logical-run audit fields are relational and
  are covered by Alembic revision `e4a6c2d9f801`.

## Required Log Fields
- `request_id`
- `user`
- `endpoint`
- `status`
- `duration_ms`
- `method`
- `client_ip`
- `event`

## Before Editing (Agent Procedure)
- Scan relevant files first.
- State intended change scope.
- List commands you will run before making edits.
- Confirm whether DB schema or API contract is affected.

## After Editing (Agent Procedure)
- Run formatting/lint/tests for changed areas.
- Add/update Alembic migration when schema changed.
- Update docs when contracts, settings, or workflows changed.
- Keep `README.md`, `docs/architecture.md`, `docs/scheduler_parameter_bindings.md`, and relevant
  agent instructions aligned when parameter or snapshot behavior changes.
- Verify no secrets/tokens/credentials are committed.

## Stop Conditions
- If schema behavior is unclear, inspect Alembic history before coding.
- If API behavior is unclear, check `/api/v1` contract and existing routers.
- If request is ambiguous, do not invent endpoints or fields.

## Definition of Done
- Relevant tests pass locally.
- CI-equivalent checks pass for changed scope.
- Migrations included when needed.
- Versioning/deprecation policy respected.
- No security rule violations.
