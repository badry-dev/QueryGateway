# Temporary Production Deployment Plan: Windows EC2 + WSL2 Ubuntu + Docker Engine

This document is a temporary deployment plan for running QueryGateway in production on the existing AWS EC2 Windows Server by using Ubuntu under WSL2 and Docker Engine inside WSL.

It is intentionally scoped to this single deployment path. After the deployment is complete and validated, remove this document from the repo and transfer the useful lessons into the permanent project documentation:

- `docs/deployment.md`
- `docs/operations.md`
- `docs/security_checklist.md`
- `README.md`, if platform support or quick-start guidance changes

No database schema or API contract changes are implied by this plan.

## Deployment Decision

Use the existing Windows EC2 server as the host, but run QueryGateway as Linux containers inside WSL2 Ubuntu using Docker Engine.

Do not deploy QueryGateway as native Windows containers. The current repo is built around Linux container images:

- Backend: `python:3.14-slim`
- Frontend build: `node:24-slim`
- Frontend runtime: `nginx:1.31-alpine`
- App database: `postgres:16-alpine`
- Optional Oracle XE: `gvenzl/oracle-xe:21-slim`

Do not base production on Docker Desktop on Windows Server. Docker Desktop is not the right production dependency for this server path, and Docker's Windows install guidance does not support Docker Desktop on Windows Server editions.

## Target Architecture

```text
Internet / approved client networks
  |
  v
AWS EC2 Security Group
  |
  v
Windows Server Firewall
  |
  v
Windows EC2 host
  |
  +-- WSL2 Ubuntu distribution
      |
      +-- Docker Engine
          |
          +-- querygateway Docker network
              |
              +-- web container
              |   - Nginx
              |   - serves React SPA
              |   - proxies /api/* to api:8000
              |   - only service published to host/public network
              |
              +-- api container
              |   - FastAPI/Uvicorn
              |   - private Docker-network service
              |   - executes Alembic migrations via one-shot command
              |
              +-- db container, temporary/simple option
                  - PostgreSQL 16
                  - private Docker-network service
                  - persisted in Docker volume
                  - backed up off-host

Outbound from API:
  - external APIs
  - Oracle database/listener, if configured
  - AWS services for logs/backups/secrets, if configured
```

Preferred public access:

- Use DNS pointing to the EC2 public IP or Elastic IP.
- Serve the app through HTTPS.
- Publish only `80` and/or `443` publicly.
- Keep `api:8000` and `db:5432` private.

## Key Assumptions

- The EC2 Windows Server already exists.
- WSL is already installed.
- Docker is already installed in WSL, or will be installed there.
- The initial deployment is single-host.
- The project will run from the WSL Linux filesystem, not from a mounted Windows path.
- PostgreSQL may initially run as a local Compose service, but production credentials and backup/restore must be handled before go-live.
- RDS can still be adopted later; this temporary plan does not require it.

## Non-Goals

- No native Windows container conversion.
- No Kubernetes/ECS migration.
- No permanent documentation restructure during the deployment attempt.
- No schema changes unless the app itself requires them through existing Alembic migrations.
- No new API endpoints or contract changes.

## WSL2 Host Layout

Use a Linux-native path inside WSL:

```bash
/opt/querygateway
```

Avoid these paths for the deployed repo and Docker bind-mounted runtime data:

```bash
/mnt/c/Users/...
/mnt/d/...
```

Reason: Docker, PostgreSQL, Node, Python tooling, file watchers, permissions, symlinks, and I/O behavior are more predictable when files live inside the WSL ext4 filesystem.

Recommended WSL filesystem layout:

```text
/opt/querygateway/              repo checkout
/opt/querygateway/.env          production environment file, not committed
/opt/querygateway/backups/      local staging area for database dumps
/var/lib/docker/                Docker Engine data root, managed by Docker
```

## Network And Port Plan

### Public Ports

| Port | Scope | Purpose | Recommendation |
| --- | --- | --- | --- |
| 443 | Public or approved client CIDRs | HTTPS access | Preferred production entry point. |
| 80 | Public or approved client CIDRs | HTTP redirect or temporary HTTP access | Allow only if needed. Redirect to HTTPS once TLS is configured. |
| 3389 | Admin IP/VPN only | Windows RDP | Restrict tightly. |

### Private Ports

| Port | Service | Recommendation |
| --- | --- | --- |
| 8000 | FastAPI backend | Do not publish publicly. Access through `web` proxy only. |
| 5432 | PostgreSQL | Do not publish publicly. Keep inside Docker network. |
| 1521 | Oracle listener | Only outbound to approved Oracle host unless running local Oracle test profile. |

### Security Group Rules

Inbound:

- Allow `443` from approved client networks.
- Allow `80` only for HTTP redirect or certificate challenge.
- Allow `3389` only from admin IPs or VPN.
- Do not allow `8000`.
- Do not allow `5432`.

Outbound:

- Allow HTTPS to required external APIs.
- Allow Oracle database/listener host and port if QueryGateway reads Oracle.
- Allow AWS APIs needed for backups, logs, secrets, and package/image pulls.

### Windows Firewall

Mirror the EC2 security group intent:

- Permit only the public app port(s).
- Permit RDP only from trusted admin networks.
- Do not create broad allow rules for Docker, WSL, Postgres, or the backend API.

WSL2 networking can differ by Windows version and configuration. During deployment, validate from outside the instance:

```powershell
Test-NetConnection <public-dns-or-ip> -Port 80
Test-NetConnection <public-dns-or-ip> -Port 443
```

From inside WSL:

```bash
curl -fsS http://localhost/api/v1/admin/health/live
curl -fsS http://localhost/api/v1/admin/health/ready
```

## TLS Plan

Production should use HTTPS.

Recommended for this temporary Windows + WSL deployment:

1. Start with HTTP on port `80` only long enough to validate routing.
2. Add TLS after the app is reachable.
3. Prefer one of these approaches:
   - AWS Application Load Balancer with ACM certificate in front of the Windows EC2 host.
   - Host-level reverse proxy with Let's Encrypt, if ALB is not available.
   - Caddy or Nginx running in Docker/WSL to terminate TLS.

If TLS terminates before the app container, ensure proxy headers are preserved:

```nginx
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

Update `CORS_ORIGINS` to the final HTTPS origin.

## Production Compose Strategy

Use the committed production override file rather than editing the development Compose file for the temporary deployment:

```text
compose.production.yml
```

Purpose:

- Set production environment.
- Remove public backend and database ports.
- Replace development database credentials.
- Configure production CORS.
- Override the PostgreSQL healthcheck to use the production database and user.
- Optionally configure logging.
- Optionally profile-gate the local database if an external database is used later.

The current template keeps `api`, `db`, and optional `oracle` off host ports. Only `web` is published, controlled by `PUBLIC_HTTP_PORT` in `.env`.

If TLS is terminated directly by a container, extend the `web` or proxy service to publish `443:443`.

## Production Environment File

Create `.env` on the WSL host from the committed production sample:

```bash
cd /opt/querygateway
cp .env.production.example .env
chmod 600 .env
```

Replace every placeholder before starting containers. Minimum production values:

```env
POSTGRES_DB=querygateway
POSTGRES_USER=querygateway_app
POSTGRES_PASSWORD=replace-with-strong-db-password

DATABASE_URL=postgresql+asyncpg://querygateway_app:replace-with-strong-db-password@db:5432/querygateway

APP_ENV=production
DEBUG=false
LOG_LEVEL=INFO
CORS_ORIGINS=https://querygateway.example.com

JWT_SECRET_KEY=replace-with-generated-secret
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60

ENCRYPTION_KEY=replace-with-generated-fernet-key

ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=replace-with-bcrypt-hash

QUERY_TIMEOUT_SECONDS=30
ORACLE_CLIENT_LIB_DIR=/opt/oracle/instantclient_19_32

PUBLIC_HTTP_PORT=80
```

Generate secrets inside WSL:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Generate the admin password hash from the backend environment:

```bash
cd /opt/querygateway/backend
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -c "from app.auth.hashing import hash_password; print(hash_password('replace-with-strong-password'))"
```

Important:

- Store `ENCRYPTION_KEY` in a secure external location.
- Losing `ENCRYPTION_KEY` makes encrypted Oracle credentials unrecoverable.
- Do not commit `.env`.
- Do not store plaintext admin passwords in the repo or deployment notes.

## Deployment Procedure

Run these commands inside WSL Ubuntu.

### 1. Prepare OS Packages

```bash
sudo apt update
sudo apt install -y git ca-certificates curl gnupg jq
```

If Docker Engine is not already installed in WSL, install Docker Engine and the Compose plugin following Docker's Ubuntu instructions.

Validate Docker:

```bash
docker version
docker compose version
docker run --rm hello-world
```

### 2. Clone Or Update The Repo

```bash
sudo mkdir -p /opt/querygateway
sudo chown "$USER":"$USER" /opt/querygateway
git clone <repo-url> /opt/querygateway
cd /opt/querygateway
```

If the repo is already cloned:

```bash
cd /opt/querygateway
git fetch --all --prune
git status
git pull --ff-only
```

### 3. Prepare Production Environment

The production override is committed as `compose.production.yml`. Do not edit the development defaults in `docker-compose.yml` for this deployment.

Create the server-only `.env` file from the production sample:

```bash
cd /opt/querygateway
cp .env.production.example .env
chmod 600 .env
```

Edit `.env` and replace every placeholder with production values:

- `POSTGRES_PASSWORD`
- `DATABASE_URL`
- `CORS_ORIGINS`
- `JWT_SECRET_KEY`
- `ENCRYPTION_KEY`
- `ADMIN_PASSWORD_HASH`
- `ORACLE_CLIENT_LIB_DIR`; use `/opt/oracle/instantclient_19_32` for thick mode
  with the client bundled in the backend image, or leave it blank for thin mode
- `PUBLIC_HTTP_PORT`, if not using host port `80`

Before continuing, validate the merged Compose config:

```bash
docker compose -f docker-compose.yml -f compose.production.yml config
```

### 4. Build Images

```bash
docker compose -f docker-compose.yml -f compose.production.yml build
```

### 5. Start Database First

If using the local `db` service:

```bash
docker compose -f docker-compose.yml -f compose.production.yml up -d db
docker compose -f docker-compose.yml -f compose.production.yml ps
```

Wait until the database is healthy.

### 6. Run Alembic Migrations

Migrations are required before serving production traffic. The current Compose file includes a one-shot `migrate` service and `api` waits for it to complete during `up`.

For a controlled preflight migration before starting the API, run:

```bash
docker compose -f docker-compose.yml -f compose.production.yml up --build --force-recreate migrate
```

### 7. Start Application

```bash
docker compose -f docker-compose.yml -f compose.production.yml up -d api web
docker compose -f docker-compose.yml -f compose.production.yml ps
```

### 8. Verify Locally Inside WSL

```bash
curl -fsS http://localhost/api/v1/admin/health/live
curl -fsS http://localhost/api/v1/admin/health/ready
```

Check logs:

```bash
docker compose -f docker-compose.yml -f compose.production.yml logs api --tail 100
docker compose -f docker-compose.yml -f compose.production.yml logs web --tail 100
```

### 9. Verify From Windows Host

From PowerShell on the Windows host:

```powershell
curl.exe -fsS http://localhost/api/v1/admin/health/live
curl.exe -fsS http://localhost/api/v1/admin/health/ready
```

### 10. Verify From Outside EC2

From an external machine:

```bash
curl -fsS http://<public-dns-or-ip>/api/v1/admin/health/live
```

After TLS:

```bash
curl -fsS https://<domain>/api/v1/admin/health/live
curl -fsS https://<domain>/api/v1/admin/health/ready
```

### 11. Verify Application Workflows

Before go-live:

- Open the admin UI through the public URL.
- Log in as the seeded admin.
- Create or verify one Oracle connection.
- Test the Oracle connection from the admin UI.
- Create or verify one endpoint.
- Attach authentication to the endpoint.
- Call one `/api/v1/data/*` route with valid credentials.
- Confirm unauthenticated calls fail for protected data routes.
- Confirm scheduler health if scheduled snapshots are used.

## Startup After Windows Reboot

Because this deployment depends on WSL and Docker inside WSL, reboot behavior must be tested.

Required checks after reboot:

```powershell
wsl -l -v
wsl -d Ubuntu -- bash -lc "docker ps"
wsl -d Ubuntu -- bash -lc "cd /opt/querygateway && docker compose -f docker-compose.yml -f compose.production.yml ps"
```

If Docker does not start automatically inside WSL, define a controlled startup procedure. Options include:

- A Windows Scheduled Task that starts WSL and runs a startup script.
- A documented manual restart procedure for the operations team.
- A service wrapper if already approved in this environment.

Example WSL startup script:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /opt/querygateway

if ! docker info >/dev/null 2>&1; then
  sudo service docker start
fi

docker compose -f docker-compose.yml -f compose.production.yml up -d
docker compose -f docker-compose.yml -f compose.production.yml ps
```

Store it as:

```text
/opt/querygateway/scripts/start-production.sh
```

Make it executable:

```bash
chmod +x /opt/querygateway/scripts/start-production.sh
```

Do not add this script to the repo unless it is generalized and reviewed for permanent documentation.

## Backup And Restore For Temporary Local PostgreSQL

If the deployment uses the local `db` Compose service, backups are mandatory.

### Backup Command

```bash
cd /opt/querygateway
mkdir -p backups
docker compose -f docker-compose.yml -f compose.production.yml exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c \
  > "backups/querygateway_$(date +%Y%m%d_%H%M%S).dump"
```

Then copy backups off-host, preferably to S3 or another managed backup location.

### Restore Drill

Before go-live, perform a restore into a temporary database or temporary environment and confirm:

- Backup file is readable.
- Restore command succeeds.
- App starts against restored database.
- Admin login works.
- Existing endpoint definitions and encrypted connection records are present.
- `ENCRYPTION_KEY` can decrypt saved credentials.

### Minimum Backup Policy

- Daily database dump.
- Off-host copy.
- At least 30 days retention unless policy says otherwise.
- Manual backup before every deployment.
- Manual backup before every migration.
- Secure backup of `.env` or equivalent secret store.

## Logging And Monitoring

Minimum temporary monitoring:

- Container health status:
  - `docker compose ps`
- API health:
  - `/api/v1/admin/health/live`
  - `/api/v1/admin/health/ready`
  - `/api/v1/admin/health/dashboard`
- API logs:
  - `docker compose logs api`
- Web logs:
  - `docker compose logs web`
- Database logs:
  - `docker compose logs db`
- Windows host disk, CPU, and memory.
- WSL disk usage.
- Docker volume disk usage.

Useful checks:

```bash
docker system df
df -h
free -h
docker compose -f docker-compose.yml -f compose.production.yml ps
docker compose -f docker-compose.yml -f compose.production.yml logs api --tail 200
```

Recommended improvement:

- Ship Docker logs to CloudWatch Logs or another central log system once the app is reachable.
- Alert on health endpoint failures, repeated 5xx, scheduler failures, and low disk.

## Project-Specific Production Gaps To Fix Before Go-Live

### 1. Review Production Templates

Current status:

- `compose.production.yml` is committed for the temporary WSL deployment.
- `.env.production.example` is committed as the production server template.
- The base `docker-compose.yml` still contains development defaults.

Go-live requirement:

- Use `docker-compose.yml` plus `compose.production.yml` together.
- Copy `.env.production.example` to `.env` on the server.
- Replace every placeholder in `.env`.
- Validate that the merged config keeps `api`, `db`, and optional `oracle` private.
- Keep the templates easy to remove or fold into permanent docs later.

### 2. Confirm Migrations Run

Current behavior:

- `docker-compose.yml` includes a one-shot `migrate` service.
- `api` depends on `migrate` completing successfully.

Go-live requirement:

```bash
docker compose -f docker-compose.yml -f compose.production.yml up --build --force-recreate migrate
```

Run this before starting the new app version if you want an explicit migration gate. Otherwise confirm the `migrate` service succeeds during `docker compose up -d`.

### 3. Replace Development PostgreSQL Credentials

Current gap:

- `POSTGRES_PASSWORD=db2api`
- `DATABASE_URL=postgresql+asyncpg://db2api:db2api@db:5432/db2api`

Go-live requirement:

- Use a strong production password.
- Use a production database name and user.
- Keep `5432` private.
- Back up the database before traffic.

### 4. Add HTTPS

Current gap:

- Current Nginx container listens on HTTP port `80`.

Go-live requirement:

- Configure HTTPS through ALB, Caddy, Nginx, or another approved reverse proxy.
- Redirect HTTP to HTTPS.
- Update `CORS_ORIGINS`.

### 5. Validate WSL Reboot Behavior

Current gap:

- WSL and Docker service startup after Windows reboot are not proven.

Go-live requirement:

- Reboot the EC2 instance before production cutover.
- Confirm WSL starts.
- Confirm Docker starts.
- Confirm containers restart.
- Confirm public health endpoint recovers without manual debugging.

### 6. Confirm WSL Network Exposure

Current gap:

- WSL2 networking can vary by Windows version and configuration.

Go-live requirement:

- Confirm `80` and `443` are reachable externally.
- Confirm `8000` and `5432` are not reachable externally.
- Confirm EC2 Security Group and Windows Firewall match the desired exposure.

### 7. Protect Data Endpoints

Current project rule:

- All data endpoints must require authentication.

Current behavior noted in README:

- Endpoints with no auth method attached are public.

Go-live requirement:

- Audit every active `/api/v1/data/*` endpoint.
- Confirm an auth method is attached.
- If production must technically prevent public data endpoints, add an enforcement change before go-live.

### 8. Generate And Store Production Secrets

Go-live requirement:

- Generate `JWT_SECRET_KEY`.
- Generate `ENCRYPTION_KEY`.
- Generate `ADMIN_PASSWORD_HASH`.
- Store secrets outside git.
- Back up `ENCRYPTION_KEY` securely.

### 9. Validate Oracle Connectivity From The EC2 Host

Go-live requirement:

- Test the Oracle connection from QueryGateway running inside WSL containers.
- Confirm outbound firewall/security group rules allow Oracle listener access.
- Confirm whether thin mode works.
- If thick mode is required, set
  `ORACLE_CLIENT_LIB_DIR=/opt/oracle/instantclient_19_32`. The backend image
  downloads the pinned Linux x86-64 Instant Client from Oracle and verifies its
  published SHA-256 during the build.

### 10. Keep One API Replica Initially

Current design consideration:

- APScheduler runs in-process.

Go-live requirement:

- Keep one `api` replica for the first deployment.
- Do not scale API replicas/workers until scheduler duplication risk is reviewed.

### 11. Configure Backups Before Real Data

Go-live requirement:

- Create a database backup before traffic.
- Store backup off-host.
- Test restore.
- Document retention.

### 12. Capture Deployment Learnings For Permanent Docs

Because this file is temporary, record the final tested facts during deployment:

- Exact Windows Server version.
- Exact WSL distro/version.
- Exact Docker Engine and Compose versions.
- Final public DNS/IP setup.
- Final port/firewall rules.
- Final TLS approach.
- Final Compose override.
- Final backup command and schedule.
- Final startup-after-reboot procedure.
- Any WSL-specific networking fixes.
- Any Oracle connectivity changes.

After deployment, move those facts into:

- `docs/deployment.md`
- `docs/operations.md`
- `docs/security_checklist.md`

Then remove this temporary document.

## Go-Live Checklist

- [ ] Repo deployed under WSL Linux path, for example `/opt/querygateway`.
- [ ] Docker Engine runs inside WSL.
- [ ] `docker compose version` verified inside WSL.
- [ ] Production `.env` created from `.env.production.example` on server and not committed.
- [ ] `compose.production.yml` present from the repo and reviewed.
- [ ] Merged Compose config validated.
- [ ] Production DB credentials set.
- [ ] `JWT_SECRET_KEY` generated.
- [ ] `ENCRYPTION_KEY` generated and backed up securely.
- [ ] `ADMIN_PASSWORD_HASH` generated with bcrypt.
- [ ] `APP_ENV=production`.
- [ ] `DEBUG=false`.
- [ ] `CORS_ORIGINS` set to the final public origin.
- [ ] `api:8000` is not publicly reachable.
- [ ] `db:5432` is not publicly reachable.
- [ ] EC2 Security Group exposes only required ports.
- [ ] Windows Firewall exposes only required ports.
- [ ] HTTPS configured or approved temporary HTTP exception documented.
- [ ] Alembic migrations run successfully.
- [ ] Containers healthy.
- [ ] Health endpoints pass inside WSL.
- [ ] Health endpoints pass from Windows host.
- [ ] Health endpoints pass externally.
- [ ] Admin login tested.
- [ ] Oracle connection tested from production deployment.
- [ ] One protected data endpoint tested.
- [ ] Unauthenticated data endpoint access rejected.
- [ ] Scheduler health checked if schedules are used.
- [ ] Backup created.
- [ ] Backup copied off-host.
- [ ] Restore tested.
- [ ] Windows reboot tested.
- [ ] WSL/Docker/container startup after reboot tested.
- [ ] Logs reviewed for secrets or credential leakage.
- [ ] Final deployment facts captured for permanent docs.

## Temporary Document Removal Plan

After the deployment is complete:

1. Review this document and mark which steps were actually used.
2. Copy the final tested WSL deployment procedure into `docs/deployment.md`.
3. Copy backup, restore, startup, monitoring, and troubleshooting details into `docs/operations.md`.
4. Copy go-live security checks into `docs/security_checklist.md`.
5. Update `README.md` only if platform support or quick-start wording needs to change.
6. Delete `docs/production_deployment.md`.

## References

- QueryGateway repo files:
  - `README.md`
  - `.env.production.example`
  - `docker-compose.yml`
  - `compose.production.yml`
  - `docker/Dockerfile.backend`
  - `docker/Dockerfile.frontend`
  - `docker/nginx.conf`
  - `docs/deployment.md`
  - `docs/operations.md`
  - `backend/app/config.py`
- Docker Desktop Windows install/support notes: https://docs.docker.com/desktop/setup/install/windows-install/
- Docker Engine on Ubuntu: https://docs.docker.com/engine/install/ubuntu/
- Docker Compose production guidance: https://docs.docker.com/compose/how-tos/production/
- Microsoft WSL documentation: https://learn.microsoft.com/en-us/windows/wsl/
- AWS EC2 security groups: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-security-groups.html
- AWS Elastic IP addresses: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/elastic-ip-addresses-eip.html
