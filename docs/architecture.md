# Architecture Overview

## System Components

```
┌───────────────────────────────────────────────────────────────────┐
│                        QueryGateway                               │
│                                                                   │
│  ┌──────────────┐    HTTP     ┌──────────────────────────────┐   │
│  │   Frontend   │ ──────────▶ │         Backend (FastAPI)    │   │
│  │  (React SPA) │            │                              │   │
│  │  Port: 80    │            │  /api/v1/admin/*  (admin)    │   │
│  └──────────────┘            │  /api/v1/data/*   (consumer) │   │
│                              │                              │   │
│                              │  ┌──────────────────────┐   │   │
│                              │  │   APScheduler 3.x    │   │   │
│                              │  │   (in-process)       │   │   │
│                              │  └──────────┬───────────┘   │   │
│                              └─────────────┼───────────────┘   │
│                                            │                    │
│              ┌─────────────────────────────┴──────────┐        │
│              │                                         │        │
│  ┌───────────▼───────┐                  ┌─────────────▼──────┐ │
│  │    PostgreSQL      │                  │  Oracle Database   │ │
│  │  (app metadata,   │                  │  (user data source)│ │
│  │   schedule defs,  │                  │                    │ │
│  │   job history,    │                  │  python-oracledb   │ │
│  │   snapshots)      │                  │                    │ │
│  └───────────────────┘                  └────────────────────┘ │
└───────────────────────────────────────────────────────────────────┘
```

## Route Namespaces

| Namespace | Purpose | Who calls it |
|-----------|---------|--------------|
| `/api/v1/admin/*` | Manage connections, auth, endpoints, schedules, settings, health | Admin SPA |
| `/api/v1/data/*` | Serve dynamic data from live queries or snapshots | API consumers |

## Key Design Decisions

### SQL Safety

All user-defined SQL is executed via SQLAlchemy `text()` with named bind parameters
(`:param_name`). String interpolation of user input is prohibited at all layers. A bind marker
inside a single-quoted SQL literal is text and is intentionally ignored. Bind values are validated
through typed Pydantic schemas before reaching the query executor.

Live and snapshot data requests enforce every parameter marked `required`, even if an endpoint
default exists. Preview inputs are temporary. Endpoint defaults resolve only omitted optional live
request values; scheduled queries instead require a separate binding for every SQL parameter. Date
query parameters accept `YYYY-MM-DD` and `DD-MM-YYYY`; both formats are normalized to Python
`date` values before database binding. See [Endpoint, scheduler, and snapshot parameter
contracts](scheduler_parameter_bindings.md).

### Authentication

- Admin API: an environment-seeded administrator authenticates through `/api/v1/auth/login`; the
  protected admin API uses the resulting JWT Bearer token.
- Data endpoints: every `/api/v1/data/*` request is authenticated. The data service enforces the
  endpoint's Bearer token, Basic Auth, or API key method when configured; otherwise it requires the
  platform admin Bearer token. Anonymous data access is never allowed.
- Credentials are hashed with `bcrypt`; tokens are issued/verified with `PyJWT`.

### Scheduler

APScheduler 3.x runs in-process with an in-memory job store. Schedule definitions are persisted in
PostgreSQL, and every active schedule is registered when it is created, updated, resumed, or
restored during API startup. Each schedule owns its timezone, parameter bindings, and optional
date-window preset. The database `next_run_at` is captured as the nominal `scheduled_for` time, so
delayed execution still resolves the same logical date; manual runs can provide an explicit logical
date. A unique `(schedule_id, scheduled_for)` constraint makes a logical run idempotent. Execution
telemetry includes start/finish times, logical date, window boundaries, resolved parameters,
trigger source, binding hash, row count, status, and errors. Deleting a schedule sets the
historical job run's `schedule_id` to `NULL`, preserving both audit history and snapshots. Deleting
an endpoint removes its schedule and cached snapshots, unregisters its in-memory job after the
database commit, and sets the historical job run's `endpoint_id` (and cascaded `schedule_id`) to
`NULL` so the audit record remains available.

The scheduler is intentionally single-process. Run one API process/replica unless distributed scheduler coordination is added; otherwise each process would register and execute the same persisted schedules.

### Snapshot Cache

Scheduled endpoints can serve results from a PostgreSQL JSONB snapshot rather than executing live
queries. Schedule creation requires exact coverage of the endpoint's SQL binds. The declarative
binding sources are fixed literal, explicit SQL `NULL` for an optional bind, logical run date,
relative logical date, and inclusive window start/end. Supported windows are previous day, last N
complete days, week to date, previous week, month to date, and previous month.

After final output-column mapping and before persistence, each non-empty scheduled result must
match its resolved schedule parameters under the endpoint's declared `eq`, `gte`, and `lte`
snapshot filters. An inconsistent or unparseable result fails the job without replacing retained
valid snapshots; the scheduler never guesses or rewrites source values. The data plane revalidates
retained candidates, falls back to an older valid covering snapshot when possible, and returns an
explicit HTTP 503 integrity error when none is usable.

Each parameterized snapshot endpoint also declares an explicit final cached-output-column mapping
and one whitelisted operator (`eq`, `gte`, or `lte`). The data plane validates required fields and
types, rejects reversed ranges, selects the newest retained job snapshot whose persisted resolved
values cover the request, validates mapped columns, and filters the cached rows. It never falls
back to returning the entire snapshot when mappings or request parameters are missing. A covered
request with no business rows returns an empty `data` array; an out-of-coverage request is an
explicit HTTP 422, while the absence of any retained snapshot is HTTP 503. These mappings are data
selection only; tenant authorization continues to be owned by the endpoint authentication method.
Arbitrary Python, JavaScript, and SQL expressions are intentionally unsupported.

Snapshot filter mappings extend the endpoint's existing JSON parameter document and therefore do
not change the relational schema. Schedule-owned parameter bindings and logical-run audit fields
are relational and are managed by Alembic. See [Endpoint, scheduler, and snapshot parameter
contracts](scheduler_parameter_bindings.md) for the full contract and date semantics.

### Configuration

Pydantic Settings v2 loads all configuration from environment variables (`.env` in development, injected secrets in production). No hardcoded configuration values in source code.

### Logging

`structlog` emits structured JSON with mandatory correlation fields (`request_id`, `user`,
`endpoint`, `status`, `duration_ms`, `method`, `client_ip`, `event`). Sensitive fields are redacted
at middleware level before emission.

## Directory Layout

```
QueryGateway/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app factory, CORS, router registration
│   │   ├── config.py        # Pydantic Settings
│   │   ├── models/          # SQLAlchemy models (Phase 1+)
│   │   ├── routers/         # Route handlers (Phase 1+)
│   │   ├── services/        # Business logic, scheduler, snapshot filtering
│   │   ├── repositories/    # DB access layer (Phase 1+)
│   │   ├── auth/            # JWT + bcrypt utilities (Phase 3+)
│   │   └── sql/             # SQL execution and validation (Phase 4+)
│   ├── alembic/             # Migration environment (Phase 1+)
│   ├── tests/               # Pytest test suite
│   ├── requirements.txt
│   └── pyproject.toml       # ruff, mypy, pytest config
├── frontend/
│   ├── src/
│   │   ├── main.tsx         # React app entry
│   │   ├── App.tsx          # Root component / router (Phase 1+)
│   │   ├── components/      # shadcn/ui + custom components (Phase 2+)
│   │   ├── pages/           # Route-level page components (Phase 2+)
│   │   ├── lib/             # API clients, utilities (Phase 2+)
│   │   └── test/            # Vitest setup
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   └── package.json
├── docker/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   └── nginx.conf
├── docs/
│   ├── architecture.md                 # This file
│   ├── scheduler_parameter_bindings.md # Parameter and snapshot contracts
│   ├── conventions.md                  # Coding standards
│   ├── contributing.md                 # Onboarding guide
│   ├── deployment.md                   # Deployment runbook
│   ├── operations.md                   # Backup/restore and troubleshooting
│   └── security_checklist.md           # Security validation checklist
├── .github/
│   ├── workflows/
│   │   ├── backend.yml      # Backend CI
│   │   ├── frontend.yml     # Frontend CI
│   │   └── docker.yml       # Docker build CI
│   └── instructions/        # AI assistant context files
├── docker-compose.yml
└── .env.example
```
