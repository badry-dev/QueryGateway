# Security Checklist

Comprehensive security validation for QueryGateway production deployments. All items must be verified before go-live.

## Authentication & Authorization

| # | Check | Status | Notes |
|---|-------|--------|-------|
| 1 | All data endpoints (`/api/v1/data/*`) enforce per-endpoint auth when configured | Verified | Auth method resolved per endpoint; unauthenticated requests rejected with 401 |
| 2 | Bearer JWT tokens verified against signing secret with expiry enforcement | Verified | PyJWT with HS256/384/512; expired tokens return 401 |
| 3 | Basic Auth credentials verified against bcrypt hash | Verified | bcrypt with random salt; timing-safe comparison |
| 4 | API keys verified against bcrypt hash | Verified | Key hash stored; plaintext shown only once on creation |
| 5 | Token rotation invalidates all previously issued tokens | Verified | New signing secret generated on rotation; old tokens fail verification |
| 6 | API key rotation invalidates old keys immediately | Verified | New key hash stored; old key fails bcrypt verification |
| 7 | Missing/empty credentials return 401 (not 500) | Verified | All three auth types handle missing credentials gracefully |
| 8 | Malformed credentials return 401 (not 500) | Verified | Base64 decode errors, invalid JWTs handled without stack traces |
| 9 | Default-deny: endpoints with unconfigured auth method return 401 | Verified | Inactive or missing auth method returns "Authentication configuration is unavailable" |

## Credential Storage

| # | Check | Status | Notes |
|---|-------|--------|-------|
| 10 | Oracle passwords encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256) | Verified | `encrypted_password` column stores ciphertext bytes |
| 11 | `encrypted_password` never returned in API responses | Verified | `ConnectionResponse` schema excludes the field |
| 12 | `has_password` boolean indicates credential presence without exposure | Verified | Safe indicator for UI |
| 13 | Bearer signing secrets encrypted with Fernet before `config_json` storage | Verified | Base64-encoded Fernet ciphertext in `signing_secret_enc` |
| 14 | Basic auth passwords stored as bcrypt hashes in `config_json` | Verified | `password_hash` field; plaintext never persisted |
| 15 | API key stored as bcrypt hash in `config_json` | Verified | `key_hash` field; plaintext shown once on creation only |
| 16 | `config_json` never returned in `AuthMethodResponse` | Verified | Schema explicitly excludes sensitive config fields |
| 17 | `ENCRYPTION_KEY` sourced from environment, not hardcoded | Verified | Pydantic Settings loads from `.env` or environment variables |

## SQL Injection Prevention

| # | Check | Status | Notes |
|---|-------|--------|-------|
| 18 | All user SQL uses named bind variables (`:param_name`) | Verified | `extract_bind_params()` extracts; `validate_sql_safety()` enforces |
| 19 | String concatenation patterns rejected (`' +`, `+ '`) | Verified | `_UNSAFE_PATTERNS` regex list in `schemas/endpoint.py` |
| 20 | PL/SQL concatenation rejected (`' ||`, `|| '`) | Verified | Pattern included in safety validation |
| 21 | Python f-string patterns rejected (`f"`, `f'`) | Verified | Pattern included in safety validation |
| 22 | Template interpolation rejected (`${`, `{var}`) | Verified | Pattern included in safety validation |
| 23 | SQL validation runs on both create and update | Verified | `EndpointCreate` and `EndpointUpdate` share the validator |
| 24 | SQL preview also validates before execution | Verified | `SqlPreviewRequest` includes the same validator |
| 25 | Parameters coerced through typed schemas before SQL execution | Verified | `_coerce_param()` with `ParamDescriptor` type validation |
| 26 | SQLAlchemy `text()` with bind dict used for execution | Verified | `sql/executor.py` uses parameterized execution |

## Input Validation

| # | Check | Status | Notes |
|---|-------|--------|-------|
| 27 | Endpoint paths validated with strict regex (lowercase alphanumeric, hyphens, underscores) | Verified | `_PATH_RE` rejects special characters, spaces, traversal patterns |
| 28 | Path traversal attempts blocked (`../`, `..\\`) | Verified | Regex rejects paths not matching `^[a-z0-9][a-z0-9\-_/]*$` |
| 29 | Invalid UUID path parameters return 422 (not 500) | Verified | FastAPI built-in UUID validation |
| 30 | Missing required fields return 422 with field-level detail | Verified | Pydantic validation errors surfaced |
| 31 | Invalid enum values rejected at schema level | Verified | `AuthMethodType`, `DataStrategy`, `ScheduleType` validated |
| 32 | String length limits enforced on all text fields | Verified | `max_length` constraints on name (255), description (1000), path (500) |

## Data Exposure

| # | Check | Status | Notes |
|---|-------|--------|-------|
| 33 | 500 errors return generic message, not stack traces | Verified | `unhandled_exception_handler` returns `{"detail": "Internal server error"}` |
| 34 | Validation errors do not leak internal schema details | Verified | Pydantic errors are structured but safe |
| 35 | Oracle connection strings not exposed in error responses | Verified | SQL execution errors logged server-side; generic message returned |
| 36 | Access logs record all data endpoint requests | Verified | `_write_access_log()` called on every code path in data router |
| 37 | Access logs include: path, method, principal, IP, status, duration, request_id | Verified | `AccessLog` model captures all audit fields |

## Transport Security

| # | Check | Status | Notes |
|---|-------|--------|-------|
| 38 | CORS configured and restrictable via `CORS_ORIGINS` setting | Verified | Default is `http://localhost:5173` (local dev), not `*`; list explicit origins in production. `allow_credentials=True`, so never set `CORS_ORIGINS=*` — the app now **refuses to boot** if `CORS_ORIGINS` contains `*` (M3, validated at startup) |
| 39 | `WWW-Authenticate` headers sent on 401 responses | Verified | Bearer and Basic auth return appropriate challenge headers |
| 40 | Request correlation IDs present in all structured logs | Verified | `RequestLoggingMiddleware` attaches `request_id` |

## Scheduler Security

| # | Check | Status | Notes |
|---|-------|--------|-------|
| 41 | Scheduled jobs use stored connection credentials (not request-time) | Verified | Job execution reads from encrypted DB records |
| 42 | Job execution errors logged but not exposed to data API consumers | Verified | Job run records stored internally; data endpoint returns 503 |
| 43 | Job concurrency limited to prevent resource exhaustion | Verified | `max_instances=1` per job, `max_job_concurrency` setting |
| 44 | Snapshot retention policy prevents unbounded storage growth | Verified | `snapshot_retention_count` setting with automatic cleanup |

## Deployment Security

| # | Check | Status | Notes |
|---|-------|--------|-------|
| 45 | `DEBUG=false` in production | Action Required | Verify `.env` configuration |
| 46 | `ENCRYPTION_KEY` in secrets manager, not version control | Action Required | Use environment injection or Kubernetes Secrets |
| 47 | `DATABASE_URL` credentials not logged | Verified | Pydantic Settings marks as secret type |
| 48 | HTTPS termination configured at reverse proxy | Action Required | Configure nginx/ALB/Cloudflare |
| 49 | PostgreSQL access restricted to application network | Action Required | Firewall/security group rules |
| 50 | Container images scanned for vulnerabilities | Verified | Trivy scans both images in CI (`docker.yml`), fails on fixable CRITICAL; per-image SPDX SBOMs generated with Syft |

## Application Hardening (audit findings M1, M3, L1–L5)

| # | Check | Status | Notes |
|---|-------|--------|-------|
| 51 | Every dynamic data endpoint requires authentication | Verified | A configured endpoint method is enforced when present. Otherwise the legacy `allow_unauthenticated=true` value opts into platform-admin Bearer fallback; it never permits anonymous access. Missing or invalid credentials return 401 and log `unauthenticated_endpoint_denied`. |
| 52 | App refuses to boot with wildcard CORS under credentials | Verified | M3: `cors_origins` validator rejects `*` at startup |
| 53 | API keys accepted only via header, not query string | Verified | L1: `X-Api-Key` only; `?api_key=` fallback removed |
| 54 | Sensitive keys redacted at the logging boundary | Verified | L2: structlog processor masks password/secret/token/api_key/key/authorization/signing_secret |
| 55 | Interactive API docs disabled in production | Verified | L3: `docs/redoc/openapi` URLs are `None` when `APP_ENV=production` |
| 56 | Password inputs bounded to bcrypt's 72-byte limit | Verified | L4: schema-level rejection (422) on admin login + basic-auth password |
| 57 | Constant-time username comparison in data-plane Basic auth | Verified | L5: `hmac.compare_digest` + always-run bcrypt in `verify_basic` |

## Supply-Chain Security (SECURITY.md §4.9)

| # | Check | Status | Notes |
|---|-------|--------|-------|
| 58 | Python deps hash-pinned; locked install | Verified | `requirements.lock` (uv `--generate-hashes`); `pip install --require-hashes` in CI + image |
| 59 | Backend/frontend vulnerability gates fail the build | Verified | `pip-audit` and `npm audit --audit-level=high`; weekly `osv-scanner` over the tree |
| 60 | npm install runs with `--ignore-scripts` | Verified | CI and `Dockerfile.frontend` (blocks install-time script execution) |
| 61 | GitHub Actions pinned to full commit SHA | Verified | All workflows; enforced by `scripts/check_action_pins.py` in `actions-lint.yml` |
| 62 | Dependabot + dependency-review + CODEOWNERS | Verified | `dependabot.yml` (pip/npm/docker/actions); SHA-pinned `dependency-review` PR gate; `CODEOWNERS` on manifests/lockfiles/workflows |
| 63 | Branch protection with required, non-bypassable checks | Action Required | Repo-admin only — settings documented in [repository_governance.md](repository_governance.md) |
| 64 | Container image signing + provenance | Action Required | Images scanned + SBOM'd, not yet signed (cosign/Sigstore) |

## Summary

- **Verified items**: 58/64
- **Action required**: 6/64
- **High-severity unresolved findings**: 0
- **All code-level security controls validated through automated tests**

The 6 "Action Required" items are environment/repo-admin configurations that
must be applied per installation: the original deployment-config items
(`DEBUG=false`, `ENCRYPTION_KEY` in a secrets manager, HTTPS termination,
PostgreSQL network isolation — see the [Deployment Runbook](deployment.md))
plus branch protection and image signing (#63–#64 — see
[repository_governance.md](repository_governance.md)).
