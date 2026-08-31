# Security Constraints for AI-Assisted Changes

## Hard Rules
- Never commit secrets, API keys, JWT signing keys, DB credentials, or private certs.
- Never log plaintext credentials or token bodies.
- Never bypass authentication for `/api/v1/data/*`.
- The legacy `allow_unauthenticated` field only opts into platform-admin Bearer authentication;
  it never authorizes anonymous data access.
- Never allow raw SQL string interpolation with user input.
- Never weaken token expiry validation.

## Auth Rules
- Use `bcrypt` for hashing only.
- Use `PyJWT` for JWT encode/decode only.
- Require `exp` claim and reject expired tokens.
- Keep signing keys in environment-managed settings.

## SQL and Data Safety
- Enforce `:param_name` bind style.
- Validate and coerce bind values through typed schemas.
- Reject unsafe query composition patterns.
- Never quote a bind placeholder inside a SQL string literal.
- Enforce required parameters on both live and snapshot requests, regardless of endpoint defaults.
- Scheduled execution must resolve every SQL bind from the schedule's own declarative bindings;
  never read endpoint request defaults at run time.
- Parameterized snapshots must prove coverage from persisted job-run parameters and apply typed,
  allowlisted cached-column filters before returning rows. Snapshot filters are not authorization.
- Prefer least-privilege Oracle credentials for query execution.

## Logging and Privacy
- Use structured logs with minimal necessary PII.
- Required fields: `request_id`, `user`, `endpoint`, `status`, `duration_ms`, `method`,
  `client_ip`, `event`.
- Redact secrets and high-risk fields at logging boundaries.

## Migration and Release Safety
- All schema changes via Alembic revisions.
- Never alter applied migration history.
- Document migration impact and rollback expectations in PR.

## Security Review Triggers
- Changes touching auth middleware.
- Changes touching SQL parsing/execution.
- Changes touching scheduler execution permissions.
- Changes introducing new environment variables or secret paths.
