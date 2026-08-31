# Docker Instructions

## Do
- Keep Docker assets in `docker/`, `docker-compose.yml`, and `compose.production.yml`.
- Ensure compose supports `db`, one-shot `migrate`, `api`, and `web` services.
- Keep optional local Oracle service/profile isolated and documented.
- Use deterministic base image tags.
- Ensure backend and frontend images build in CI.

## Do Not
- Do not embed secrets in Dockerfiles or compose files.
- Do not couple local-only overrides into default production paths.
- Do not skip healthcheck/readiness wiring for service dependencies.

## Validation Commands
- `docker compose build`
- `docker compose up -d`
- `docker compose ps`
- `docker compose logs --tail=200 api`
- `docker compose logs --tail=200 web`
- `docker compose logs --tail=200 db`

## Runtime Expectations
- The `migrate` service starts after DB readiness and must complete successfully before the API
  starts.
- Migrations are applied deterministically with `alembic upgrade head`; do not add an independent
  API-startup migration path that can race the Compose service.
- Config comes from environment variables compatible with Pydantic Settings.

## Stop Conditions
- If container startup order fails, inspect healthchecks and dependency config before changing app code.
- If migration startup behavior is unclear, inspect migration entrypoint scripts and CI workflow.
