# Backend Instructions (FastAPI)

## Do
- Use Python 3.14+ syntax and typing.
- Keep routes versioned under `/api/v1/admin/*` and `/api/v1/data/*`.
- Use Pydantic v2 models and Pydantic Settings for config.
- Use SQLAlchemy 2.0 patterns.
- Add Alembic migration for schema changes.
- Use `PyJWT` for token issuance/verification.
- Use `bcrypt` for hashing and verification.
- Emit structlog events with required fields.
- Validate SQL bind parameters via typed schemas before execution.
- Use SQLAlchemy `text()` and binds for user SQL.
- Enforce required HTTP parameters with `build_param_model(..., enforce_required=True)` for both
  live and snapshot data paths.
- Resolve scheduled SQL binds only from schedule-owned declarative bindings.
- Require complete snapshot filter mappings, prove retained-run coverage, and filter cached rows
  with the declared typed `eq`/`gte`/`lte` operators.

## Do Not
- Do not add unversioned API routes.
- Do not use `python-jose` or `passlib`.
- Do not interpolate SQL strings with user input.
- Do not treat quoted `':param'` text as a bind placeholder.
- Do not reuse endpoint defaults as implicit schedule inputs or serve an unfiltered parameterized
  snapshot.
- Do not edit old migration revisions after merge.
- Do not return secrets in API responses or logs.

## Migration Workflow
- Create: `cd backend && alembic revision --autogenerate -m "describe_change"`.
- Apply: `cd backend && alembic upgrade head`.
- Verify rollback path: `cd backend && alembic downgrade -1`.
- Re-apply: `cd backend && alembic upgrade head`.

## Backend Validation Commands
- `cd backend && ruff check .`
- `cd backend && mypy .`
- `cd backend && pytest`

## Logging Minimum Fields
- `request_id`
- `user`
- `endpoint`
- `status`
- `duration_ms`
- `method`
- `client_ip`
- `event`

## Stop Conditions
- Unsure data model: inspect models + Alembic history.
- Unsure route behavior: inspect existing `/api/v1` routers and tests.
- Ambiguous requirement: pause and ask; do not invent contracts.
