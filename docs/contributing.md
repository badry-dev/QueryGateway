# Contributing to QueryGateway

## Prerequisites

| Tool | Minimum version |
|------|----------------|
| Python | 3.14 |
| Node.js | 20 LTS |
| Docker | 24 |
| Docker Compose | v2 (bundled with Docker Desktop) |
| Git | 2.40 |

## Initial Setup

### 1. Clone the repo

```sh
git clone <repo-url>
cd QueryGateway
```

### 2. Backend

```sh
cd backend
python -m venv .venv
# Linux/macOS:
. .venv/bin/activate
# Windows:
.venv\Scripts\activate

pip install -r requirements.txt

# Copy and edit environment variables
cp .env.example .env
```

### 3. Frontend

```sh
cd frontend
npm install

# Copy environment config (if present)
# cp .env.example .env
```

### 4. Docker (optional, for full stack)

```sh
# Copy root env example
cp .env.example .env
# Edit .env to set JWT_SECRET_KEY and ENCRYPTION_KEY

docker compose up -d --build
```

Compose runs the one-shot `migrate` service before the API starts, so a fresh local `db_data` volume is initialized automatically.

To rerun migrations without restarting the whole stack:

```sh
make docker-migrate
```

To include a local Oracle XE instance:

```sh
docker compose --profile oracle up -d
```

## Running Locally

### Backend (dev server with hot reload)

```sh
cd backend && uvicorn app.main:app --reload
```

API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/api/docs`.

### Frontend (Vite dev server)

```sh
cd frontend && npm run dev
```

SPA is available at `http://localhost:5173`. Requests to `/api/*` are proxied to the backend.

## Checks and Tests

Run these before opening a PR:

```sh
# Backend
cd backend
ruff check .
mypy .
pytest

# Frontend
cd frontend
npm run eslint
npm run prettier:check
npm run test

# Docker
docker compose build
```

Or use the Makefile at the repo root:

```sh
make check         # run all checks
make check-backend
make check-frontend
make docker-build
```

## Making Changes

1. Create a branch: `git checkout -b feat/<scope>`.
2. Make minimal, scoped changes.
3. For schema changes: add an Alembic migration (`alembic revision --autogenerate -m "describe change"`).
4. For API changes: maintain `/api/v1/*` compatibility or introduce a `/api/v2/*` route.
5. Run all checks for the area you changed.
6. Update `docs/` if you changed API contracts, config, or significant behavior.
7. Open a PR against `main`.

For endpoint parameter, schedule binding, or snapshot filtering changes, update
[the canonical parameter contract](scheduler_parameter_bindings.md) and keep the related root and
`.github/instructions/` agent guidance aligned.

## What CI Checks

| Job | Checks |
|-----|--------|
| Backend | `ruff check`, `mypy`, `pytest` |
| Frontend | `eslint`, `prettier --check`, `vitest` |
| Docker | backend + frontend image builds, `docker compose config` |

All jobs are required to pass before a PR can be merged.

## Coding Conventions

See [docs/conventions.md](./conventions.md) for full details on:
- Branch/PR rules and commit hygiene
- API versioning and deprecation policy
- Database migration workflow
- Security constraints (SQL safety, auth, secrets)
- Logging standards
- Code style (Python and TypeScript)
