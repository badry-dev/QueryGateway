# Human + Agent Workflow Playbook

## Branch Strategy
- Use short-lived feature branches from `main`.
- Branch naming: `feat/<scope>`, `fix/<scope>`, `chore/<scope>`.
- One logical change per PR.

## How to Ask for Changes (Human -> Agent)
- Provide target area: backend, frontend, docker, docs, or cross-cutting.
- Provide expected outcome and acceptance checks.
- State whether schema/API contract change is allowed.
- State whether migration/version bump is expected.

## Agent Operating Procedure
1. Before editing: scan related files, summarize intent, list commands to run.
2. Implement minimal scoped changes.
3. If schema changes: add Alembic revision.
4. If API changes: preserve `/api/v1/*` compatibility or add version bump.
5. After editing: run lint/tests/build for touched areas.
6. Update docs/changelog notes when behavior or contract changes.
7. For parameter behavior, keep preview samples, endpoint request defaults, schedule bindings,
   and snapshot request filters separate; verify the canonical contract in
   `docs/scheduler_parameter_bindings.md`.

## Verification Checklist
- Backend checks pass: `ruff`, `mypy`, `pytest`.
- Frontend checks pass: `eslint`, `prettier:check`, `vitest`/`Jest`.
- Docker build passes: `docker compose build`.
- Migrations included for DB changes.
- No secrets in code, logs, tests, or docs.
- No breaking API change without explicit versioning plan.
- Required live/snapshot parameters remain enforced and parameterized snapshots cannot fall back
  to unfiltered cached data.

## PR Checklist
- Scope is clear and minimal.
- Tests added/updated.
- Migration included if needed.
- Docs updated.
- Security constraints respected.
- CI green across backend, frontend, and docker jobs.

## Stop Conditions
- Unsure schema intent: inspect models + migrations first.
- Unclear API contract: inspect `/api/v1` routes/spec first.
- Ambiguous requirement: ask clarifying question; do not invent endpoints.

## Merge Criteria
- Reviewer can run listed commands and reproduce pass state.
- Contract changes are versioned and documented.
- Operational impact (env vars, migration steps, docker changes) is explicitly documented.
