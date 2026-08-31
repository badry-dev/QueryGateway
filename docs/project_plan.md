# QueryGateway Implementation Plan

QueryGateway is delivered as a self-hosted platform that lets teams expose Oracle query results as
secure REST endpoints through a guided wizard while preserving security-by-default, reproducible
infrastructure, and operational reliability. The implemented baseline uses Python 3.14+, FastAPI,
PostgreSQL, SQLAlchemy 2.0 + Alembic, APScheduler 3.x, Pydantic Settings, API versioning, a Vite +
React SPA, shadcn/ui + Tailwind, and Dockerized CI/CD.

## Scope and Non-Goals

### MVP Scope (Included)
- Module 1: Database Connection Management
  - Create, edit, delete, and test Oracle connections.
  - Secure credential storage and pool configuration.
- Module 2: API Creation Wizard
  - Connection selection, SQL authoring with bind parameters, preview/mapping, auth selection, endpoint definition, data strategy, deploy.
  - Dynamic endpoint registration and runtime routing.
- Module 3: Authentication Configuration
  - Manage Bearer token, Basic Auth, and API key methods.
  - Token generation and credential verification workflows.
- Module 4: Task Scheduling + Snapshot Cache
  - APScheduler-driven scheduled refresh jobs.
  - Snapshot persistence in PostgreSQL JSONB and execution logs.
- Module 5: Settings + Health Dashboard
  - Base URL/port and application runtime settings.
  - Health and status visibility for core dependencies.

### Non-Goals (Excluded from MVP)
- Additional databases beyond Oracle for user data sources (e.g., MySQL, SQL Server, PostgreSQL as target source DB).
- Write operations for dynamic data endpoints (POST/PUT/DELETE).
- GraphQL support.
- Auto-generated per-endpoint OpenAPI packages for consumer APIs.
- Postman collection export.
- Distributed task execution architecture (Celery/queue workers).
- Advanced RBAC beyond baseline admin role controls.

## Architecture and Repo Layout

### Monorepo Layout
- `backend/`: FastAPI service, domain logic, data layer, scheduler runtime, migrations.
- `frontend/`: Vite + React SPA admin console (shadcn/ui + Tailwind).
- `docker/`: Dockerfiles, runtime config, optional local Oracle XE profile.
- `docs/`: architecture decisions, API contracts, runbooks.
- `docker-compose.yml`: local/dev orchestration (`api`, `web`, `db`, optional `oracle`).

### Runtime Architecture
- Admin console (frontend SPA) consumes admin APIs only.
- Backend exposes two versioned namespaces:
  - `/api/v1/admin/*`: management APIs for connections, auth methods, endpoints, schedules, settings, logs.
  - `/api/v1/data/*`: dynamic consumer-facing data endpoints resolved at runtime.
- FastAPI service responsibilities:
  - Validate auth for every data endpoint request.
  - Resolve endpoint metadata and selected freshness strategy.
  - Execute parameterized SQL against Oracle (live mode) or select a covering retained snapshot
    and apply typed cached-row filters (snapshot mode).
  - Manage scheduler jobs and persist execution telemetry.

### Versioning and Deprecation Rules
- Versioning is mandatory from day one (`v1` prefixes for admin and data namespaces).
- Backward compatibility policy:
  - No breaking change inside `v1` without compatibility fallback.
  - Breaking contract changes require `v2` route introduction.
- Deprecation policy:
  - Mark deprecated endpoints in docs and response headers.
  - Maintain deprecated endpoint behavior for one full minor release cycle before removal.
  - Publish migration notes in `docs/` for all deprecated/removed contracts.

## Phased Delivery Plan

## Phase 0: Repository Scaffolding, CI/CD, Docker, Conventions

### Goals
- Establish a reproducible monorepo foundation and quality gates before feature work.

### Deliverables
- Monorepo directory skeleton (`backend/`, `frontend/`, `docker/`, `docs/`).
- Baseline Docker and `docker-compose` setup for local development.
- GitHub Actions workflows for backend, frontend, and Docker build verification.
- Shared coding standards and contribution conventions.

### Key Implementation Tasks
- Initialize backend Python project for 3.14+ with dependency management and lint/test/type scripts.
- Initialize frontend Vite + React + TypeScript with Tailwind, shadcn/ui base setup, eslint/prettier, and vitest (or Jest).
- Add root-level tooling docs and Makefile/task runner commands for consistent local workflows.
- Create `docker-compose.yml` with `api`, `web`, `db` and optional `oracle` profile.
- Add `.github/workflows/`:
  - Backend job: `ruff`, `pytest`, `mypy`.
  - Frontend job: `eslint`, `prettier --check`, `vitest` (or Jest).
  - Docker job: build all target images.
- Define branch/PR conventions, commit hygiene, and release tagging approach in `docs/`.

### Acceptance Criteria
- Clean clone can run lint/test/build through documented commands.
- CI runs on pull request and blocks merge on failing required jobs.
- `docker compose up` boots backend, frontend, and PostgreSQL successfully.
- Repository has clear onboarding and contribution instructions.

### Dependencies
- GitHub repository and Actions enabled.
- Container runtime available to development team.

### Primary Risks and Mitigations
- Risk: Early drift in coding standards.
  - Mitigation: Enforce all checks in CI, not just local hooks.
- Risk: Docker startup inconsistency across developer machines.
  - Mitigation: Pin base images and provide versioned env templates.

## Phase 1: Backend Foundation

### Goals
- Deliver the core FastAPI service skeleton with configuration, persistence, observability, and migration baseline.

### Deliverables
- FastAPI app structure with startup lifecycle, dependency injection boundaries, and health endpoints.
- Pydantic Settings configuration system with `.env` schema.
- Structured logging via Python logging + structlog.
- SQLAlchemy 2.0 models for app database and Alembic migration baseline.
- Database connectivity for PostgreSQL (asyncpg) and Oracle driver integration point.

### Key Implementation Tasks
- Implement app factory, router registration, middleware pipeline, and exception handling.
- Define settings classes (environment, secrets, database URLs, CORS, query timeouts, logging levels).
- Configure structlog JSON rendering and request correlation IDs.
- Model core tables: connections, auth methods, endpoints, schedules, job runs, cached snapshots, audit/access logs, settings.
- Initialize Alembic and create first migration for all foundational tables.
- Add readiness/liveness/DB health endpoints under `/api/v1/admin/health/*`.
- Establish repository/service layer patterns to control FastAPI DI complexity.

### Acceptance Criteria
- Service boots and passes lint, type-check, and unit tests.
- Alembic upgrade creates schema from empty database deterministically.
- Health endpoints validate app readiness and PostgreSQL connectivity.
- Logs are emitted as structured JSON with traceable request context.

### Dependencies
- Phase 0 complete.
- PostgreSQL service running.

### Primary Risks and Mitigations
- Risk: Poor boundary design leading to DI sprawl.
  - Mitigation: Enforce service/repository conventions and module templates early.
- Risk: Migration instability across environments.
  - Mitigation: Use migration checks in CI and test fresh + incremental upgrades.

## Phase 2: Module 1 - Connections End-to-End

### Goals
- Provide complete connection lifecycle management for Oracle sources.

### Deliverables
- Admin APIs and frontend screens for creating, editing, deleting, listing, and testing Oracle connections.
- Secure storage for credentials and pool configuration metadata.
- Connectivity test endpoint with diagnostic feedback.

### Key Implementation Tasks
- Implement connection entity validation (host/service/SID, username, pool sizing, timeouts).
- Encrypt sensitive fields at rest and manage keys via environment-based secret inputs.
- Build backend CRUD endpoints under `/api/v1/admin/connections/*`.
- Implement connection test workflow using `python-oracledb` (thin mode by default).
- Build frontend pages/forms/tables for connection management with validation and error feedback.
- Add audit logging for create/update/delete/test actions.

### Acceptance Criteria
- Users can create and test at least one Oracle connection successfully.
- Credentials are not returned in plain text from API responses or logs.
- Invalid connection configs return actionable validation errors.
- UI supports full CRUD flows and reflects backend state changes.

### Dependencies
- Phase 1 complete.
- Reachable Oracle instance for integration testing.

### Primary Risks and Mitigations
- Risk: Oracle environment differences causing false-negative tests.
  - Mitigation: Provide explicit thin/thick mode diagnostics and timeout controls.
- Risk: Credential leakage in logs.
  - Mitigation: Central redaction filter for sensitive fields.

## Phase 3: Module 3 - Auth Configuration End-to-End

### Goals
- Deliver configurable endpoint authentication using PyJWT + bcrypt.

### Deliverables
- Auth method CRUD for Bearer token, Basic Auth, API key.
- Token issuance/validation services with expiration and rotation settings.
- Middleware enforcing authentication on `/api/v1/data/*`.

### Key Implementation Tasks
- Implement auth models and schemas for all supported types.
- Build credential hashing and verification using `bcrypt`.
- Build JWT creation/validation utilities using `PyJWT`.
- Implement admin APIs under `/api/v1/admin/auth/*`.
- Add middleware/dependencies that resolve per-endpoint auth policy.
- Build frontend auth management screens and secure token display/regen UX.
- Add access logging with timestamp, IP, principal, endpoint, status.

### Acceptance Criteria
- Protected data endpoints reject unauthorized requests consistently.
- Valid credentials grant access according to configured endpoint policy.
- Token expiry and invalid signature cases are handled with deterministic responses.
- Auth management UI supports creation, update, disable, and revocation flows.

### Dependencies
- Phase 2 complete.

### Primary Risks and Mitigations
- Risk: Misconfigured auth policies exposing endpoints.
  - Mitigation: Default-deny policy and mandatory auth assignment before endpoint activation.
- Risk: Weak secret management.
  - Mitigation: Enforce minimum key lengths and reject insecure defaults.

## Phase 4: Module 2 - API Creation Wizard End-to-End

### Goals
- Deliver the core wizard that converts parameterized SQL into deployable versioned data endpoints.

### Deliverables
- Multi-step wizard UI and backend orchestration APIs.
- Rich SQL editor integration with CodeMirror 6 via `@uiw/react-codemirror`.
- SQL preview engine with bind parameter extraction/validation rules.
- Endpoint registration pipeline and dynamic data router.

### Key Implementation Tasks
- Build wizard flow state model and backend draft/publish lifecycle.
- Integrate SQL editor with syntax highlighting, lint/error markers, and shortcuts.
- Implement parameter binding contract:
  - Only named bind variables (e.g., `:param_name`).
  - Reject string-concatenated SQL interpolation patterns.
  - Validate input types/coercion using explicit schemas.
  - Treat preview samples as temporary values, never persisted defaults.
  - Enforce required descriptors for both live and snapshot requests regardless of defaults.
  - Keep optional live defaults independent from schedule-owned SQL bindings.
- Build preview execution endpoint to return sample JSON and inferred schema.
- Implement result mapping layer (rename/select columns and output shaping).
- Build endpoint definition step (path, GET method for MVP, auth method, data strategy).
- Register dynamic endpoint metadata and activate runtime resolution under `/api/v1/data/*`.
- Ensure router lookup is version-aware and supports deprecation metadata.

### Acceptance Criteria
- User can complete wizard and publish a functioning GET endpoint end-to-end.
- SQL preview enforces bind parameters and blocks unsafe query patterns.
- Published endpoint serves expected JSON for valid parameter inputs.
- Dynamic router resolves endpoint config without service restart.

### Dependencies
- Phase 2 and Phase 3 complete.

### Primary Risks and Mitigations
- Risk: SQL safety regressions.
  - Mitigation: Mandatory bind variable enforcement and explicit query validation layer.
- Risk: Complex wizard state causing inconsistent deployments.
  - Mitigation: Persist wizard drafts server-side with explicit state transitions.

## Phase 5: Module 4 - Scheduling + Snapshot Cache End-to-End

### Goals
- Enable scheduled data refresh with persisted definitions, restart restoration, and filtered
  cached response serving.

### Deliverables
- APScheduler 3.x integration with an in-memory job store whose active schedule definitions are
  persisted in PostgreSQL and restored on API startup.
- Schedule CRUD and control actions (run now, pause/resume, enable/disable).
- Snapshot cache storage in PostgreSQL JSONB.
- Job execution logging dashboard and APIs.

### Key Implementation Tasks
- Implement scheduler service lifecycle integrated with FastAPI startup/shutdown.
- Model schedules, job state, run history, and snapshot payload metadata.
- Implement admin APIs under `/api/v1/admin/schedules/*` and `/api/v1/admin/jobs/*`.
- Create execution worker logic for scheduled query runs and cache replacement strategy.
- Require schedule-owned parameter bindings, timezone-aware logical dates, and declarative
  calendar windows; persist resolved values for audit and coverage selection.
- Add staleness tracking and fallback handling when latest snapshot fails.
- Wire data endpoints in snapshot mode to require cached-column mappings, select the newest
  retained run that covers the request, and apply typed equality/range filters.
- Build frontend schedule management UI and execution log views.

### Acceptance Criteria
- Active scheduled jobs are restored exactly once after a single API process restarts.
- Manual run and pause/resume actions work reliably from UI and API.
- Snapshot-mode endpoints enforce required request parameters, reject requests outside retained
  coverage, return only filtered cached rows, and expose last-refresh metadata.
- Job logs capture start time, duration, row count, status, and error details.

### Dependencies
- Phase 4 complete.

### Primary Risks and Mitigations
- Risk: In-process scheduler contention under load.
  - Mitigation: Constrain job concurrency, isolate DB session handling, and monitor execution latency.
- Risk: Unbounded cache growth.
  - Mitigation: Define retention policy and periodic cleanup jobs.

## Phase 6: Module 5 - Settings + Health Dashboard End-to-End — COMPLETE

### Goals
- Provide centralized operational controls and health visibility.

### Deliverables
- Settings APIs and UI for base URL/port-related metadata, logging level, query timeout, CORS/rate-limit policy inputs.
- Health dashboard summarizing API, DB, Oracle connectivity probes, scheduler status, and recent job outcomes.

### Key Implementation Tasks
- Implement settings persistence model and validation constraints.
- Build admin APIs under `/api/v1/admin/settings/*`.
- Add runtime-safe application of mutable settings (where supported) and restart-required flags otherwise.
- Implement health aggregation service and dashboard widgets.
- Add alerts/flags for degraded dependencies and stale snapshots.

### Acceptance Criteria
- Settings can be viewed/updated with validation and audit trail.
- Health dashboard reflects real-time system state and recent scheduler outcomes.
- Misconfigurations surface clear diagnostics without exposing secrets.

### Dependencies
- Phase 5 complete.

### Primary Risks and Mitigations
- Risk: Runtime mutation causing inconsistent behavior.
  - Mitigation: Explicitly separate dynamic vs restart-required settings.
- Risk: Health indicators becoming noisy/unreliable.
  - Mitigation: Define probe intervals, timeout thresholds, and debounce rules.

## Phase 7: Integration Hardening (E2E, Security, Docs) — COMPLETE

### Goals
- Validate production readiness across module boundaries and security controls.

### Deliverables
- Cross-module integration and smoke E2E tests.
- Security validation checklist and remediation pass.
- Deployment and operations documentation for self-hosted environments.

### Key Implementation Tasks
- Build end-to-end smoke scenarios:
  - Create connection -> configure auth -> publish endpoint -> schedule snapshot -> consume `/api/v1/data/*`.
- Add negative-path security tests (invalid auth, SQL injection attempts, malformed parameters, rate-limit behavior).
- Validate migration upgrade path from baseline to latest.
- Add performance sanity tests for common query and snapshot paths.
- Finalize docs: architecture, API versioning/deprecation, setup, backup/restore, incident troubleshooting.

### Acceptance Criteria
- Critical E2E smoke suite passes in CI on clean environment.
- Security checklist items are verified with no unresolved high-severity findings.
- Deployment runbook enables first-time setup without tribal knowledge.

### Dependencies
- Phases 0-6 complete.

### Primary Risks and Mitigations
- Risk: Late integration defects across modules.
  - Mitigation: Gate each phase with integration tests and contract checks before advancing.
- Risk: Gaps between implementation and operational docs.
  - Mitigation: Documentation updates required in same PR as behavior changes.

## Testing Strategy

- Backend tests
  - Unit tests for services, validation logic, auth helpers, scheduler orchestration, and router resolution.
  - Integration tests for API routes, DB persistence, migrations, and Oracle query execution paths.
- Frontend tests
  - Component tests for forms, wizard step logic, validation states, and schedule controls.
  - Targeted integration tests for critical user flows in the admin SPA.
- End-to-end smoke tests
  - Minimal but mandatory flows covering publish-and-consume lifecycle and scheduled snapshot refresh.
- Test data and environments
  - Seed deterministic fixture data for PostgreSQL.
  - Use controlled Oracle test schema for repeatable query tests.

## CI/CD

GitHub Actions workflows will run on pull requests and protected branches with separate jobs:
- Backend job
  - Setup Python 3.14+
  - Install backend dependencies
  - Run `ruff`, `mypy`, `pytest`
- Frontend job
  - Setup Node LTS
  - Install frontend dependencies
  - Run `eslint`, `prettier --check`, `vitest` (or Jest)
- Docker job
  - Build backend and frontend images
  - Validate `docker-compose` build targets
- Optional gating enhancements
  - Migration check job (upgrade from empty DB)
  - E2E smoke job against compose environment for release branches

## Operational Readiness

- Environments and configuration
  - Use Pydantic Settings (Pydantic v2) as the canonical `.env` schema and configuration loader.
  - Maintain per-environment variable sets for local, test, staging, production.
  - Keep secrets out of code and inject via environment/secret manager.
- Logging and observability
  - Standardize structured JSON logs (structlog) across API, scheduler, and DB operations.
  - Include correlation IDs and principal identifiers for traceability.
  - Redact credentials, tokens, and sensitive payload fields at logger middleware level.
- Migrations and schema control
  - Alembic is mandatory from day one.
  - All app DB schema changes must be migration-driven and validated in CI.
- Backup and recovery notes
  - Define backup strategy for PostgreSQL metadata and cached snapshots.
  - Document restore procedure and verify restore drills at least in staging.
  - Keep migration and application version compatibility notes in release docs.
- Upgrade/versioning notes
  - Maintain API versioned namespaces from initial release (`/api/v1/admin/*`, `/api/v1/data/*`).
  - Use explicit deprecation notices and migration documentation for contract evolution.
  - Track dependency upgrade windows (Python, FastAPI, APScheduler, SQLAlchemy, frontend libs) with quarterly review cadence.
