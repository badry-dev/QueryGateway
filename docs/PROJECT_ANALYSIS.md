# QueryGateway: Project Analysis & Manifesto

> **Historical analysis with current implementation notes (updated 2026-08-31).** This document
> records the product and technology evaluation that preceded implementation. The authoritative
> runtime contract is now [Architecture](architecture.md), and endpoint/scheduler/snapshot
> parameter behavior is defined in [Parameter contracts](scheduler_parameter_bindings.md).
> QueryGateway currently runs Python 3.14+, a Vite + React admin SPA, an in-process APScheduler
> whose PostgreSQL schedule definitions are restored at startup, schedule-owned SQL bindings, and
> coverage-aware typed snapshot filtering.

## 1. Executive Summary

**Project Name:** QueryGateway
**Goal:** Provide a self-hosted platform that enables users to expose local database data through dynamically generated RESTful API endpoints, using a wizard-driven UI for configuration.

**Core Value Proposition:** Organizations with Oracle (and later other) databases need a lightweight, self-hosted tool to expose specific query results as secure REST APIs — without requiring developers to hand-code each endpoint. QueryGateway bridges the gap between database-stored data and modern API consumers.

---

## 2. Open-Source Alternatives Assessment

Before building from scratch, the following existing open-source and free tools were evaluated against the project's MVP requirements.

### 2.1 Requirements Checklist (MVP)

| # | Requirement | Weight |
|---|-------------|--------
| R1 | Oracle Database connectivity | Must-have |
| R2 | Custom SQL queries as API endpoints (not just table CRUD) | Must-have |
| R3 | Dynamic parameters in SQL queries | Must-have |
| R4 | Web UI / wizard for API creation | Must-have |
| R5 | Authentication (Bearer token, Basic Auth) | Must-have |
| R6 | Task scheduling for periodic data refresh | Must-have |
| R7 | JSON output from query results | Must-have |
| R8 | Configurable API URL and port | Must-have |
| R9 | Store generated JSON to file/database | Must-have |
| R10 | Python backend (FastAPI) | Preferred |
| R11 | Next.js frontend | Preferred |
| R12 | Self-hosted / fully open-source | Must-have |

### 2.2 Evaluated Tools

#### A. Oracle REST Data Services (ORDS)

- **URL:** <https://www.oracle.com/database/technologies/appdev/rest.html>
- **License:** Free (proprietary, not open-source)
- **Oracle Support:** Native — built by Oracle
- **Custom SQL Endpoints:** Yes — RESTful service modules with SQL/PL/SQL
- **Web UI:** Oracle APEX integration (separate product)
- **Auth:** OAuth2, Basic Auth, custom privilege/role system
- **Scheduling:** No native scheduling — requires DBMS_SCHEDULER or external cron
- **JSON Caching/Storage:** No — live queries only
- **Tech Stack:** Java

| Requirement | Met? | Notes |
|-------------|------|-------|
| R1 Oracle | YES | Native |
| R2 Custom SQL | YES | Full SQL/PL/SQL support |
| R3 Dynamic params | YES | Bind variables in templates |
| R4 Web UI wizard | PARTIAL | Requires Oracle APEX or SQL Developer |
| R5 Auth | YES | OAuth2, Basic Auth, role-based |
| R6 Scheduling | NO | External only (DBMS_SCHEDULER) |
| R7 JSON output | YES | Native JSON responses |
| R8 Configurable URL/port | YES | Standalone deployment |
| R9 Store JSON | NO | No caching/storage mechanism |
| R10 Python/FastAPI | NO | Java-based |
| R11 Next.js frontend | NO | No standalone frontend |
| R12 Open-source | NO | Free but proprietary |

**Verdict:** Closest Oracle-native solution but not open-source. No scheduling, no JSON caching, no wizard UI, wrong tech stack.

---

#### B. DreamFactory

- **URL:** <https://github.com/dreamfactorysoftware/dreamfactory>
- **License:** Apache 2.0 (community edition); Commercial for Oracle
- **Oracle Support:** Commercial edition ONLY
- **Custom SQL Endpoints:** Yes (stored procedures, custom SQL)
- **Web UI:** Yes — full admin panel
- **Auth:** OAuth 2.0, SAML, LDAP, API keys (enterprise features)
- **Scheduling:** No native scheduling
- **Tech Stack:** PHP (Laravel)

| Requirement | Met? | Notes |
|-------------|------|-------|
| R1 Oracle | NO (free) | Oracle requires paid license |
| R2 Custom SQL | YES | Via stored procedures/scripts |
| R3 Dynamic params | YES | URL parameters mapped to queries |
| R4 Web UI wizard | YES | Full admin panel |
| R5 Auth | YES | Multiple methods |
| R6 Scheduling | NO | No native scheduling |
| R7 JSON output | YES | Native |
| R8 Configurable URL/port | YES | Docker/standalone |
| R9 Store JSON | NO | No caching layer |
| R10 Python/FastAPI | NO | PHP-based |
| R11 Next.js frontend | NO | Built-in Angular admin |
| R12 Open-source | PARTIAL | Oracle connector is commercial |

**Verdict:** Oracle support is paywalled. Wrong tech stack. No scheduling.

---

#### C. Directus

- **URL:** <https://github.com/directus/directus>
- **License:** BSL 1.1 (free for <$5M revenue organizations)
- **Oracle Support:** Listed as supported (via Knex.js)
- **Custom SQL Endpoints:** Limited — primarily CRUD on existing tables/views
- **Web UI:** Yes — excellent admin panel
- **Auth:** SSO, OAuth2, OpenID, custom
- **Scheduling:** Flows (automation) with scheduled triggers
- **Tech Stack:** TypeScript/Node.js

| Requirement | Met? | Notes |
|-------------|------|-------|
| R1 Oracle | PARTIAL | Listed but community reports issues |
| R2 Custom SQL | LIMITED | Primarily table/view CRUD; custom endpoints require extensions |
| R3 Dynamic params | LIMITED | Filter parameters, not arbitrary SQL params |
| R4 Web UI wizard | YES | Excellent UI |
| R5 Auth | YES | Multiple providers |
| R6 Scheduling | PARTIAL | Flows automation, not query-to-cache scheduling |
| R7 JSON output | YES | Native |
| R8 Configurable URL/port | YES | Environment config |
| R9 Store JSON | NO | No query-result caching |
| R10 Python/FastAPI | NO | Node.js/TypeScript |
| R11 Next.js frontend | NO | Built-in Vue.js admin |
| R12 Open-source | PARTIAL | BSL 1.1 with revenue cap |

**Verdict:** Designed for headless CMS, not raw SQL-to-API. Oracle support is unstable. Not truly open-source (BSL license). Cannot expose arbitrary SQL queries as endpoints without heavy customization.

---

#### D. Fusio

- **URL:** <https://github.com/apioo/fusio>
- **License:** MIT (with AGPLv3 for some components)
- **Oracle Support:** Yes (via dedicated Docker image)
- **Custom SQL Endpoints:** Yes — actions can execute arbitrary SQL
- **Web UI:** Yes — admin panel for routes, actions, connections
- **Auth:** OAuth2, API keys
- **Scheduling:** Cronjob integration
- **Tech Stack:** PHP (with Python worker support)

| Requirement | Met? | Notes |
|-------------|------|-------|
| R1 Oracle | YES | Via dedicated Docker image |
| R2 Custom SQL | YES | Actions with SQL queries |
| R3 Dynamic params | YES | Route parameters passed to actions |
| R4 Web UI wizard | YES | Admin panel |
| R5 Auth | YES | OAuth2, API keys |
| R6 Scheduling | PARTIAL | Cronjob support, not built-in scheduler UI |
| R7 JSON output | YES | Native |
| R8 Configurable URL/port | YES | Docker/config |
| R9 Store JSON | NO | No query-result caching/storage |
| R10 Python/FastAPI | NO | PHP core (Python via worker) |
| R11 Next.js frontend | NO | Built-in React admin |
| R12 Open-source | YES | MIT |

**Verdict:** Closest match feature-wise. However: PHP-based (not Python/FastAPI), no built-in JSON caching/storage from query results, Python is only available via a worker system (not native). Would require significant customization to meet all MVP requirements.

---

#### E. Sandman2

- **URL:** <https://github.com/jeffknupp/sandman2>
- **License:** Apache 2.0
- **Oracle Support:** Yes (via SQLAlchemy)
- **Custom SQL Endpoints:** No — auto-generates CRUD from tables only
- **Web UI:** Basic admin page
- **Auth:** No built-in authentication
- **Scheduling:** None
- **Tech Stack:** Python (Flask)

| Requirement | Met? | Notes |
|-------------|------|-------|
| R1 Oracle | YES | Via SQLAlchemy |
| R2 Custom SQL | NO | Table CRUD only |
| R3 Dynamic params | NO | No custom queries |
| R4 Web UI wizard | MINIMAL | Basic admin page |
| R5 Auth | NO | No authentication |
| R6 Scheduling | NO | None |
| R7 JSON output | YES | Native |
| R8 Configurable URL/port | YES | Flask config |
| R9 Store JSON | NO | Live queries only |
| R10 Python/FastAPI | PARTIAL | Python but Flask, not FastAPI |
| R11 Next.js frontend | NO | None |
| R12 Open-source | YES | Apache 2.0 |

**Verdict:** Too basic. No custom SQL, no auth, no scheduling. Dead project (last significant update years ago).

---

#### F. Datasette

- **URL:** <https://datasette.io/>
- **License:** Apache 2.0
- **Oracle Support:** No — SQLite only
- **Tech Stack:** Python

**Verdict:** Eliminated — SQLite only, no Oracle support.

---

#### G. PostgREST / Supabase / Hasura

- **URLs:** <https://postgrest.org> / <https://supabase.com> / <https://hasura.io>
- **Oracle Support:** None — PostgreSQL only (Hasura adds SQL Server/BigQuery)

**Verdict:** Eliminated — no Oracle support.

---

#### H. DB2Rest

- **URL:** <https://db2rest.com/> / <https://github.com/kdhrubo/db2rest>
- **License:** Apache 2.0
- **Oracle Support:** Yes
- **Custom SQL Endpoints:** Limited — primarily CRUD
- **Web UI:** No web UI
- **Tech Stack:** Java (Spring Boot)

**Verdict:** Java-based, no web UI, limited custom SQL support, no scheduling.

---

#### I. ZenQuery

- **URL:** <https://github.com/BjoernKW/ZenQuery>
- **Oracle Support:** Yes
- **Custom SQL Endpoints:** Yes — read-only queries
- **Web UI:** Yes — query editor
- **Tech Stack:** Java

**Verdict:** Read-only (matches MVP GET-only requirement), but Java-based, appears to be a smaller/less maintained project.

---

### 2.3 Alternatives Comparison Matrix

| Tool | Oracle | Custom SQL | Web UI | Auth | Scheduling | JSON Cache | Python | Open-Source | Score /12 |
|------|:------:|:----------:|:------:|:----:|:----------:|:----------:|:------:|:-----------:|:---------:|
| ORDS | YES | YES | PARTIAL | YES | NO | NO | NO | NO | 5 |
| DreamFactory | NO* | YES | YES | YES | NO | NO | NO | PARTIAL | 4 |
| Directus | PARTIAL | LIMITED | YES | YES | PARTIAL | NO | NO | PARTIAL | 5 |
| **Fusio** | **YES** | **YES** | **YES** | **YES** | **PARTIAL** | **NO** | **NO** | **YES** | **7** |
| Sandman2 | YES | NO | MINIMAL | NO | NO | NO | PARTIAL | YES | 3 |
| Datasette | NO | YES | YES | PARTIAL | NO | NO | YES | YES | 4 |
| DB2Rest | YES | LIMITED | NO | YES | NO | NO | NO | YES | 4 |
| ZenQuery | YES | YES | YES | LIMITED | NO | NO | NO | YES | 5 |

*\*DreamFactory Oracle requires paid license*

### 2.4 Gap Analysis Conclusion

**No existing open-source tool fully satisfies the MVP requirements.** The key gaps across all evaluated tools:

1. **No tool combines Oracle + Custom SQL + Scheduling + JSON caching** — this is the project's unique value proposition
2. **No Python/FastAPI-based solution** supports Oracle with a wizard-driven UI
3. **Scheduling with data caching** (run query on schedule, store results, serve from cache) is not offered by any tool — they all serve live queries
4. **The wizard-based API creation flow** (connection → SQL → auth → endpoint → schedule) is unique to this project

**Fusio** comes closest (7/12) but fails on:

- Python/FastAPI tech stack (PHP core)
- No JSON result caching/storage
- No Next.js frontend
- Scheduling is basic cronjob, not the envisioned create-and-manage scheduler

**Recommendation: BUILD — proceed with custom development.** The combination of requirements is sufficiently unique that no existing tool can be adopted as-is. However, the architecture should draw inspiration from Fusio's action/connection model and ORDS's SQL template approach.

---

## 3. Project Manifesto

### 3.1 Vision

QueryGateway is a self-hosted, open-source platform that democratizes database data access by enabling non-developers to create secure REST API endpoints from SQL queries through an intuitive wizard interface — without writing application code.

### 3.2 Core Principles

1. **Wizard-Driven Simplicity** — Creating an API endpoint should be a guided, step-by-step process accessible to database analysts and administrators, not just developers.
2. **Security by Default** — Every endpoint requires authentication. No anonymous access. All inputs are parameterized to prevent SQL injection. All actions are logged.
3. **Flexible Data Freshness** — Users choose between live database queries or scheduled data snapshots, balancing performance with data currency.
4. **Oracle-First, Database-Agnostic Architecture** — MVP targets Oracle, but the architecture uses abstraction layers (SQLAlchemy) to support future database additions.
5. **Separation of Concerns** — Python/FastAPI backend handles business logic and database interaction; Next.js frontend handles the user experience; PostgreSQL stores application state.

### 3.3 MVP Scope

#### Module 1: Database Connection Management

- Create, edit, delete, and test Oracle database connections
- Store connection details securely (encrypted credentials)
- Connection pooling configuration
- Health check / connectivity test

#### Module 2: API Creation Wizard

A step-by-step wizard flow:

1. **Select Connection** — Choose from pre-configured database connections
2. **Write SQL Query** — SQL editor with syntax highlighting; define dynamic parameters (`:param_name` bind variables)
3. **Preview & Map Results** — Execute query preview, view JSON structure, configure column mapping/renaming
4. **Configure Authentication** — Select from pre-configured auth methods (Bearer token, Basic Auth, API key)
5. **Define Endpoint** — Set the URL path, HTTP method (GET for MVP), response format
6. **Set Data Strategy** — Choose between:
   - **Live Query** — Execute SQL on every API call
   - **Scheduled Snapshot** — Run SQL on a schedule, cache results as JSON (in file or PostgreSQL)
7. **Review & Deploy** — Summary page, then activate the endpoint

#### Module 3: Authentication Configuration

- Create and manage authentication methods
- Supported types (MVP): Bearer Token, Basic Authentication, API Key (header)
- Custom header requirements per auth method
- Token generation and management

#### Module 4: Task Scheduling

- Create scheduled tasks to refresh cached API data
- Configurable frequencies (cron-style: every N minutes/hours/daily/weekly/custom)
- Task execution logging (start time, duration, success/failure, row count)
- Manual trigger option
- Task enable/disable toggle

#### Module 5: Settings

- Configure API base URL and port
- Application-level settings (logging level, max query timeout, etc.)
- System health dashboard

### 3.4 Proposed Tech Stack

| Layer | Technology | Justification |
|-------|-----------|---------------|
| **Backend API** | Python 3.11+ / FastAPI | User preference; async support; auto-generated OpenAPI docs |
| **Oracle Connectivity** | python-oracledb | Official Oracle Python driver; thin mode (no Oracle Client needed) |
| **ORM / Query Layer** | SQLAlchemy 2.0 | Database abstraction for future multi-DB support |
| **App Database** | PostgreSQL | Stores connections, endpoints, schedules, logs, cached results |
| **Task Scheduling** | APScheduler | Python-native in-process scheduler; definitions persist in PostgreSQL and active jobs are restored on startup |
| **Frontend** | Next.js 14+ (App Router) | User preference; SSR/SSG capabilities |
| **UI Components** | shadcn/ui + Tailwind CSS | User preference; modern, accessible component library |
| **Testing** | pytest + pytest-asyncio | User preference; comprehensive async test support |
| **Auth Library** | python-jose + passlib | JWT token handling and password hashing |
| **Logging** | Python logging + structlog | Structured JSON logging for all operations |
| **Containerization** | Docker + docker-compose | Consistent deployment across environments |

### 3.5 High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Next.js Frontend                  │
│            (shadcn/ui + Tailwind CSS)                │
│                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │ Wizard   │ │ Connections│ │ Auth     │ │Settings│ │
│  │ UI       │ │ Manager   │ │ Manager  │ │ Page   │ │
│  └────┬─────┘ └─────┬────┘ └────┬─────┘ └───┬────┘ │
└───────┼──────────────┼──────────┼────────────┼──────┘
        │              │          │            │
        ▼              ▼          ▼            ▼
┌─────────────────────────────────────────────────────┐
│                FastAPI Backend                        │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │           Admin API (/api/admin/*)            │   │
│  │  • Connection CRUD    • Auth Method CRUD      │   │
│  │  • Endpoint CRUD      • Schedule CRUD         │   │
│  │  • Settings           • Logs                  │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │        Dynamic API Router (/api/data/*)       │   │
│  │  • Resolves endpoint path                     │   │
│  │  • Validates authentication                   │   │
│  │  • Returns cached JSON or executes live query │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────┐  ┌─────────────┐  ┌────────────┐ │
│  │ APScheduler  │  │ SQLAlchemy  │  │ Auth       │ │
│  │ (Job Store)  │  │ (ORM)       │  │ Middleware │ │
│  └──────┬───────┘  └──────┬──────┘  └────────────┘ │
└─────────┼────────────────┼──────────────────────────┘
          │                │
          ▼                ▼
┌──────────────┐   ┌──────────────┐
│  PostgreSQL  │   │ Oracle DB(s) │
│  (App Data)  │   │ (User Data)  │
│  • Endpoints │   │              │
│  • Schedules │   │              │
│  • Auth      │   │              │
│  • Logs      │   │              │
│  • Cache     │   │              │
└──────────────┘   └──────────────┘
```

### 3.6 Data Flow: API Request Lifecycle

```
Client Request → GET /api/data/sales/by-region?year=2024
                        │
                        ▼
              ┌─────────────────┐
              │  Auth Middleware │ ── Validates Bearer/Basic/API Key
              └────────┬────────┘
                       │ (authenticated)
                       ▼
              ┌─────────────────┐
              │ Dynamic Router  │ ── Looks up endpoint config by path
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │ Data Strategy?  │
              └────┬───────┬────┘
                   │       │
            Cached │       │ Live
                   ▼       ▼
            ┌────────┐ ┌──────────────┐
            │ Return │ │ Execute SQL  │
            │ stored │ │ with params  │
            │ JSON   │ │ on Oracle DB │
            └────────┘ └──────┬───────┘
                              │
                              ▼
                        ┌───────────┐
                        │ Return    │
                        │ JSON      │
                        └───────────┘
```

### 3.7 Security Considerations (Day One)

| Area | Approach |
|------|----------|
| SQL Injection | Parameterized queries only; bind variables enforced; no string concatenation |
| Credential Storage | AES-256 encryption for database passwords; environment-based secrets |
| Authentication | Mandatory on all data endpoints; configurable per-endpoint |
| Authorization | Role-based access in admin panel |
| Input Validation | Pydantic models for all API inputs; parameter type enforcement |
| CORS | Configurable allowed origins |
| Rate Limiting | Configurable per-endpoint rate limits |
| Logging | All access logged with timestamp, IP, user, endpoint, status |
| HTTPS | TLS termination supported via reverse proxy configuration |
| Secrets Management | Environment variables for sensitive config; no secrets in codebase |

### 3.8 Future Roadmap (Post-MVP)

| Phase | Features |
|-------|----------|
| **v1.1** | Additional databases (PostgreSQL, MySQL) via SQLAlchemy dialects |
| **v1.2** | CRUD operations (POST, PUT, DELETE endpoints) |
| **v1.3** | Request body processing and passing to database procedures |
| **v1.4** | Endpoint grouping with parent paths (/group/endpoint) |
| **v2.0** | GraphQL support |
| **v2.1** | Auto-generated OpenAPI/Swagger documentation per endpoint |
| **v2.2** | Postman collection export |
| **v2.3** | API versioning support |

---

## 4. Decision Required

Before proceeding to the detailed implementation plan, please confirm:

1. **Build vs. Adopt:** Do you agree with the recommendation to build custom rather than adopt an existing tool?
2. **Tech Stack:** Is the proposed tech stack (FastAPI + Next.js + PostgreSQL + shadcn/ui) confirmed?
3. **MVP Scope:** Is the 5-module MVP scope correctly captured?
4. **Architecture:** Does the high-level architecture align with your vision?
5. **Any adjustments** to priorities, features, or approach?

---

## 5. Decision Responses & Tech Stack Evaluation

### 5.1 Confirmed Decisions

| # | Question | Decision | Notes |
|---|----------|----------|-------|
| 1 | Build vs. Adopt | **BUILD CUSTOM** | Confirmed. Will be developed as an open-source project for future community publication. The gap analysis (Section 2.4) validates that no existing tool covers the unique combination of Oracle + Custom SQL + Scheduling + JSON caching + Wizard UI. |
| 3 | MVP Scope (5 modules) | **CONFIRMED** | The five modules (Connection Management, API Creation Wizard, Auth Configuration, Task Scheduling, Settings) correctly capture the MVP scope. |
| 4 | Architecture | **CONFIRMED** | The high-level architecture (Section 3.5) and request lifecycle (Section 3.6) align with the project vision. No changes needed. |
| 5 | Adjustments | **NONE** | No adjustments to priorities or approach at this time. |

**Question 2 (Tech Stack)** requires a detailed evaluation — see Section 5.2 below.

### 5.2 Tech Stack Evaluation

The proposed stack from Section 3.4 is evaluated below on a component-by-component basis, considering fitness for the project's specific requirements, ecosystem maturity, developer experience, operational characteristics, and long-term maintainability.

---

#### 5.2.1 Backend: Python 3.11+ / FastAPI

**Verdict: ✅ STRONGLY RECOMMENDED — Excellent fit.**

| Criterion | Assessment |
|-----------|-----------|
| **Performance** | FastAPI is one of the fastest Python frameworks, built on Starlette (ASGI) with native `async/await`. For a tool serving cached JSON or proxying DB queries, throughput is more than adequate. |
| **Async Support** | Critical for this project. Multiple concurrent Oracle connections, scheduled tasks, and API serving all benefit from async I/O. FastAPI's native async support avoids thread-pool bottlenecks. |
| **Auto-Generated OpenAPI Docs** | Built-in Swagger UI and ReDoc provide instant interactive API documentation — valuable both for the admin API and for users consuming generated endpoints. |
| **Pydantic Integration** | Pydantic v2 (used by FastAPI 0.100+) provides robust request/response validation, serialization, and settings management. This directly supports the "Input Validation" security requirement (Section 3.7). |
| **Ecosystem Compatibility** | `python-oracledb`, `SQLAlchemy 2.0`, `APScheduler`, `python-jose`, `passlib` — all integrate cleanly with FastAPI. No compatibility concerns. |
| **Community & Maintenance** | FastAPI has 75k+ GitHub stars, active maintenance by Sebastián Ramírez, and a large ecosystem of middleware/plugins. Low risk of abandonment. |
| **Learning Curve** | Moderate. Type hints + dependency injection pattern requires familiarity but leads to highly maintainable code. |

**Risks & Mitigations:**

- *Risk:* FastAPI's dependency injection system can become complex in large applications. *Mitigation:* Establish clear patterns early (service layer, repository pattern) and document conventions.
- *Risk:* Python GIL limits true CPU parallelism. *Mitigation:* Not a concern — this project is I/O-bound (DB queries, HTTP serving), not CPU-bound.

**Implemented target:** Python 3.14+. The repository's Ruff, mypy, dependencies, Docker image, and
developer setup all use Python 3.14 or newer.

---

#### 5.2.2 Oracle Connectivity: python-oracledb

**Verdict: ✅ STRONGLY RECOMMENDED — The only correct choice.**

| Criterion | Assessment |
|-----------|-----------|
| **Official Support** | Maintained by Oracle. It is the official successor to cx_Oracle. |
| **Thin Mode** | Can connect to Oracle without requiring the Oracle Client libraries — a massive simplification for deployment, especially in Docker. |
| **Thick Mode** | Optional Oracle Client integration for advanced features (Advanced Queuing, LDAP lookups, etc.) if needed post-MVP. |
| **Async Support** | Supports asyncio via `oracledb.connect_async()` — aligns perfectly with FastAPI's async architecture. |
| **Connection Pooling** | Built-in connection pool management, configurable min/max/increment — matches Module 1 (Connection Management) requirements. |

**No alternatives exist** with equivalent Oracle support in the Python ecosystem. This is the definitive choice.

---

#### 5.2.3 ORM / Query Layer: SQLAlchemy 2.0

**Verdict: ✅ RECOMMENDED — Right choice with caveats.**

| Criterion | Assessment |
|-----------|-----------|
| **Database Abstraction** | The primary justification — enables future multi-database support (PostgreSQL, MySQL, SQL Server) via dialect swapping. |
| **Async Support** | SQLAlchemy 2.0 has first-class async support via `AsyncSession` and `AsyncEngine`. |
| **Oracle Dialect** | Full Oracle dialect support via python-oracledb backend. |
| **Dual Usage** | Can be used for ORM (app database models) AND for raw SQL execution (user queries against Oracle), covering both use cases. |
| **Migration Support** | Alembic (SQLAlchemy's migration tool) provides robust schema versioning for the PostgreSQL app database. |

**Important Caveat:** For user-defined SQL queries (Module 2), SQLAlchemy should be used as a **connection/execution layer only** — not as an ORM. User queries must be passed through as parameterized raw SQL via `text()` with bind parameters. This distinction should be clearly architected:

- **App database (PostgreSQL):** Use SQLAlchemy ORM models (connections, endpoints, schedules, logs)
- **User databases (Oracle):** Use SQLAlchemy Core `text()` with bound parameters for raw query execution

---

#### 5.2.4 App Database: PostgreSQL

**Verdict: ✅ STRONGLY RECOMMENDED — Ideal choice.**

| Criterion | Assessment |
|-----------|-----------|
| **JSON/JSONB Columns** | Native JSONB support is perfect for storing cached query results (Module 4). Supports indexing, querying, and partial updates on JSON data. |
| **APScheduler Job Store** | Built-in PostgreSQL job store support — jobs survive process restarts. |
| **Reliability** | Battle-tested, ACID-compliant, excellent for storing application state. |
| **Scalability** | More than sufficient for the expected workload (metadata storage + cached JSON). |
| **Ecosystem** | `asyncpg` driver provides high-performance async access; integrates seamlessly with SQLAlchemy 2.0 async. |

**Consideration:** For local development and testing, consider also supporting SQLite as an alternative app database (via SQLAlchemy dialect swapping) so developers can run the project without a PostgreSQL instance. This is a "nice-to-have" for developer experience, not a requirement.

---

#### 5.2.5 Task Scheduling: APScheduler

**Verdict: ✅ RECOMMENDED — Good fit for MVP.**

| Criterion | Assessment |
|-----------|-----------|
| **Cron Triggers** | Full cron expression support matches the scheduling requirements in Module 4. |
| **Restart restoration** | Schedule definitions and next-run metadata persist in PostgreSQL; the single API process restores active jobs into APScheduler's in-memory job store at startup. |
| **Python-Native** | Runs in-process, no external dependencies (no Redis, no RabbitMQ, no Celery). |
| **Dynamic Jobs** | Jobs can be added, modified, paused, and removed at runtime — essential for the wizard-based scheduling flow. |

**Note on APScheduler Version:** APScheduler 4.x (currently in alpha/beta) is a significant rewrite with native async support and a redesigned architecture. **Recommendation:** Use APScheduler 3.x (stable) for MVP. The 3.x series is well-tested and documented. Evaluate migration to 4.x post-MVP once it reaches stable release.

**Long-Term Consideration:** If the project scales to require distributed task execution (multiple worker nodes), Celery + Redis/RabbitMQ would be the natural evolution. APScheduler is sufficient for the single-instance deployment targeted by MVP.

---

#### 5.2.6 Frontend: Next.js 14+ (App Router)

**Verdict: ✅ RECOMMENDED — Good choice, with architectural guidance.**

| Criterion | Assessment |
|-----------|-----------|
| **React Ecosystem** | Access to the full React component ecosystem; strong community support. |
| **App Router (RSC)** | React Server Components reduce client-side JavaScript bundle size. Useful for the admin dashboard pages. |
| **API Routes** | Next.js API routes can serve as a BFF (Backend-for-Frontend) layer, proxying requests to FastAPI and handling session management. |
| **TypeScript** | First-class TypeScript support ensures type safety across the frontend. |
| **SSR/SSG** | Server-side rendering provides fast initial page loads for the admin panel. |

**Architectural Guidance:**

- The Next.js app should function as a **pure admin UI / management console**. It should NOT serve the dynamic data API endpoints — those are handled exclusively by FastAPI.
- Use Next.js API routes **only** for frontend concerns (session management, BFF proxying to FastAPI admin API) — not for business logic.
- The wizard flow (Module 2) is the most complex frontend feature. React's component model with state management (React Context or Zustand) is well-suited for multi-step wizard forms.

**Alternative Considered — Vite + React SPA:**
A simpler Vite-based React SPA was considered. Since this is a self-hosted admin tool (not a public-facing website), SSR/SSG benefits are minimal. However, Next.js still wins for:

1. File-based routing (faster development for the multi-page admin interface)
2. Built-in API routes for BFF pattern
3. Better developer tooling and conventions
4. The team's stated preference

The overhead of Next.js is justified by development velocity rather than runtime benefits.

---

#### 5.2.7 UI Components: shadcn/ui + Tailwind CSS

**Verdict: ✅ STRONGLY RECOMMENDED — Excellent choice.**

| Criterion | Assessment |
|-----------|-----------|
| **Not a Dependency** | shadcn/ui copies components into the project — no version lock-in, full control over the code. |
| **Accessibility** | Built on Radix UI primitives, providing WCAG-compliant components out of the box. |
| **Wizard Components** | Stepper, Form, Dialog, Select, Command, and Table components directly support the wizard flow and admin CRUD interfaces. |
| **Tailwind CSS** | Utility-first CSS ensures consistent styling without CSS architecture decisions. Pairs perfectly with shadcn/ui. |
| **Customizability** | Full source code ownership means any component can be modified to match exact project requirements. |
| **Dark Mode** | Built-in theming support (light/dark mode) with minimal configuration. |

**Note:** Consider adding a rich code/SQL editor component (e.g., Monaco Editor via `@monaco-editor/react` or CodeMirror via `@uiw/react-codemirror`) for Module 2's SQL query writing step. This is beyond what shadcn/ui provides but is essential for a good query-authoring experience.

---

#### 5.2.8 Auth Libraries: python-jose + passlib

**Verdict: ⚠️ RECOMMENDED WITH SUBSTITUTION.**

| Library | Assessment |
|---------|-----------|
| **python-jose** | ⚠️ **Concern:** python-jose has not been actively maintained (last release in 2021). The project shows limited activity. |
| **passlib** | ⚠️ **Concern:** passlib has also seen reduced maintenance activity. |

**Recommendation:**

- Replace `python-jose` with **PyJWT** (`PyJWT` package). PyJWT is actively maintained (by the jpadilla team), has 5k+ stars, frequent releases, and is the most widely adopted JWT library in the Python ecosystem. It covers all JWT needs for this project (token creation, validation, expiration handling).
- Replace `passlib` with **bcrypt** (`bcrypt` package) directly for password hashing, or keep passlib if broader hashing algorithm support is needed. For the MVP (Bearer Token, Basic Auth, API Key), bcrypt via the `bcrypt` package is sufficient and more actively maintained.

| Original | Replacement | Reason |
|----------|-------------|--------|
| python-jose | **PyJWT** | Actively maintained, widely adopted, simpler API |
| passlib | **bcrypt** (direct) | More focused, actively maintained; passlib acceptable if multiple hash algorithms needed |

---

#### 5.2.9 Logging: Python logging + structlog

**Verdict: ✅ RECOMMENDED.**

structlog provides structured JSON logging which is essential for:

- Task execution logging (Module 4: start time, duration, success/failure, row count)
- API access logging (Section 3.7: timestamp, IP, user, endpoint, status)
- Integration with log aggregation tools (ELK, CloudWatch, etc.) in production deployments

No changes recommended.

---

#### 5.2.10 Containerization: Docker + docker-compose

**Verdict: ✅ STRONGLY RECOMMENDED.**

Essential for a self-hosted tool. Docker Compose should define:

- `api` service (FastAPI backend)
- `web` service (Next.js frontend)
- `db` service (PostgreSQL)
- Optional `oracle` service (for local development/testing with Oracle XE)

No changes recommended.

---

### 5.3 Tech Stack Summary: Final Recommendation

| Layer | Proposed | Recommendation | Change? |
|-------|----------|----------------|---------|
| **Backend** | Python 3.11+ / FastAPI | Python **3.12+** / FastAPI | Minor version bump |
| **Oracle Driver** | python-oracledb | python-oracledb | No change |
| **ORM** | SQLAlchemy 2.0 | SQLAlchemy 2.0 + **Alembic** (migrations) | Addition |
| **App Database** | PostgreSQL | PostgreSQL (+ **asyncpg** driver) | Driver specified |
| **Scheduler** | APScheduler | APScheduler **3.x** (stable) | Version pinned |
| **Frontend** | Next.js 14+ | Next.js 14+ (App Router) | No change |
| **UI Components** | shadcn/ui + Tailwind CSS | shadcn/ui + Tailwind CSS + **Monaco/CodeMirror** (SQL editor) | Addition |
| **Testing** | pytest + pytest-asyncio | pytest + pytest-asyncio | No change |
| **Auth** | python-jose + passlib | **PyJWT** + **bcrypt** | ⚠️ Substitution |
| **Logging** | structlog | structlog | No change |
| **Containers** | Docker + docker-compose | Docker + docker-compose | No change |

### 5.4 Additional Recommendations

1. **Monorepo Structure:** Organize the project as a monorepo with clear separation:

   ```
   QueryGateway/
   ├── backend/          # FastAPI application
   ├── frontend/         # Next.js application
   ├── docker/           # Docker configurations
   ├── docs/             # Project documentation
   └── docker-compose.yml
   ```

2. **API Versioning from Day One:** Prefix admin API routes with `/api/v1/admin/*` to allow non-breaking evolution.

3. **Environment Configuration:** Use Pydantic Settings (built into Pydantic v2) for configuration management with `.env` file support. This avoids custom config parsing and integrates naturally with FastAPI.

4. **Database Migrations:** Alembic should be included from the start. Schema changes to the PostgreSQL app database must be versioned and reproducible across environments.

5. **SQL Editor Component:** For the API Creation Wizard (Module 2), integrate a code editor component (Monaco Editor or CodeMirror 6) with SQL syntax highlighting, auto-completion, and error indicators. This is a critical UX feature for the query-authoring step.

6. **CI/CD Pipeline:** Set up GitHub Actions early with:
   - Backend: `ruff` (linting) + `pytest` (testing) + `mypy` (type checking)
   - Frontend: `eslint` + `prettier` + `vitest` (or Jest)
   - Docker build verification

---

## 6. Next Steps

With all decisions confirmed and the tech stack evaluated, the following implementation phases are proposed:

| Step | Description | Deliverable |
|------|-------------|-------------|
| **Step 1** | Repository scaffolding | Monorepo structure, Docker Compose, CI/CD pipeline, dev environment setup |
| **Step 2** | Backend foundation | FastAPI project setup, PostgreSQL models (Alembic migrations), health check endpoint |
| **Step 3** | Module 1 — Connection Management | CRUD API + UI for Oracle database connections, connection testing |
| **Step 4** | Module 3 — Auth Configuration | Auth method CRUD, token generation, middleware setup |
| **Step 5** | Module 2 — API Creation Wizard | Wizard flow (backend + frontend), SQL execution engine, dynamic endpoint router |
| **Step 6** | Module 4 — Task Scheduling | APScheduler integration, scheduled snapshot execution, task management UI |
| **Step 7** | Module 5 — Settings | App configuration, system health dashboard |
| **Step 8** | Integration testing & documentation | End-to-end testing, deployment documentation, user guide |

**Ready to proceed to Step 1 upon confirmation.**
