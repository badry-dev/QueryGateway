# Phase 2 — Multi-Database Connection Support

## Overview

Extend QueryGateway from Oracle-only to a multi-database platform. Users will be able to register connections to different database engines, test them, and expose SQL queries as REST endpoints — exactly as today, but engine-agnostic.

## Current compatibility baseline

Any future database adapter must preserve the current v1 parameter behavior:

- unquoted named binds, typed validation, and required-parameter enforcement for live and snapshot
  requests;
- separation of temporary preview samples, optional live defaults, and schedule-owned bindings;
- timezone-aware logical schedule dates and declarative date windows; and
- complete snapshot mappings, persisted-run coverage checks, and typed cached-row filtering before
  data is returned.

The canonical behavior is documented in
[Endpoint, scheduler, and snapshot parameter contracts](scheduler_parameter_bindings.md). Engine
adapters may translate bind syntax internally only after validation; they must not introduce raw
string interpolation or weaken the public `/api/v1` contract.

---

## Proposed Database Types

### Phase 2 (this document)
| DB Type | Driver | Notes |
|---------|--------|-------|
| PostgreSQL | `asyncpg` (already a dependency) | Most natural first addition — app DB already runs on it |
| MySQL / MariaDB | `aiomysql` | Wide enterprise usage |
| SQLite | `aiosqlite` (stdlib fallback available) | Zero-setup; great for dev/testing and embedded use cases |

### Phase 3 (deferred)
| DB Type | Driver | Rationale |
|---------|--------|-----------|
| Microsoft SQL Server | `pyodbc` + ODBC driver | Dominant in enterprise Windows environments |
| DBF (dBase/FoxPro) | `dbfread` | File-based; server-side path access |
| IBM Db2 | `ibm_db` | Legacy enterprise environments |
| Snowflake | `snowflake-connector-python` | Popular cloud data warehouse |
| BigQuery | `google-cloud-bigquery` | Google Cloud analytics platform |
| Redshift | `redshift_connector` or `psycopg2` | AWS analytics; PostgreSQL-compatible dialect |

---

## Architecture Plan

### Strategy: Discriminated Union with Per-Type Extension

Rather than creating completely separate tables and code paths for each DB, we use a **single `connections` table with a `db_type` discriminator column** and JSON/nullable extension columns for type-specific settings. This keeps the model simple and the repository/routes unchanged.

---

## Backend Changes

### 1. Database Migration

Add a new Alembic revision:

```sql
-- Add db_type enum
CREATE TYPE db_type AS ENUM ('oracle', 'postgresql', 'mysql', 'sqlserver', 'sqlite', 'dbf');

-- Add db_type column (nullable during migration, then backfill to 'oracle', then NOT NULL)
ALTER TABLE connections ADD COLUMN db_type db_type NOT NULL DEFAULT 'oracle';

-- DBF/SQLite need a file path, not a host
ALTER TABLE connections ALTER COLUMN host DROP NOT NULL;  -- make host nullable
ALTER TABLE connections ADD COLUMN file_path VARCHAR(1024);  -- for DBF/SQLite
ALTER TABLE connections ALTER COLUMN username DROP NOT NULL;  -- optional for SQLite/DBF
ALTER TABLE connections ADD COLUMN extra_params JSONB;  -- driver-specific options (charset, sslmode, etc.)
```

Files to create:
- `backend/alembic/versions/0002_add_db_type_multi_database.py`

---

### 2. Connection Model

**File:** `backend/app/models/connection.py`

Add fields:
- `db_type: Mapped[DbType]` — new enum column with default `oracle`
- `file_path: Mapped[str | None]` — for SQLite/DBF
- `extra_params: Mapped[dict | None]` — JSONB for driver-specific options (charset, ssl_mode, application_name, etc.)
- Make `host` and `username` nullable (SQLite/DBF don't need them)

Keep existing Oracle fields (`service_name`, `sid`, `mode`) — they remain valid for Oracle rows; NULL for all other types.

---

### 3. Pydantic Schemas

**File:** `backend/app/schemas/connection.py`

Replace the single schema with a discriminated-union approach:

```python
class DbType(str, Enum):
    oracle = "oracle"
    postgresql = "postgresql"
    mysql = "mysql"
    sqlserver = "sqlserver"
    sqlite = "sqlite"
    dbf = "dbf"

class ConnectionBase(BaseModel):
    """Fields common to all DB types."""
    name: str
    description: str | None
    db_type: DbType
    is_active: bool = True
    query_timeout: int = 30

class OracleConnectionFields(ConnectionBase):
    db_type: Literal[DbType.oracle] = DbType.oracle
    host: str
    port: int = 1521
    service_name: str | None
    sid: str | None
    username: str
    mode: OracleMode = OracleMode.thin
    pool_min: int = 1
    pool_max: int = 5
    pool_timeout: int = 30

class PostgresConnectionFields(ConnectionBase):
    db_type: Literal[DbType.postgresql] = DbType.postgresql
    host: str
    port: int = 5432
    database: str          # stored in service_name column
    username: str
    sslmode: str = "prefer" # stored in extra_params

class MySQLConnectionFields(ConnectionBase):
    db_type: Literal[DbType.mysql] = DbType.mysql
    host: str
    port: int = 3306
    database: str
    username: str
    charset: str = "utf8mb4"

class SqlServerConnectionFields(ConnectionBase):
    db_type: Literal[DbType.sqlserver] = DbType.sqlserver
    host: str
    port: int = 1433
    database: str
    username: str
    driver: str = "ODBC Driver 17 for SQL Server"

class SqliteConnectionFields(ConnectionBase):
    db_type: Literal[DbType.sqlite] = DbType.sqlite
    file_path: str         # absolute path to .db file

class DbfConnectionFields(ConnectionBase):
    db_type: Literal[DbType.dbf] = DbType.dbf
    file_path: str         # path to directory containing .dbf files

# Discriminated union used in API
ConnectionCreate = Annotated[
    OracleConnectionFields | PostgresConnectionFields | ...,
    Field(discriminator="db_type")
]
```

Response schema adds `db_type` and exposes only relevant fields.

---

### 4. SQL Executor — Pluggable Driver Architecture

**File:** `backend/app/sql/executor.py`

Refactor into a dispatcher pattern:

```python
async def execute_query(
    connection: OracleConnection,   # rename to Connection
    sql: str,
    params: dict[str, object],
    max_rows: int = 1000,
) -> tuple[list[str], list[dict], float]:
    match connection.db_type:
        case DbType.oracle:
            return await _execute_oracle(connection, sql, params, max_rows)
        case DbType.postgresql:
            return await _execute_postgres(connection, sql, params, max_rows)
        case DbType.mysql:
            return await _execute_mysql(connection, sql, params, max_rows)
        ...
```

Each `_execute_*` function handles:
- Password decryption (shared via `decrypt_password()`)
- DSN/connection string construction
- Driver import and connection setup
- Parameterized query execution
- Row → dict mapping
- Timeout enforcement

---

### 5. Connection Service — Test Connectivity

**File:** `backend/app/services/connection.py`

The `test_connection()` method gets a similar dispatch:

```python
match obj.db_type:
    case DbType.oracle:   return await _test_oracle(obj, ...)
    case DbType.postgresql: return await _test_postgres(obj, ...)
    ...
```

Each probe runs a type-appropriate version query:
- Oracle: `SELECT banner FROM v$version WHERE rownum = 1`
- PostgreSQL: `SELECT version()`
- MySQL: `SELECT version()`
- SQL Server: `SELECT @@VERSION`
- SQLite: `SELECT sqlite_version()`
- DBF: File existence + readable check

---

### 6. Requirements

New optional dependencies (added to `requirements-extra.txt` or separate files):

```
# PostgreSQL (already in requirements.txt as app DB)
asyncpg>=0.31.0

# MySQL
aiomysql>=0.2.0

# SQL Server (requires ODBC driver installed on OS)
pyodbc>=5.0.0

# SQLite (stdlib, no install needed)
# aiosqlite>=0.19.0  # optional for async

# DBF
dbfread>=2.0.7
```

---

## Frontend Changes

### 1. DB Type Selector

**File:** `frontend/src/components/connections/ConnectionForm.tsx`

Add a `DbType` selector at the top of the form. When the user selects a DB type, the fields below update to show only relevant fields:

| Field | Oracle | PostgreSQL | MySQL | SQL Server | SQLite | DBF |
|-------|--------|-----------|-------|-----------|--------|-----|
| Host | ✓ | ✓ | ✓ | ✓ | — | — |
| Port | ✓ | ✓ | ✓ | ✓ | — | — |
| Database/Service | service_name/SID | database | database | database | — | — |
| Username | ✓ | ✓ | ✓ | ✓ | — | — |
| Password | ✓ | ✓ | ✓ | ✓ | — | — |
| File Path | — | — | — | — | ✓ | ✓ |
| Mode (thin/thick) | ✓ | — | — | — | — | — |
| Pool settings | ✓ | ✓ | ✓ | — | — | — |
| Extra options | — | sslmode | charset | ODBC driver | — | — |

### 2. Type Definitions

**File:** `frontend/src/types/connection.ts`

Add `DbType` enum and per-type discriminated union interfaces:

```typescript
export type DbType = "oracle" | "postgresql" | "mysql" | "sqlserver" | "sqlite" | "dbf"

export interface ConnectionBase {
  id: string
  name: string
  db_type: DbType
  description?: string
  is_active: boolean
  query_timeout: number
  created_at: string
  updated_at: string
}

export interface OracleConnection extends ConnectionBase {
  db_type: "oracle"
  host: string
  port: number
  service_name?: string
  sid?: string
  username: string
  mode: OracleMode
  // ...
}
// etc.

export type Connection = OracleConnection | PostgresConnection | MySQLConnection | ...
```

### 3. Connections Page

**File:** `frontend/src/pages/ConnectionsPage.tsx`

Update the connection table to show a `Type` badge column. The test result modal can display type-specific info (e.g., PostgreSQL version, MySQL version).

---

## Implementation Phases

### Phase 2a — Foundation (do first)
1. Alembic migration: add `db_type`, `file_path`, `extra_params` columns; make `host`/`username` nullable
2. Update `OracleConnection` model with new fields
3. Update Pydantic schemas to discriminated union
4. Update `ConnectionResponse` to expose `db_type`
5. Update frontend types and connection table (add Type column)
6. Update `ConnectionForm` to show DB type selector + conditional fields
7. Keep all Oracle functionality working — regression test

### Phase 2b — PostgreSQL Driver
1. Add `_execute_postgres()` to executor
2. Add `_test_postgres()` to connection service
3. Smoke test: create a PostgreSQL connection pointing at the app's own DB

### Phase 2c — MySQL Driver
1. Add `aiomysql` dependency
2. Add `_execute_mysql()` and `_test_mysql()`

### Phase 2d — SQL Server Driver
1. Add `pyodbc` dependency
2. Add `_execute_sqlserver()` and `_test_sqlserver()`
3. Document ODBC driver OS prerequisite

### Phase 2e — SQLite + DBF
1. Add `dbfread` dependency
2. Add file-based executors
3. Handle the no-host/no-auth flow in frontend

---

## Questions / Decisions Needed

1. **Schema storage strategy:** Should type-specific fields like `database`, `sslmode`, `charset` be stored as separate nullable columns (explicit, queryable) or as JSONB in `extra_params` (flexible, opaque)?
   _Recommendation: explicit columns for first-class fields (host, port, database), JSONB for secondary driver options._

2. **Backward compatibility:** Existing Oracle connections stored without a `db_type` value — default to `'oracle'` in migration. Does this work for your existing data?

3. **DBF scope:** DBF is file-based and server-side — the backend reads local `.dbf` files. Is the use case that DBF files are on the same machine as the backend? If so, what SQL dialect should be supported (dBase SQL is very limited)?

4. **Cloud warehouses (Snowflake, BigQuery):** Include in Phase 2 or defer to Phase 3?

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `backend/alembic/versions/0002_add_db_type_multi_database.py` | Create |
| `backend/app/models/connection.py` | Modify |
| `backend/app/schemas/connection.py` | Modify |
| `backend/app/services/connection.py` | Modify |
| `backend/app/sql/executor.py` | Modify |
| `backend/requirements.txt` or new `requirements-*.txt` files | Modify |
| `frontend/src/types/connection.ts` | Modify |
| `frontend/src/components/connections/ConnectionForm.tsx` | Modify |
| `frontend/src/pages/ConnectionsPage.tsx` | Modify |
| `docs/deployment.md` | Modify (document new OS prerequisites per DB) |
| `README.md` | Modify (update supported databases list) |
