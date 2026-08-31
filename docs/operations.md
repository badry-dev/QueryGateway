# Operations Guide

Backup, restore, monitoring, and incident troubleshooting procedures for QueryGateway.

## Backup Procedures

### PostgreSQL Database Backup

The PostgreSQL database stores all application state: connections, auth methods, endpoints, schedules, job runs, snapshots, settings, and access logs.

**Full backup (recommended daily):**

```bash
# Plain SQL dump (portable, human-readable)
pg_dump -h localhost -U db2api_user -d db2api_db -F p -f backup_$(date +%Y%m%d).sql

# Custom format (compressed, supports parallel restore)
pg_dump -h localhost -U db2api_user -d db2api_db -F c -f backup_$(date +%Y%m%d).dump
```

**Docker environment:**

```bash
docker compose exec db pg_dump -U postgres db2api_db -F c -f /tmp/backup.dump
docker compose cp db:/tmp/backup.dump ./backup_$(date +%Y%m%d).dump
```

**Automated backup script:**

```bash
#!/bin/bash
# cron: 0 2 * * * /opt/db2api/backup.sh
BACKUP_DIR="/opt/db2api/backups"
RETENTION_DAYS=30
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

pg_dump -h localhost -U db2api_user -d db2api_db -F c \
  -f "${BACKUP_DIR}/db2api_${TIMESTAMP}.dump"

# Remove backups older than retention period
find "${BACKUP_DIR}" -name "db2api_*.dump" -mtime +${RETENTION_DAYS} -delete
```

### What to Backup

| Component | Backup Method | Frequency |
|-----------|--------------|-----------|
| PostgreSQL database | `pg_dump` | Daily |
| `.env` file | File copy | On change |
| `ENCRYPTION_KEY` | Secrets manager | On creation |
| Docker volumes | Volume backup | Weekly |

### What NOT to Backup

- Application code (stored in git)
- npm/pip packages (recreatable from lock files)
- Log files (ephemeral, stored externally if needed)

## Restore Procedures

### Full Database Restore

```bash
# Stop the application
docker compose stop api

# Drop and recreate the database
psql -h localhost -U postgres -c "DROP DATABASE IF EXISTS db2api_db;"
psql -h localhost -U postgres -c "CREATE DATABASE db2api_db OWNER db2api_user;"

# Restore from backup
pg_restore -h localhost -U db2api_user -d db2api_db backup_file.dump

# Or for plain SQL dumps:
psql -h localhost -U db2api_user -d db2api_db < backup_file.sql

# Restart the application
docker compose start api
```

### Point-in-Time Recovery

For production environments, enable PostgreSQL WAL archiving:

```
# postgresql.conf
wal_level = replica
archive_mode = on
archive_command = 'cp %p /archive/%f'
```

### Encryption Key Recovery

If the `ENCRYPTION_KEY` is lost:

1. **All encrypted credentials are unrecoverable** (Oracle passwords, signing secrets)
2. Generate a new key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
3. Re-enter all Oracle connection passwords through the admin UI
4. Rotate all bearer auth signing secrets (existing tokens will be invalid)
5. Rotate all API keys

## Monitoring

### Health Endpoints

Use the built-in health endpoints for monitoring:

```bash
# Liveness probe — process is running
curl -s http://localhost:8000/api/v1/admin/health/live | jq .

# Readiness probe — database is connected
curl -s http://localhost:8000/api/v1/admin/health/ready | jq .

# Full dashboard — all components
curl -s http://localhost:8000/api/v1/admin/health/dashboard | jq .
```

### Dashboard Response Fields

| Field | Meaning |
|-------|---------|
| `status` | `ok` or `degraded` |
| `database.ok` | PostgreSQL connectivity |
| `scheduler.running` | APScheduler is active |
| `scheduler.job_count` | Number of registered jobs |
| `recent_jobs.total` | Jobs run in last 24h |
| `recent_jobs.success_rate` | Percentage of successful jobs |
| `stale_snapshots` | Endpoints with outdated cached data |
| `connections.total` / `.active` | Connection counts |
| `endpoints.total` / `.active` | Endpoint counts |

### Alert Triggers

Set up alerts for:

| Condition | Severity | Action |
|-----------|----------|--------|
| `/health/live` returns non-200 | Critical | Restart the service |
| `/health/ready` returns non-200 | High | Check PostgreSQL connectivity |
| `status == "degraded"` | Medium | Investigate stale snapshots or DB issues |
| `recent_jobs.success_rate < 90%` | Medium | Check job logs and Oracle connectivity |
| `stale_snapshots` list is non-empty | Low | Verify schedule configuration |

### Log Analysis

Logs are emitted as structured JSON via structlog. Key fields:

| Field | Description |
|-------|-------------|
| `request_id` | Unique request correlation ID |
| `event` | Log event name |
| `user` | Authenticated principal |
| `endpoint` | API path |
| `status` | HTTP status code |
| `duration_ms` | Request duration |
| `method` | HTTP method |
| `client_ip` | Request source after trusted-proxy resolution |
| `job_id` | Scheduler job identifier |
| `run_id` | Job run identifier |
| `row_count` | Query result row count |

**Common log queries (using jq):**

```bash
# Failed requests
cat app.log | jq 'select(.status >= 400)'

# Slow queries (>5s)
cat app.log | jq 'select(.duration_ms > 5000)'

# Failed scheduler jobs
cat app.log | jq 'select(.event == "job_execution_failed")'

# Auth failures
cat app.log | jq 'select(.status == 401)'
```

## Incident Troubleshooting

### Service Won't Start

1. **Check environment variables**: Ensure `DATABASE_URL`, `ENCRYPTION_KEY`, and
   `JWT_SECRET_KEY` are set and valid
2. **Check PostgreSQL**: `pg_isready -h localhost`
3. **Check migrations**: `alembic current` should show the latest revision
4. **Check logs**: Look for startup errors in container logs
5. **Port conflicts**: Ensure ports 8000 and 5432 are available

```bash
docker compose logs api --tail 50
```

### Database Connection Failures

1. **Verify PostgreSQL is running**: `pg_isready -h localhost -p 5432`
2. **Check credentials**: Verify `DATABASE_URL` in `.env`
3. **Check network**: Ensure the API container can reach the database
4. **Check connection limits**: `SELECT count(*) FROM pg_stat_activity;`

### Oracle Query Failures

1. **Test connection**: Use the admin UI "Test" button or:
   ```bash
   curl -X POST http://localhost:8000/api/v1/admin/connections/{id}/test
   ```
2. **Check Oracle logs**: Look for ORA-XXXXX error codes
3. **Common issues**:
   - `ORA-12541`: Oracle listener not running
   - `ORA-12514`: Unknown service name
   - `ORA-01017`: Invalid credentials
   - `ORA-02396`: Query timeout exceeded
4. **Network issues**: Verify firewall rules between the API host and Oracle

### Scheduler Issues

1. **Check scheduler status**: `GET /api/v1/admin/health/dashboard` → `scheduler.running`
2. **View recent job runs**: `GET /api/v1/admin/schedules/jobs/?limit=10`
3. **Check for stale snapshots**: `GET /api/v1/admin/health/dashboard` → `stale_snapshots`
4. **Common causes**:
   - Oracle connection timeout
   - Large result set exceeding memory
   - Concurrent job limit reached
   - A missing or extra schedule parameter binding
   - A date window source without a configured window preset
   - An invalid IANA timezone or a logical-date replay outside the intended business calendar

Use `POST /api/v1/admin/schedules/preview` with the proposed timing and binding payload to inspect
the next resolved logical dates and typed SQL values before saving a schedule.

### Auth Token Issues

1. **Expired tokens**: Tokens have a configurable TTL; re-issue via admin UI
2. **Invalid tokens after rotation**: Expected behavior — old tokens are invalidated
3. **Missing auth header**: Ensure `Authorization: Bearer <token>` is set
4. **Wrong auth type**: Verify the endpoint's auth method type matches the credentials

### Data Endpoint Returns Unexpected Results

1. **Check endpoint config**: `GET /api/v1/admin/endpoints/{id}`
2. **Verify parameters**: Required parameters must be present in the query string for both live
   and snapshot requests. Endpoint defaults do not satisfy a missing required HTTP value.
3. **Check parameter ownership**: Preview samples are temporary, live defaults apply only to
   omitted optional requests, and schedule execution uses the schedule's own bindings.
4. **Check snapshot mappings and error codes**:
   - Snapshot endpoints require a cached-column mapping for every request parameter.
   - The mapped name is the final output name after `column_map_json` renaming.
   - `snapshot_filter_not_configured` means an older endpoint must be updated in the endpoint edit
     dialog or admin API.
   - `invalid_parameter_range` means a lower request bound is later than its upper bound.
   - `snapshot_out_of_coverage` means no retained job run covers the complete request; inspect
     schedule bindings, window, timezone, and snapshot retention.
   - `snapshot_filter_column_unavailable` means a configured mapped column is absent from the
     non-empty cached payload.
   - A covered request with no matching business rows is successful and returns `data: []`.
   - No retained snapshot returns HTTP 503 rather than a coverage error.
5. **Check snapshot staleness**: For snapshot endpoints, compare `snapshot_created_at`,
   `snapshot_row_count`, and the filtered `row_count` response metadata.
6. **Check SQL syntax**: Use the SQL preview feature with temporary sample values. Ensure bind
   placeholders are not enclosed in single quotes.

See [Endpoint, scheduler, and snapshot parameter contracts](scheduler_parameter_bindings.md) for
the complete selection and coverage rules.

### Schedule and Endpoint Deletion

- Deleting a schedule unregisters the in-memory job after the database commit and preserves its
  immutable job-run history. Historical `schedule_id` values become `NULL`; retained snapshots
  continue to reference their job runs.
- Deleting an endpoint cascades its active schedule and cached snapshots, unregisters the schedule
  job, and preserves historical job runs with nullable endpoint/schedule references.
- Back up PostgreSQL before bulk deletion when job-run audit history or cached payloads are part of
  an operational retention requirement.

## Upgrade Procedures

### Application Upgrade

```bash
# Pull latest code
git pull origin main

# Rebuild and restart. The one-shot `migrate` service applies Alembic
# migrations before the API starts.
docker compose up -d --build
```

### Database Upgrade

Docker Compose runs migrations automatically through the `migrate` service before the API starts. For non-Docker deployments, run migrations before starting the new application version:

```bash
# Docker-only migration run
docker compose up --build --force-recreate migrate
```

```bash
# 1. Backup first
pg_dump -F c -f pre_upgrade_backup.dump

# 2. Run migrations
cd backend && alembic upgrade head

# 3. Verify
alembic current
```

### Rollback Procedure

```bash
# 1. Stop the application
docker compose stop api

# 2. Downgrade migration (if needed)
cd backend && alembic downgrade -1

# 3. Restore previous application version
git checkout <previous-tag>

# 4. Restart
docker compose start api
```

## Performance Tuning

### Backend

| Setting | Default | Production Recommendation |
|---------|---------|--------------------------|
| `query_timeout_seconds` | 30 | Adjust per use case (5-120s) |
| `max_job_concurrency` | 3 | 5-10 depending on Oracle capacity |
| `snapshot_retention_count` | 5 | 3-10 depending on data size |
| Uvicorn workers | 1 | 2-4x CPU cores |

### PostgreSQL

```sql
-- Recommended for production
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET work_mem = '16MB';
ALTER SYSTEM SET maintenance_work_mem = '128MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
```

### Oracle Connection Pool

Configure connection pool settings per Oracle data source:

| Setting | Default | Recommendation |
|---------|---------|---------------|
| `pool_min` | 1 | 2-5 |
| `pool_max` | 5 | 10-20 |
| `pool_timeout` | 30 | 30-60 |
| `query_timeout` | 30 | Adjust per query complexity |
