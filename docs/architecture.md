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
│  │   job store,      │                  │                    │ │
│  │   snapshots)      │                  │  python-oracledb   │ │
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

All user-defined SQL is executed via SQLAlchemy `text()` with named bind parameters (`:param_name`). String interpolation of user input is prohibited at all layers. Bind values are validated through typed Pydantic schemas before reaching the query executor.

Live data requests enforce every parameter marked `required`, even when that parameter also has a scheduler default. Defaults exist so scheduled execution can run without request input and so optional live parameters can be omitted. Date query parameters accept `YYYY-MM-DD` and `DD-MM-YYYY`; both formats are normalized to Python `date` values before database binding.

### Authentication

- Admin API: session-based or JWT Bearer (TBD per Phase 1).
- Data endpoints: per-endpoint configurable auth — Bearer token, Basic Auth, or API key. Middleware resolves the policy from endpoint metadata at request time and enforces it when an auth method is attached. Endpoints published without an auth method are served publicly, so one must be assigned to any endpoint that should be protected.
- Credentials are hashed with `bcrypt`; tokens are issued/verified with `PyJWT`.

### Scheduler

APScheduler 3.x runs in-process with an in-memory job store. Schedule definitions are persisted in PostgreSQL, and every active schedule is registered when it is created, updated, resumed, or restored during API startup. Execution telemetry (start time, duration, row count, status, errors) is written to the app DB and exposed through admin APIs. Deleting a schedule sets the historical job run's `schedule_id` to `NULL`, preserving both audit history and snapshots. Deleting an endpoint removes its schedule and cached snapshots, unregisters its in-memory job after the database commit, and sets the historical job run's `endpoint_id` (and cascaded `schedule_id`) to `NULL` so the audit record remains available.

The scheduler is intentionally single-process. Run one API process/replica unless distributed scheduler coordination is added; otherwise each process would register and execute the same persisted schedules.

### Snapshot Cache

Scheduled endpoints can serve results from a PostgreSQL JSONB snapshot rather than executing live queries. Every bind parameter on a snapshot endpoint must define a fixed default, an explicit SQL `NULL` default for an optional bind, or a dynamic date expression (`today` or `yesterday`) so refreshes never depend on request inputs. Dynamic defaults are resolved from the application server date at execution time, while explicit null defaults remain present in the bind dictionary with a `None` value so the database receives SQL `NULL`. Freshness metadata is returned in responses. Stale snapshot fallback behavior is configurable per endpoint.

### Configuration

Pydantic Settings v2 loads all configuration from environment variables (`.env` in development, injected secrets in production). No hardcoded configuration values in source code.

### Logging

`structlog` emits structured JSON with mandatory correlation fields (`request_id`, `user`, `endpoint`, `status`, `duration_ms`, `event`). Sensitive fields are redacted at middleware level before emission.

## Directory Layout

```
QueryGateway/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app factory, CORS, router registration
│   │   ├── config.py        # Pydantic Settings
│   │   ├── models/          # SQLAlchemy models (Phase 1+)
│   │   ├── routers/         # Route handlers (Phase 1+)
│   │   ├── services/        # Business logic layer (Phase 1+)
│   │   ├── repositories/    # DB access layer (Phase 1+)
│   │   ├── auth/            # JWT + bcrypt utilities (Phase 3+)
│   │   ├── scheduler/       # APScheduler integration (Phase 5+)
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
│   ├── architecture.md      # This file
│   ├── conventions.md       # Coding standards
│   ├── contributing.md      # Onboarding guide
│   ├── deployment.md        # Deployment runbook (Phase 7)
│   ├── operations.md        # Backup/restore, monitoring, troubleshooting (Phase 7)
│   └── security_checklist.md # Security validation checklist (Phase 7)
├── .github/
│   ├── workflows/
│   │   ├── backend.yml      # Backend CI
│   │   ├── frontend.yml     # Frontend CI
│   │   └── docker.yml       # Docker build CI
│   └── instructions/        # AI assistant context files
├── docker-compose.yml
└── .env.example
```
