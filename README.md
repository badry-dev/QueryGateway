# QueryGateway

> A self-hosted platform that turns Oracle SQL queries into secure, versioned REST API endpoints — no application code required. Author a parameterized query in a guided wizard, attach authentication, choose a data-freshness strategy, and publish a live endpoint that other systems can consume.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE.txt)
[![Python](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/)
[![Backend CI](https://github.com/Badry-Kudu/QueryGateway/actions/workflows/backend.yml/badge.svg)](https://github.com/Badry-Kudu/QueryGateway/actions/workflows/backend.yml)
[![Frontend CI](https://github.com/Badry-Kudu/QueryGateway/actions/workflows/frontend.yml/badge.svg)](https://github.com/Badry-Kudu/QueryGateway/actions/workflows/frontend.yml)
[![Docker Build](https://github.com/Badry-Kudu/QueryGateway/actions/workflows/docker.yml/badge.svg)](https://github.com/Badry-Kudu/QueryGateway/actions/workflows/docker.yml)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](docs/contributing.md)

QueryGateway is built for teams that need to expose data from an Oracle database over HTTP safely and quickly. Instead of writing and deploying a bespoke microservice for every report or integration, an administrator defines the query once through a web console, and QueryGateway handles routing, authentication, parameter validation, SQL safety, optional caching, and scheduled refresh.

![QueryGateway demo](./demo.gif)

> ⭐ If QueryGateway is useful to you, please consider starring the repo — it helps others discover the project.

## Contents

- [Why QueryGateway?](#why-querygateway)
- [Who It's For](#who-its-for)
- [How It Works](#how-it-works)
- [Features](#features)
- [Platform Support](#platform-support)
- [Quick Start](#quick-start)
- [Local Run (Without Docker)](#local-run-without-docker)
- [Development](#development)
- [Database Migrations](#database-migrations)
- [Roadmap](#roadmap)
- [Contributing & Community](#contributing--community)
- [Documentation](#documentation)
- [Tech Stack](#tech-stack)
- [License](#license)

## Why QueryGateway?

Exposing data from an Oracle database over an API usually means writing a new service: wiring up a connection pool, validating inputs, guarding against SQL injection, adding authentication, handling caching, and shipping a deployment — repeated for every query. It's slow, and each hand-rolled service is another place for a security mistake.

QueryGateway collapses that work into a configuration step. Define the query once, and you get a hardened, versioned endpoint with parameter validation, configurable authentication, and optional caching built in:

- **No glue code** — go from SQL to a deployed endpoint through a wizard, not a codebase.
- **Built-in security controls** — bind-parameter-only SQL, encrypted credentials, and per-endpoint authentication (Bearer/Basic/API key).
- **Fast and consistent** — every endpoint gets the same validation, logging, and versioning, so quality doesn't depend on who wrote it.
- **Cache when you need it** — serve heavy queries from scheduled snapshots instead of hitting Oracle on every request.
- **Self-hosted** — your data and credentials never leave your infrastructure.

## Who It's For

- **Data & platform teams** that field a constant stream of "can you give me an API for this report?" requests.
- **Internal tools & dashboards** that need read access to Oracle data without direct database credentials.
- **Partner / B2B data feeds** where each consumer needs its own authenticated, parameterized endpoint.
- **BI and analytics tools** that consume JSON over HTTP and benefit from cached snapshots of expensive queries.
- **Mobile and web backends** that need a thin, safe read layer over an existing Oracle system.

## How It Works

```text
Define connection ─▶ Author SQL (with :bind params) ─▶ Attach auth ─▶ Choose data strategy ─▶ Publish
                                                                                                  │
   API consumer ──── GET /api/v1/data/<your-endpoint> ──── auth-checked, parameter-validated ─────┘
```

1. **Connect** to your Oracle database with securely stored, encrypted credentials.
2. **Author** a `SELECT` query using named bind parameters (`:param_name`) in a rich SQL editor. The wizard detects parameters as you type and requests temporary sample values before previewing the results.
3. **Secure** the endpoint by attaching a Bearer token, Basic Auth, or API key policy.
4. **Choose** a data strategy: serve results **live** on each request, or from a **scheduled snapshot** cache.
5. **Publish** a versioned endpoint under `/api/v1/data/*` that resolves dynamically — no service restart needed.

## Features

QueryGateway is organized into five admin modules, all driven from the React admin console:

| Module | What it does |
|--------|--------------|
| **Connections** | Create, edit, test, and delete Oracle database connections. Credentials are encrypted at rest; pool sizing and timeouts are configurable. Uses `python-oracledb`; thin mode needs no native client, while the backend Docker image includes Oracle Instant Client 19.32 for thick mode. |
| **API Creation Wizard** | A multi-step wizard that turns a parameterized SQL query into a deployable GET endpoint: pick a connection, author SQL with a rich editor, supply preview-only sample values for detected bind parameters, preview sample rows and inferred schema, map/rename output columns, attach an auth method, and select a data strategy. |
| **Authentication** | Manage per-endpoint auth methods — Bearer token (JWT), Basic Auth, and API key. Tokens are issued/verified with `PyJWT`; credentials are hashed with `bcrypt`. When an auth method is attached to an endpoint, middleware enforces it on every request; endpoints with no auth method attached are served publicly. |
| **Scheduling & Snapshots** | Schedule query refreshes with the in-process APScheduler (cron or interval). Run now, pause/resume, and enable/disable jobs. Results are cached as PostgreSQL JSONB snapshots and served with freshness metadata. Schedule definitions are persisted in the app database; the active APScheduler jobs run in-memory and are (re)registered when a schedule is created, updated, or resumed. |
| **Settings & Health** | Configure runtime settings (base URL/port, logging level, query timeouts, CORS/rate-limit inputs) and view a health dashboard covering API, PostgreSQL, Oracle connectivity, scheduler status, and recent job outcomes. |

### Security by Default

- **SQL injection resistant** — user-defined SQL runs only through SQLAlchemy `text()` with named bind parameters. Request values are never concatenated into SQL strings, and bind values are validated through typed schemas before execution.
- **Encrypted credentials** — Oracle connection secrets are encrypted at rest using an environment-provided key.
- **Per-endpoint authentication** — attach a Bearer token, Basic Auth, or API key policy to an endpoint and it is enforced on every request. Endpoints published without an auth method are public, so assign one to any endpoint that should be protected.
- **Structured, redacted logging** — `structlog` emits JSON logs with correlation fields (`request_id`, `user`, `endpoint`, `status`, `duration_ms`); credentials and tokens are redacted before emission.

### Two API Surfaces

| Namespace | Purpose | Who calls it |
|-----------|---------|--------------|
| `/api/v1/admin/*` | Manage connections, auth, endpoints, schedules, settings, and health | The admin SPA |
| `/api/v1/data/*` | Serve dynamic data from live queries or cached snapshots | Your API consumers |

All routes are versioned from day one; breaking contract changes are introduced under a new version path rather than mutating `v1`.

## Platform Support

- Development: Windows and Ubuntu/Linux
- Deployment: Ubuntu/Linux (recommended)
- Docker workflow: supported on both Windows (Docker Desktop) and Ubuntu/Linux

> **Python version:** Python 3.14 or newer is required (`asyncpg` 0.31.0+ ships CPython 3.14 wheels). Create the virtual environment with a 3.14 interpreter: `py -3.14 -m venv .venv` (Windows) or `python3.14 -m venv .venv` (Linux).

## Quick Start

```sh
# Install dependencies
make setup

# Run checks
make check

# Start with Docker
cp .env.example .env   # Set JWT_SECRET_KEY and ENCRYPTION_KEY (see deployment.md for generation commands)
make docker-up
```

`make docker-up` runs the one-shot `migrate` service first, then starts the API and web containers after PostgreSQL is healthy and Alembic is at `head`.

The backend image downloads Oracle Instant Client 19.32 Basic from Oracle's
versioned HTTPS URL, verifies Oracle's published SHA-256, and registers it with
the Linux dynamic linker. Set
`ORACLE_CLIENT_LIB_DIR=/opt/oracle/instantclient_19_32` in `.env` to initialize
`python-oracledb` thick mode when the API starts; leave it blank for thin mode.

- Frontend SPA: `http://localhost`
- API through nginx: `http://localhost/api/v1/...`

## Local Run (Without Docker)

> **Python version:** Use Python 3.14 or newer (`asyncpg` 0.31.0+ provides CPython 3.14 wheels).
>
> **Note (Windows):** `psycopg2-binary` may fail to build from source if PostgreSQL dev tools are not installed. The `requirements.txt` uses a relaxed pin (`>=2.9.9`) so pip selects a pre-built wheel automatically. Always run `pip install --upgrade pip` first.

### Windows (PowerShell)

```powershell
# Step 1 — Start PostgreSQL (skip if already running)
docker run -d --name db2api-pg `
  -e POSTGRES_USER=db2api -e POSTGRES_PASSWORD=db2api -e POSTGRES_DB=db2api `
  -p 5432:5432 postgres:16
# Wait ~5 seconds for PostgreSQL to initialize before continuing

# Step 2 — Backend
cd backend
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
# edit .env — set ENCRYPTION_KEY and JWT_SECRET_KEY before continuing

# Step 3 — Run database migrations
alembic upgrade head

# Step 4 — Start the backend
uvicorn app.main:app --reload
```

```powershell
# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

### Ubuntu/Linux (bash)

```bash
# Step 1 — Start PostgreSQL (skip if already running)
docker run -d --name db2api-pg \
  -e POSTGRES_USER=db2api -e POSTGRES_PASSWORD=db2api -e POSTGRES_DB=db2api \
  -p 5432:5432 postgres:16
# Wait ~5 seconds for PostgreSQL to initialize before continuing

# Step 2 — Backend
cd backend
python3.14 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
# edit .env — set ENCRYPTION_KEY and JWT_SECRET_KEY before continuing

# Step 3 — Run database migrations
alembic upgrade head

# Step 4 — Start the backend
uvicorn app.main:app --reload
```

```bash
# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

### Local URLs

- API docs (Swagger): `http://localhost:8000/api/docs`
- Health check: `http://localhost:8000/api/v1/admin/health/live`
- Frontend SPA: `http://localhost:5173` (start frontend dev server first — see above)

> **Note:** `http://localhost:8000/` returns 404 — the backend serves no root route. All API routes are under `/api/v1/`.

## Development

```sh
make backend-dev    # FastAPI dev server on :8000 (hot reload)
make frontend-dev   # Vite dev server on :5173 (proxy /api to :8000)
```

Note: `make` targets are POSIX-oriented and work natively on Ubuntu/Linux. On Windows, run the platform-specific commands above, or use WSL/Git Bash with `make`.

## Database Migrations

Docker Compose applies migrations automatically through the `migrate` service before `api` starts. For non-Docker local runs, run Alembic manually:

```sh
# Docker: rerun only the migration service
make docker-migrate

# Equivalent raw Compose command
docker compose up --build --force-recreate migrate
```

```sh
cd backend
# Apply all pending migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "describe change"

# Rollback one step
alembic downgrade -1
```

## Roadmap

QueryGateway currently ships the five core admin modules (Connections, API Creation Wizard, Authentication, Scheduling & Snapshots, Settings & Health) for read-only Oracle endpoints. Areas we'd love help exploring next:

- **Additional data sources** — PostgreSQL, MySQL, and SQL Server as query targets (today: Oracle only).
- **Write endpoints** — controlled `POST`/`PUT`/`DELETE` data operations (today: read-only `GET`).
- **Consumer-facing API docs** — auto-generated OpenAPI specs and Postman collection export per endpoint.
- **Advanced access control** — finer-grained RBAC beyond the baseline admin role.
- **GraphQL** — an alternative query surface alongside REST.

These are not commitments or a release schedule — they're open directions. If one interests you, open an issue to discuss before starting work. See [`project_plan.md`](project_plan.md) for the full scope and non-goals.

## Contributing & Community

Contributions are welcome — whether that's code, docs, bug reports, or ideas.

- 🐛 **Found a bug or have a feature idea?** [Open an issue](https://github.com/Badry-Kudu/QueryGateway/issues).
- 🔧 **Want to contribute code?** Read the [contributing guide](docs/contributing.md) and [conventions](docs/conventions.md), then open a pull request.
- 💬 **Questions or feedback?** Start a [discussion or issue](https://github.com/Badry-Kudu/QueryGateway/issues) — we'd love to hear how you're using QueryGateway.
- ⭐ **Like the project?** Star the repo to help others find it.

## Documentation

- [Architecture](docs/architecture.md) — system components, design decisions, directory layout
- [Implementation Plan](project_plan.md) — modules, scope, and phased delivery
- [Deployment](docs/deployment.md) — self-hosted setup and secret generation
- [Operations](docs/operations.md) — backup/restore, monitoring, troubleshooting
- [Security Checklist](docs/security_checklist.md) — security validation controls
- [Conventions](docs/conventions.md) — coding standards
- [Contributing](docs/contributing.md) — onboarding guide
- [Progress](docs/progress.md) — implementation status

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| Backend | Python 3.14+, FastAPI, SQLAlchemy 2.0, Alembic, APScheduler 3.x, PyJWT, bcrypt, structlog |
| Frontend | Vite 6, React 18, TypeScript, shadcn/ui, Tailwind CSS 3, Vitest |
| App DB | PostgreSQL 16 (asyncpg) |
| Data Source | Oracle (`python-oracledb` thin or thick mode; Docker includes Instant Client 19.32) |
| CI/CD | GitHub Actions — backend (ruff/mypy/pytest), frontend (eslint/prettier/vitest), Docker build |

## License

QueryGateway is licensed under the [GNU General Public License v3.0](LICENSE.txt).
