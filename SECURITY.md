# Security Policy

QueryGateway turns Oracle SQL queries into authenticated REST endpoints. It
handles untrusted HTTP input, stores third-party database credentials, signs
and verifies tokens, and runs scheduled jobs against production data sources.
Security is therefore a first-class concern across the request path, the
credential store, the scheduler, and the build/release supply chain.

This document covers:

1. [Reporting a Vulnerability](#1-reporting-a-vulnerability)
2. [Supported Versions](#2-supported-versions)
3. [Security Model & Best Practices](#3-security-model--best-practices)
4. [Supply-Chain Security Directive](#4-supply-chain-security-directive)

Two companion documents remain authoritative for their areas and are referenced
throughout: [`SECURITY_AI.md`](SECURITY_AI.md) (hard rules for AI-assisted
changes) and [`docs/security_checklist.md`](docs/security_checklist.md)
(pre-go-live validation checklist).

---

## 1. Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report suspected vulnerabilities, leaked credentials, or suspected breaches
privately to **bdarkoush@kudu.com.sa**. For a confirmed security incident
(leaked secrets, active breach), contact the same address immediately and
include "SECURITY INCIDENT" in the subject line.

When reporting, please include:

- A description of the issue and its potential impact.
- Steps to reproduce (proof-of-concept, affected endpoint, request samples).
- Affected version, commit SHA, or deployment.
- Any relevant logs **with secrets and PII redacted**.

What to expect:

- Acknowledgement of your report.
- An assessment of severity and scope.
- Coordinated disclosure once a fix is available; we credit reporters who wish
  to be named.

If you accidentally expose a credential (commit, log, screenshot, paste), treat
it as compromised: **rotate it immediately** and notify the address above. Do
not attempt to "scrub" it from history as the only remediation — rotation comes
first.

---

## 2. Supported Versions

Security fixes target the `main` branch and the most recent tagged release.
Older releases are not patched; upgrade to the latest release to receive
security updates.

---

## 3. Security Model & Best Practices

These practices reflect controls already implemented in QueryGateway (see
[`docs/security_checklist.md`](docs/security_checklist.md) for the validated
item-by-item list) plus the standards every change is expected to uphold.

### 3.1 Authentication & Authorization

- Authentication on data endpoints (`/api/v1/data/*`) is configured **per
  endpoint** and anonymous data access is never allowed. When an endpoint auth
  method is attached, the data plane enforces that Bearer, Basic, or API-key
  policy. When no dedicated method is attached, the legacy-named
  `allow_unauthenticated=true` value explicitly selects the platform-admin
  Bearer fallback; it does **not** make the endpoint public. A configuration
  with neither path is rejected by the admin API and default-denied with `401`
  by the data plane. The denied path logs
  `event="unauthenticated_endpoint_denied"` with the required request context.
- When an auth method **is** attached but is missing or inactive at request
  time, the endpoint **default-denies** with `401` (it never silently falls
  open). Expired or malformed credentials likewise return `401`, never `500`.
- JWTs are created and verified with **`PyJWT` only**. Every token carries
  `exp`, `iat`, and a subject claim; expired or malformed tokens are rejected
  deterministically with `401` (never `500`).
- Passwords, Basic Auth credentials, and API keys are hashed with **`bcrypt`
  only**, using a random salt and timing-safe comparison. Plaintext API keys are
  shown exactly once, at creation.
- Token and API-key rotation invalidates all previously issued credentials.
- Never bypass authentication for the data API, and never weaken token-expiry
  validation. (Hard rules: [`SECURITY_AI.md`](SECURITY_AI.md).)

### 3.2 Credential & Secret Storage

- Oracle passwords are encrypted at rest with **Fernet (AES-128-CBC +
  HMAC-SHA256)**; ciphertext lives in `encrypted_password` and is never returned
  by the API (`has_password` is the safe presence indicator).
- Bearer signing secrets are Fernet-encrypted before storage; `config_json` and
  sensitive auth config are excluded from API responses.
- `JWT_SECRET_KEY` and `ENCRYPTION_KEY` are sourced from the environment, never
  hardcoded and never committed. The app **refuses to boot** on a missing,
  empty, or too-short `JWT_SECRET_KEY`, or an invalid Fernet `ENCRYPTION_KEY`.
- The seeded admin credential (`ADMIN_USERNAME` / `ADMIN_PASSWORD_HASH`) is
  supplied as a bcrypt hash via environment; rotating it means redeploying.
- In production, keep secrets in a secrets manager (e.g. Kubernetes Secrets,
  cloud secret store) injected as environment variables — not in `.env` in the
  image or in version control. Never log credentials, connection strings, or
  token bodies.

### 3.3 SQL Execution Safety

- All user-defined SQL must be **parameterized** with named binds
  (`:param_name`). Never concatenate request values into SQL strings.
- Execution uses SQLAlchemy `text()` with a bind dict; parameters are coerced
  through typed schemas (`ParamDescriptor`) before execution.
- SQL safety validation rejects unsafe composition (string concatenation,
  PL/SQL `||` concatenation, f-strings, template interpolation) on create,
  update, and preview paths.
- Endpoint paths are validated with a strict allowlist regex that blocks path
  traversal and special characters.
- Use **least-privilege Oracle credentials** for query execution — read-only
  accounts scoped to the required objects wherever possible.

### 3.4 Input Validation & Data Exposure

- Validate all input at the schema (Pydantic) boundary; invalid input returns
  `422` with field-level detail, not `500`.
- Unhandled errors return a generic `{"detail": "Internal server error"}` —
  stack traces, Oracle connection strings, and internal schema details are
  never leaked to clients.
- Enforce string-length limits and enum validation on all user-supplied fields.
- Enforce every endpoint parameter marked `required` for both live and
  snapshot HTTP requests, even if the endpoint stores a default. Preview
  samples are temporary, optional live defaults are request behavior, and
  schedule bindings are a separate persisted contract.
- Parameterized snapshot endpoints must map every request parameter to a final
  cached output column and an allowlisted typed comparison. The data plane
  proves coverage from persisted job-run parameters before filtering rows; it
  never falls back to returning an unfiltered snapshot. Snapshot mappings are
  data selection, not tenant authorization.

### 3.5 Logging, Auditing & Privacy

- Use **structured logging** everywhere. Mandatory fields: `request_id`,
  `user`, `endpoint`, `status`, `duration_ms`, `method`, `client_ip`, `event`;
  scheduler jobs add `job_id`, `run_id`, `row_count`, `success`.
- Redact secrets and high-risk fields at logging boundaries; log the minimum
  PII required for the operation.
- Every data-endpoint request is access-logged with path, method, principal,
  IP, status, duration, and `request_id` for audit.

### 3.6 Scheduler Security

- Scheduled jobs use stored, encrypted connection credentials — never
  request-time credentials.
- Scheduled jobs resolve every SQL bind from schedule-owned declarative
  bindings (`literal`, `null`, logical/relative run date, or window boundary).
  They never inherit endpoint request defaults.
- Job execution errors are recorded internally and never expose Oracle details to data-API
  consumers. Snapshot requests use another retained covering run when available and return `503`
  when no retained snapshot exists.
- Concurrency is bounded (`max_instances=1` per job, `max_job_concurrency`) and
  snapshot retention is capped to prevent resource and storage exhaustion.

### 3.7 Transport & Deployment

- Terminate **HTTPS** at the reverse proxy (nginx/ALB/Cloudflare); do not serve
  the API over plaintext in production.
- **Run the app behind the reverse proxy with forwarded-header trust enabled.**
  When a proxy fronts the app, start uvicorn with `--proxy-headers` and
  `--forwarded-allow-ips` scoped to the proxy's address/subnet so the real
  client IP from `X-Forwarded-For` reaches the audit trail. Without this,
  `access_logs.remote_ip` and the structured-log `client_ip` record the
  proxy's address instead of the client's, defeating §3.4/§3.5 forensics.
  The reverse proxy must **overwrite** `X-Forwarded-For` with the real
  connecting address (e.g. nginx `proxy_set_header X-Forwarded-For
  $remote_addr;`), never append to a client-supplied value — otherwise a
  client can prepend a spoofed IP that a trusting backend logs as the source.
  Scope the backend's trusted-proxy list (`--forwarded-allow-ips` /
  `FORWARDED_ALLOW_IPS`) to the proxy's hop only, and put the backend on a
  network segment reachable solely by the proxy — so a compromised sibling
  service cannot connect directly and forge forwarded headers (assume-breach,
  §1.3).
- Restrict **CORS** via `CORS_ORIGINS` in production. The default is a local
  development origin (`http://localhost:5173`). **Never combine a wildcard
  origin (`CORS_ORIGINS=*`) with credentialed requests** — the app sends
  `allow_credentials=True`, and a wildcard origin under credentials makes the
  middleware reflect *any* Origin, which is a cross-origin data-theft vector.
  List explicit origins in production.
- Set `DEBUG=false` in production, and consider disabling the interactive API
  docs (`/api/docs`, `/api/redoc`, `/api/openapi.json`) in production so the
  full admin API schema is not exposed.
- Restrict network access to **both** datastores to the application network —
  they are distinct and both sensitive:
  - **PostgreSQL is QueryGateway's own application database.** It stores the
    service's state — Fernet-encrypted Oracle credentials and bearer signing
    secrets, bcrypt'd auth-method secrets, endpoint/SQL definitions, and the
    access-log audit trail. Compromising it is equivalent to compromising the
    gateway itself.
  - **Oracle is the queried data source** (one or more upstream databases the
    dynamic endpoints read from). Compromising it exposes the business data the
    gateway serves.

  Neither should be reachable outside the application network — in the bundled
  compose stack both sit on the internal `backend` network and their host port
  mappings are bound to loopback only. (Note: "Restrict PostgreSQL access" in
  `docs/security_checklist.md` #49 refers to this app database; it is **not** a
  typo for Oracle.) Keep the deployment "Action Required" items in
  [`docs/security_checklist.md`](docs/security_checklist.md) verified per
  installation.

### 3.8 Database Migrations

- All schema changes go through **Alembic** revisions; never mutate a committed
  or already-applied migration. Document migration impact and rollback in the PR.

### 3.9 Change-Time Security Review Triggers

Request a focused security review for changes that touch: auth middleware, SQL
parsing/execution, scheduler execution permissions, credential handling, or any
new environment variable or secret path. AI-assisted changes additionally
follow the hard rules in [`SECURITY_AI.md`](SECURITY_AI.md).

---

## 4. Supply-Chain Security Directive

> **Deployment:** `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`, or system prompt. Portable across agents.
>
> **Organizing principle:** Prevention *and* containment, proportional to risk, enforced by protected tooling. Trust-minimization alone is a prevention strategy, and prevention eventually fails — so this directive also assumes breach and limits blast radius. **Dependency count is not a security metric.** Security effort must be proportional to measurable risk reduction.

### 4.1 Core Principles

1. **Proportionality.** Effort spent ∝ risk reduced. Do not spend hours removing a low-risk dev/test dependency, avoid a mature audited library, or optimize a count. Scrutiny follows the risk tier (§4.2), not the manifest size.
2. **Trust surface, not count.** Fewer trust relationships *weighted by scrutiny and execution rights* — not fewer manifest entries. Hand-rolling to remove a dep can increase risk.
3. **Assume breach; minimize blast radius.** A trusted dependency *will* eventually be compromised. Scope what any code can reach: least-privilege CI tokens, ephemeral sandboxed builds, scoped secrets, network egress limits. Containment outranks any single preventive rule.
4. **Control code execution, not just installs.** The threat is any unreviewed code that runs at install, build, test, CI, or release time (§4.6).
5. **Enforcement > instruction, and protect the enforcement.** A rule that relies on memory is aspirational. Real controls live in CI and lockfiles (§4.9) — and the *configuration* of those controls must itself be protected, or it gets disabled in the same change that introduces risk.
6. **Provenance > publisher.** "First-party" is a weak signal. Code that ships *inside the runtime/stdlib* is genuinely low-risk; code merely *published on a registry by a large org* is still a registry trust relationship requiring verification.
7. **Minimize runtime sprawl (replaces any language ranking).** Prefer the dominant language already present in the repository. Introducing another runtime requires a compelling security, operational, or technical reason — each added runtime multiplies toolchains, registries, and CI surface.

### 4.2 Risk Tiering (everything downstream is proportional to this)

Classify each dependency / code source / artifact before applying controls:

- **Tier A — high risk:** handles untrusted input; implements or touches security primitives (§4.4); runs in production or in the request/data path; **or executes code at install/build/CI time**. Full scrutiny (§4.7 thresholds mandatory).
- **Tier B — medium:** internal/production-support, no untrusted input, no build-time execution. Lightweight scrutiny.
- **Tier C — low:** dev/test/local tooling only. Minimal scrutiny — **but** note: anything that runs in CI executes with CI privileges and is therefore **Tier A**, not C.

### 4.3 Language Guidance (applies once you are in a language — not a ranking)

- **Go:** stdlib covers most needs (`net/http`+`ServeMux`, `encoding/json`, `database/sql`, `html/template`, `log/slog`, `context`, `errors`). Add frameworks only for real complexity.
- **Python:** stdlib for trivial work. **For HTTP with auth/proxies/retries/untrusted endpoints, use `requests`/`httpx`** — hand-rolled `urllib` (no default timeout → hang/DoS) is the larger risk. Prefer wheels over sdists (sdist `setup.py` executes at install).
- **.NET:** in-runtime BCL / in-box ASP.NET Core are low marginal risk. Registry NuGet — including Microsoft-published — gets §4.7 evaluation; verify signing.
- **Rust:** stdlib where viable; foundational audited crates otherwise. **Review every `build.rs` and proc-macro** (compile-time code execution). Enforcement in §4.9 is mandatory.
- **Browser/JS:** browser tooling should be proportional to application complexity. Full SPA frameworks require explicit justification because they introduce substantial build-chain and dependency surface. A Node toolchain runs only under §4.9 npm controls.

### 4.4 Code You Must Not Hand-Roll (three distinct categories)

**4.4a. Security-critical — ABSOLUTE BAN regardless of how the need is labeled.** Reclassifying these as "operational" to dodge the rule is a violation.

- Cryptography, signing, key generation, secure RNG
- TLS / certificate validation
- Password hashing (argon2/bcrypt/scrypt via vetted libs)
- JWT / OAuth / session-token validation
- Sanitization / escaping / parsers for **untrusted** input (HTTP, XML, YAML, HTML, SQL)

**4.4b. Protocol-complex — strong default to a library; hand-rolling needs justification.**

- Date/time/timezone arithmetic; charset/encoding handling; parsers for *trusted* structured input

**4.4c. Operational convenience — hand-rolling is FINE; adding a dependency for these is usually anti-trust-minimization.**

- Retry/backoff loops, simple connection reuse, small utility helpers. (Connection pooling is normally provided by the §4.4a HTTP/TLS client you already use.)

Pasting unprovenanced code to satisfy 4.4a is **worse** than a dependency (zero scrutiny, zero CVE coverage) — forbidden. See §4.5c.

### 4.5 Governed Code Sources (all are trust relationships)

**4.5a. Registry dependencies** — §4.7 evaluation by tier; pinned with integrity hashes; enforced in §4.9.

**4.5b. Git / repo / submodule dependencies** — registry scanners are blind to these (advisories key on registry versions), so they are a permanent known-vuln blind spot.

- Mutable refs (branch, tag) are **banned** — full commit SHA only.
- Require explicit approval + a stated reason the registry version is insufficient.
- Track advisories manually; revisit on a schedule.

**4.5c. Copied / generated code** (StackOverflow, gists, blogs, docs, **another AI model**, this agent's own output) — a trust relationship that bypasses every gate: unversioned, unscanned, no CVE alerts, invisible to dependency-review.

- Any non-trivial copied/generated block must be cited (source + reason) in the ledger (§4.12).
- Reviewed as if it were a dependency.
- **Never** used for §4.4a primitives. Security-critical generated code requires human review before merge.

### 4.6 Code-Execution Control (Tier A by definition)

Every vector below executes unreviewed code, often with more privilege than a runtime dependency:

- **npm lifecycle scripts** → install with scripts disabled (§4.9).
- **Rust `build.rs` + proc-macros** → review before adding; detect automatically (§4.9).
- **Python sdists / `setup.py`** → prefer pre-built wheels; audit native ones.
- **Code generators** → pin versions; review output.
- **Docker `RUN` / base images** → pin base by digest **and** verify signature + scan (§4.8).
- **`curl | bash` installers** → **banned.** Download, inspect, pin by hash, then run.
- **Binary / prebuilt artifacts** → verify checksum + signature; never trust unverified.

Build-time secrets must be scoped to the minimum (§4.1.3) so a malicious build script reaches nothing valuable.

### 4.7 Trust Scoring (objective; mandatory thresholds for Tier A only)

Score each Tier A dependency on objective signals; record in the ledger:

- Release cadence (recent, regular)
- Maintainer count (bus-factor > 1 preferred)
- Contributor activity (active vs abandoned)
- Direct **and transitive** dependency count
- Executes at install/build? (yes = elevated scrutiny)
- Open known/critical advisories (must be zero to adopt)
- Signing / provenance available?
- Independent-scrutiny breadth (adoption)

**Tier A gate (mandatory):** zero open critical advisories; actively maintained (no release in 24 months = treated as abandoned unless explicitly justified); provenance verifiable or vendored-with-controls; transitive tree reviewed. Tier B/C: lightweight, no mandatory rubric — proportionality (§4.1.1).

### 4.8 Containers & Artifacts

Digest-pinning gives immutability, **not** trustworthiness — you can pin a backdoored image. Required:

- **Verify signatures** before pull/deploy (cosign / Sigstore policy).
- **Scan** images and release artifacts (Trivy/Grype/osv-scanner) in CI; fail on critical.
- **Generate + store SBOMs** (syft) for images and releases.
- Prefer **distroless/minimal** bases.
- **Verify checksum + signature on consumption** of any downloaded artifact.

### 4.9 CI/CD & Repository Governance (the spine — without this, everything above is bypassable)

**Repository governance (makes every other control binding):**

- Branch protection on default branch; no direct pushes; required reviews.
- **CODEOWNERS on dependency manifests, lockfiles, every enforcement config (`cargo-deny`, allowlists), and `.github/workflows/`** — so risk and the control that would catch it can't be changed in the same unreviewed PR.
- Verified/signed commits preferred.
- Required, **non-bypassable** status checks.

**CI/CD hardening:**

- Pin GitHub Actions to **full commit SHA**, enforced by lint (zizmor/ratchet) — mutable tags have been weaponized.
- Minimal `permissions:` per workflow/job; default read-only; scoped, short-lived tokens.
- Ephemeral, isolated, sandboxed runners; restricted egress.
- Emit + verify provenance (SLSA, `actions/attest-build-provenance`, cosign).

**Enforced control matrix (minimum bar = committed lockfile + locked install + CI vuln scan that fails the build):**

| Concern | Go | Python | Rust | .NET | npm (if unavoidable) |
|---|---|---|---|---|---|
| Lockfile committed | `go.mod`/`go.sum` | hashed reqs (uv/pip-tools) | `Cargo.lock` | `packages.lock.json` | `package-lock.json` |
| Locked install | `-mod=readonly` | `pip --require-hashes` | `cargo build --locked` | `restore --locked-mode` | `npm ci --ignore-scripts` |
| Vuln scan | `govulncheck` | `pip-audit` | `cargo audit` | `list package --vulnerable` | `npm audit`/`osv-scanner` |
| Policy gate | — | — | `cargo deny check` | NuGet trusted-signers | `socket.dev` |
| Cross-cutting | `osv-scanner` over full tree; Dependabot/Renovate for update visibility; **scheduled** scans (not just on PR); dependency-review gate on PRs; Sigstore verification on artifacts | | | | |

**Currency (measurable):** scheduled scans so dormant repos are still re-checked; automated update PRs with a max-staleness SLA; **any CISA KEV-listed vulnerability must be remediated within the defined window regardless of CVSS — as must critical CVEs — or the build fails.**

**Vendored browser libs:** allowed only with a manifest (version + upstream URL + SHA-256), SRI in HTML, and a CI drift-check — the drift-check workflow itself protected by CODEOWNERS.

### 4.10 Runtime & Operational Trust (beyond build time)

These are trust relationships even though they aren't "dependencies":

- **External APIs / SaaS:** scope credentials, limit egress, treat responses as untrusted input, have a failure mode.
- **Model / code-generation providers (incl. this agent):** can inject backdoored code — governed by §4.5c; security-critical output gets human review.
- **Telemetry / analytics SDKs:** data-exfiltration vector; minimize, audit, prefer first-party-runtime.
- **Cloud build infrastructure:** part of the trusted base; apply §4.9 hardening.

### 4.11 Enforcement Reality (target state)

Move controls left: trust thresholds → `cargo-deny`/dependency-review/allowlist config; currency → scheduled scans + KEV SLA; action-pinning → CI lint; never-hand-roll-crypto → review gate on §4.4a paths. Target: majority of the directive enforced automatically; human judgment reserved for Tier A adoption decisions and §4.5c security-critical review.

### 4.12 Agent Rules & Ledger

- Optimize auditable trust surface and blast radius, **not** dependency count. If a rule would make code less safe, the rule loses — flag it.
- Never satisfy a constraint by hand-rolling §4.4a, pasting unprovenanced code for §4.4a, or mislabeling a tier.
- Never pin to a known-vulnerable version to avoid change. Never introduce a git/branch dep, a code-execution vector (§4.6), a new Action, or a runtime without surfacing it.
- Never weaken an enforcement config or workflow in a change that also adds a dependency or code-execution vector.

**Trust & Execution Ledger** (end of any task touching deps, code sources, artifacts, or CI). Scope it to the highest tier touched (§4.2) so signal isn't drowned in noise:

- **Tier A → full ledger:**
  - **Dependencies:** package, version, tier, integrity-hash status, direct+transitive count, justification.
  - **Other code sources:** git deps (with SHA + approval), copied/generated blocks (source + reason).
  - **Code execution introduced:** install/build scripts, `build.rs`, proc-macros, native wheels, Docker `RUN`, Actions, downloaded binaries — and how each was verified.
  - **Blast radius:** secrets/tokens/network the new code can reach.
  - **Enforcement status:** §4.9 controls present vs missing for the touched language.
- **Tier B → abbreviated:** one line per change — package/source, version, and justification. Flag any code execution or git dep, but skip the full breakdown.
- **Tier C → omit**, unless something executes in CI (which makes it Tier A — see §4.2) or a §4.4a/§4.5b/§4.6 concern is present, in which case escalate to the full ledger.

---

### 4.13 Applying This Directive to QueryGateway (current state)

QueryGateway is a two-runtime repository — **Python** (FastAPI backend) and
**browser/JS** (Vite + React SPA) — packaged with **Docker**. Per principle 7
of §4.1 (minimize runtime sprawl), no additional runtime should be introduced
without a compelling justification. The
following gaps between this directive and the current CI
(`.github/workflows/`) are tracked as the supply-chain hardening backlog:

| §4.9 control | Python (`backend/`) | Frontend (`frontend/`) | Docker (`docker/`) |
|---|---|---|---|
| Lockfile committed | hash-pinned `requirements.lock` (uv `--generate-hashes`) ✅ | `package-lock.json` ✅ | base images digest-pinned (`@sha256`) ✅ |
| Locked install | `pip install --require-hashes` (CI + image) ✅ | `npm ci --ignore-scripts` (CI + image) ✅ | — |
| Vuln scan in CI | `pip-audit` build-failing ✅ + weekly `osv-scanner` | `npm audit --audit-level=high` build-failing ✅ + weekly `osv-scanner` | Trivy, fail on CRITICAL ✅ |
| Actions SHA-pinned | full commit SHA + pin lint ✅ | full commit SHA + pin lint ✅ | full commit SHA + pin lint ✅ |
| SBOM / signing | covered by image SBOM | covered by image SBOM | SBOM (syft, SPDX) per image ✅; image signing — not yet |

Status: the supply-chain hardening backlog is implemented in CI. Workflows:
`backend.yml`, `frontend.yml`, `docker.yml` (build + Trivy + SBOM),
`actions-lint.yml` (SHA-pin lint), `security-scan.yml` (weekly pip-audit /
npm audit / osv-scanner), and `dependency-review.yml` (per-PR delta gate).
`.github/CODEOWNERS` and `.github/dependabot.yml` are in place.

Remaining (require repo-admin, not settable from code — see
[`docs/repository_governance.md`](docs/repository_governance.md)):

1. Enable branch protection on `main` with the new checks as **required,
   non-bypassable** status checks, plus required Code Owner review.
2. Enable the repository **Dependency graph** (so `dependency-review` passes)
   and **Dependabot alerts** / secret scanning.
3. **Image signing + provenance** (cosign / Sigstore attestation) — not yet
   implemented; the images are scanned and have SBOMs but are not signed.
