# Development Conventions

## Branch and PR Rules

- Branch off `main` only.
- Branch naming: `feat/<scope>`, `fix/<scope>`, `chore/<scope>`, `docs/<scope>`.
- One logical change per PR; keep diffs small and reviewable.
- PR title must be imperative, ≤70 characters (e.g. "Add Oracle connection CRUD endpoints").
- Squash-merge into `main`; avoid merge commits.
- CI must be green before merge. Failing required jobs block the PR.

## Commit Hygiene

- Use the imperative mood in commit messages ("Add", "Fix", "Remove", not "Added", "Fixed").
- First line: ≤72 chars, no trailing period.
- Body: explain *why*, not *what*, when the change is non-obvious.
- Reference issues/PRs inline: `Closes #123`.

## Release Tagging

- Tags follow SemVer: `v<MAJOR>.<MINOR>.<PATCH>`.
- Tag only commits on `main`.
- A GitHub Release is created for each tag with a changelog entry.

## API Versioning

- All routes start with `/api/v1/admin/*` or `/api/v1/data/*`.
- Breaking changes require a new version path (`/api/v2/...`).
- Deprecated endpoints must carry a `Deprecation` response header and a `docs/` migration note.
- Maintain deprecated behavior for one full minor release cycle before removal.

## Database Migrations

- Every schema change needs an Alembic revision in the same PR.
- Never edit an already-applied migration file; add a new revision.
- Verify rollback: `alembic downgrade -1` must succeed in CI.
- Migration files must be committed alongside the model change.
- JSON contract extensions inside existing JSONB columns do not require a relational migration;
  document and test the API compatibility impact instead.

## Security Constraints

- Parameterize all user SQL with `:param_name` bind variables via SQLAlchemy `text()`.
- Never interpolate request values into SQL strings.
- Validate and coerce bind params through typed Pydantic schemas before execution.
- Hash passwords/credentials with `bcrypt` only; never MD5/SHA-x.
- Issue and verify JWTs with `PyJWT` only; always include `exp` and `iat` claims.
- Never store secrets in code, fixtures, tests, or docs. Use environment variables.
- Never return plaintext credentials or token bodies in API responses or logs.

## Parameter Contract

- Keep SQL preview samples, optional live-request defaults, schedule-owned bindings, and snapshot
  request filters as separate concepts.
- Required descriptors remain required for live and snapshot HTTP requests even if they contain a
  default.
- Schedules must bind every endpoint SQL parameter explicitly and must never read endpoint
  defaults during execution.
- Parameterized snapshot endpoints must map every request parameter to a final cached output
  column with `eq`, `gte`, or `lte`, prove retained-snapshot coverage, and filter cached rows.
- Snapshot filter mappings are row selection only; authorization belongs to the endpoint auth
  method.
- The canonical behavior and error codes live in
  [Endpoint, scheduler, and snapshot parameter contracts](scheduler_parameter_bindings.md).

## Logging Standards

- Use `structlog` for all structured JSON logging.
- Mandatory fields on every log event:
  - `request_id`, `user`, `endpoint`, `status`, `duration_ms`, `event`
- Scheduler events additionally require:
  - `job_id`, `run_id`, `row_count`, `success`
- Redact sensitive fields (passwords, tokens, Oracle credentials) at middleware level.

## Code Style

### Backend (Python)

- Python 3.14+ syntax and type annotations throughout.
- `ruff` enforces style and security linting (`ruff check .`).
- `mypy --strict` enforces type correctness.
- 100-character line limit.
- Sort imports with `ruff` (isort-compatible).

### Frontend (TypeScript)

- Strict TypeScript; no `any` unless absolutely necessary.
- `eslint` with `typescript-eslint` recommended rules.
- `prettier` for formatting (100-char print width, double quotes).
- Tailwind classes sorted by `prettier-plugin-tailwindcss`.

## Testing Requirements

- Backend: unit tests for services, auth, SQL validation, scheduler; integration tests for routes and DB.
- Frontend: component tests for all wizard steps, forms, and error states.
- Every PR with a behavior change must include or update tests.
- Test fixtures must not contain secrets.
- CI checks: `ruff`, `mypy`, `pytest` (backend); `eslint`, `prettier --check`, `vitest` (frontend); `docker compose build` (Docker).

## Naming Convention Policy

### Project Rename: DB2API-Exposure → QueryGateway

The project was formally renamed from **DB2API-Exposure** to **QueryGateway** in March 2026 to reflect its broader mission beyond Oracle databases. However, the following identifiers **intentionally remain unchanged** for operational stability:

#### Infrastructure Credentials (db2api)
- PostgreSQL username/password defaults
- Database names and connection strings
- These are internal configuration defaults, not public-facing identifiers
- Changing them would require migration scripts and environment variable updates across dev, test, and production
- **Action:** Update only if performing a full infrastructure refresh; document changes in deployment runbooks

#### API Key Prefix (db2api_)
- Generated API keys start with the `db2api_` prefix
- Part of the data model and cannot be changed for existing keys without migration
- A migration would orphan all existing production API keys
- **Action:** Preserve for backward compatibility; start issuing new keys with this prefix indefinitely

#### Documentation & Public Interfaces
- **All** user-facing documentation, UI components, API titles, and frontend branding → use **QueryGateway**
- These are updated continuously without infrastructure impact

This policy balances naming consistency (user visibility) with operational stability (internal systems).
