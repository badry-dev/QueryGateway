# Claude Code Persistent Context

## Project Identity
QueryGateway is a monorepo for creating secure, dynamic REST endpoints from Oracle SQL queries with optional scheduled snapshot caching.

## Stack Snapshot
- Python 3.14+, FastAPI, Pydantic Settings v2.
- PostgreSQL app DB, SQLAlchemy 2.0, Alembic.
- Oracle connectivity via `python-oracledb`.
- APScheduler 3.x with an in-memory job store; schedule definitions are persisted in PostgreSQL
  and active jobs are restored on API startup.
- Auth: `PyJWT` + `bcrypt`.
- Logging: `logging` + `structlog`.
- Frontend: Vite + React SPA + TypeScript + shadcn/ui + Tailwind.
- The endpoint wizard uses CodeMirror 6 through `@uiw/react-codemirror` for SQL authoring.

## Repo Map
- `backend/`: API, models, migrations, scheduler, auth, SQL execution.
- `frontend/`: admin SPA for modules 1-5.
- `docker/`: Docker assets.
- `docs/`: specs and runbooks.
- `.github/`: CI and assistant instructions.

## Route Conventions
- Admin API: `/api/v1/admin/*`.
- Dynamic data API: `/api/v1/data/*`.
- No unversioned routes for new features.
- Breaking API change requires new version path.

## Migration Conventions
- Alembic required for schema changes.
- Create revision: `alembic revision --autogenerate -m "message"`.
- Upgrade: `alembic upgrade head`.
- Downgrade check: `alembic downgrade -1`.
- Never mutate committed/applied migration files.

## Auth Conventions
- Hash credentials/passwords with `bcrypt` only.
- JWT creation/verification with `PyJWT` only.
- Include `exp`, `iat`, and subject claims.
- Reject expired or malformed tokens deterministically.

## SQL Execution Conventions
- User-defined SQL must be parameterized.
- Bind style is `:param_name`.
- Validate and coerce params with typed schemas before execution.
- Use SQLAlchemy `text()` + bind dict.
- Never concatenate request values into SQL strings.
- Bind markers inside single-quoted SQL literals are not parameters and must not be used.

## Endpoint and Scheduler Parameter Conventions

- Preview inputs are temporary samples and are not persisted.
- Every required HTTP parameter remains required for live and snapshot requests, regardless of
  configured endpoint defaults.
- Endpoint defaults apply to omitted optional live requests only. Schedules own every SQL bind
  through `literal`, `null`, `run_date`, `relative_date`, `window_start`, or `window_end`.
- Parameterized snapshot endpoints map every request parameter to a post-rename cached column via
  `eq`, `gte`, or `lte`. Coverage is checked against persisted job-run parameters before cached
  rows are filtered.
- Snapshot filter mappings select data; they never replace endpoint authentication or authorize a
  tenant.
- The full contract and stable error codes are documented in
  `docs/scheduler_parameter_bindings.md`.

## Logging Conventions

- Use structured logging everywhere.
- Mandatory fields: `request_id`, `user`, `endpoint`, `status`, `duration_ms`, `method`,
  `client_ip`, `event`.
- Add scheduler fields for jobs: `job_id`, `run_id`, `row_count`, `success`.

## Run Commands (Expected)

- Backend setup: `cd backend && python3.14 -m venv .venv && . .venv/bin/activate`
  (Windows: `py -3.14 -m venv .venv`, then `.venv\Scripts\activate`) and install
  `requirements.txt`.
- Backend dev: `cd backend && uvicorn app.main:app --reload`.
- Backend checks: `cd backend && ruff check . && mypy . && pytest`.
- Frontend setup: `cd frontend && npm install`.
- Frontend dev: `cd frontend && npm run dev`.
- Frontend checks: `cd frontend && npm run eslint && npm run prettier:check && npm run test`.
- Docker build: `docker compose build`.
- Docker run: `docker compose up -d --build` (the one-shot `migrate` service must complete before
  the API starts).

## Working Protocol
- Before edits: summarize target files and planned commands.
- During edits: keep changes minimal and scoped.
- After edits: run checks for changed area; update tests/docs/migrations.
- Stop if schema or API contract is unclear; inspect migrations/spec instead of guessing.
