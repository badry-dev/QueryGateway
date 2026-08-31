# Testing Instructions

## Testing Policy
- Every behavior change must include or update tests.
- Backend changes require unit/integration coverage as appropriate.
- Frontend changes require component tests for affected UI.
- Critical path smoke checks must remain green.

## Required Check Commands
- Backend: `cd backend && ruff check . && mypy . && pytest`
- Frontend: `cd frontend && npm run eslint && npm run prettier:check && npm run test`
- Docker: `docker compose build`

## Backend Test Focus
- Auth validation with PyJWT and bcrypt flows.
- SQL bind parameter validation and rejection of unsafe SQL composition.
- Dynamic route resolution under `/api/v1/data/*`.
- Scheduler job creation/execution logging and snapshot cache behavior.
- Required-parameter enforcement for both live and snapshot requests, including supported date
  formats and optional SQL `NULL` behavior.
- Schedule binding completeness, logical-date/window resolution, retained-snapshot coverage,
  reversed ranges, mapped-column failures, and typed cached-row filtering.
- Alembic migration upgrade/downgrade sanity.

## Frontend Test Focus

- Wizard step transitions and validation.
- SQL editor integration behavior and parameter UX.
- Separation of preview samples, endpoint defaults, schedule bindings, and snapshot filter
  mappings in endpoint create/edit flows.
- Connection/auth/schedule/settings form validation.
- Error rendering for API failures.

## PR Gate Expectations
- CI jobs expected: backend (ruff/pytest/mypy), frontend (eslint/prettier/vitest or Jest), docker build.
- Failing checks block merge.
- Test snapshots or fixtures must not include secrets.

## Stop Conditions
- If tests conflict with API contract, inspect current `/api/v1` spec before changing tests.
- If schema-related tests fail unexpectedly, verify latest Alembic head and migration ordering.
