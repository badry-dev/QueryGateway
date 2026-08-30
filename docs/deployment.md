# Deployment Runbook

This document provides step-by-step deployment instructions for QueryGateway in self-hosted environments.

## Prerequisites

- **Python 3.14+** (backend runtime — `asyncpg` 0.31.0+ provides CPython 3.14 wheels)
- **Node.js 20 LTS** (frontend build)
- **PostgreSQL 16+** (application database)
- **Docker & Docker Compose** (recommended for production)
- **Oracle connectivity** (target database for data queries)
- Network access to the Oracle instance(s) you plan to query

## Environment Variables

Create a `.env` file from `.env.example` and configure:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string (`postgresql+asyncpg://user:pass@host:5432/db`) |
| `ENCRYPTION_KEY` | Yes | — | Fernet encryption key for credential storage (generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) |
| `APP_ENV` | No | `development` | Environment identifier (`development`, `staging`, `production`) |
| `DEBUG` | No | `false` | Enable debug mode (never `true` in production) |
| `LOG_LEVEL` | No | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `CORS_ORIGINS` | No | `*` | Comma-separated allowed CORS origins |

### Generating an Encryption Key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store this key securely. If the key is lost, all encrypted credentials (Oracle passwords, signing secrets) become unrecoverable.

## Deployment Options

### Option 1: Docker Compose (Recommended)

```bash
# Clone the repository
git clone <repo-url> && cd DB2API-Exposure

# Configure environment
cp .env.example .env
# Edit .env with your values

# Build and start all services. The one-shot `migrate` service runs
# Alembic before the API starts.
docker compose build
docker compose up -d

# Verify services are running
docker compose ps
curl http://localhost/api/v1/admin/health/live
curl http://localhost  # Frontend
```

For Oracle thick mode, set
`ORACLE_CLIENT_LIB_DIR=/opt/oracle/instantclient_19_32` in `.env`. The backend
image contains the pinned Linux x86-64 Instant Client and validates that its
native libraries load during the image build. Leave the variable blank for
thin mode.

**Services started:**
- `migrate` — one-shot Alembic migration runner
- `api` — FastAPI backend on the private Docker network
- `web` — React SPA (nginx) on host port 80
- `db` — PostgreSQL on port 5432

### Option 2: Bare Metal / VM

#### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

For production, use a process manager:

```bash
# Using gunicorn with uvicorn workers
pip install gunicorn
gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 1 \
  --bind 0.0.0.0:8000 \
  --access-logfile - \
  --error-logfile -
```

Keep exactly one API worker while APScheduler uses its in-process job store. Each worker restores active schedules during startup, so multiple workers or replicas would execute duplicate snapshot refreshes until distributed scheduler coordination is implemented.

#### Frontend Setup

```bash
cd frontend

# Install dependencies
npm ci

# Build for production
npm run build

# Serve the dist/ directory with nginx, caddy, or any static file server
```

**Nginx example config:**

```nginx
server {
    listen 80;
    server_name db2api.example.com;

    # Frontend SPA
    location / {
        root /path/to/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    # API proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### PostgreSQL Setup

```bash
# Create database and user
createuser db2api_user
createdb db2api_db -O db2api_user

# Or via psql
psql -c "CREATE USER db2api_user WITH PASSWORD 'your-password';"
psql -c "CREATE DATABASE db2api_db OWNER db2api_user;"
```

### Option 3: Kubernetes

Use the Docker images as a starting point. Key considerations:

- Deploy the API as a `Deployment` with `replicas: 1` while the scheduler is in-process
- Use a `Service` for internal routing and an `Ingress` for external access
- PostgreSQL: use a managed service (e.g., AWS RDS, GCP Cloud SQL) or a StatefulSet
- Store `ENCRYPTION_KEY` and `DATABASE_URL` as Kubernetes Secrets
- Configure liveness and readiness probes:

```yaml
livenessProbe:
  httpGet:
    path: /api/v1/admin/health/live
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /api/v1/admin/health/ready
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
```

## Database Migrations

Docker Compose runs migrations automatically via the `migrate` service before `api` starts. For bare-metal or VM deployments, migrations must be run before the first request:

```bash
# Docker-only migration run
docker compose up --build --force-recreate migrate
```

```bash
cd backend
alembic upgrade head
```

To verify current migration state:

```bash
alembic current
alembic history
```

To downgrade one step (for rollback):

```bash
alembic downgrade -1
```

## Health Probes

| Endpoint | Purpose | Expected Response |
|----------|---------|-------------------|
| `GET /api/v1/admin/health/live` | Liveness check | `{"status": "ok"}` |
| `GET /api/v1/admin/health/ready` | Readiness check (DB connectivity) | `{"status": "ok"}` |
| `GET /api/v1/admin/health/dashboard` | Full system dashboard | JSON with status, DB, scheduler, counts |

## Post-Deployment Verification

1. **Health check**: `curl http://localhost:8000/api/v1/admin/health/live`
2. **Database ready**: `curl http://localhost:8000/api/v1/admin/health/ready`
3. **Admin UI**: Open `http://localhost:3000` in a browser
4. **Create first connection**: Use the Connections page to add an Oracle data source
5. **Test connection**: Click "Test" to verify Oracle connectivity
6. **Create first endpoint**: Use the API Endpoints page wizard
7. **Verify data endpoint**: `curl http://localhost:8000/api/v1/data/<your-path>`

## Security Hardening for Production

- Set `DEBUG=false` and `APP_ENV=production`
- Restrict `CORS_ORIGINS` to your frontend domain(s)
- Use HTTPS termination (reverse proxy or load balancer)
- Rotate the `ENCRYPTION_KEY` via a secrets manager
- Enable firewall rules to restrict PostgreSQL access
- Review the [Security Checklist](security_checklist.md)

## Troubleshooting

See [Operations Guide](operations.md) for incident troubleshooting procedures.
