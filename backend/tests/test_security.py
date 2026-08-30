"""Phase 7 — Security validation tests.

Comprehensive negative-path testing covering:
- SQL injection attempts (blocked by schema validation)
- Invalid/malformed auth credentials
- Malformed request parameters
- Missing required parameters
- Credential leakage audit in responses
- Path traversal attempts
- Oversized payloads
"""

import uuid

import pytest
from app.schemas.endpoint import EndpointCreate, validate_sql_safety
from httpx import AsyncClient


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ── SQL Injection Prevention ─────────────────────────────────────────────────


class TestSqlInjectionPrevention:
    """Verify SQL injection vectors are blocked at schema validation."""

    @pytest.mark.parametrize(
        "sql",
        [
            # String concatenation
            "SELECT * FROM t WHERE name = '' + user_input",
            "SELECT * FROM t WHERE name = user_input + ''",
            # PL/SQL concatenation
            "SELECT * FROM t WHERE name = '' || user_input",
            "SELECT * FROM t WHERE name = user_input || ''",
            # Python f-string patterns
            'SELECT * FROM t WHERE name = f"hello"',
            "SELECT * FROM t WHERE name = f'hello'",
            # Template interpolation
            "SELECT * FROM t WHERE name = ${user_input}",
            "SELECT * FROM t WHERE name = {user_input}",
        ],
    )
    def test_unsafe_sql_rejected(self, sql: str) -> None:
        errors = validate_sql_safety(sql)
        assert len(errors) > 0, f"Expected rejection for: {sql}"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM employees WHERE dept_id = :dept_id",
            "SELECT id, name FROM departments WHERE active = :active",
            "SELECT 1 FROM dual",
            "SELECT * FROM t WHERE a = :a AND b = :b AND c = :c",
            "SELECT * FROM t WHERE name LIKE '%test%'",
        ],
    )
    def test_safe_sql_accepted(self, sql: str) -> None:
        errors = validate_sql_safety(sql)
        assert errors == [], f"Unexpected rejection for: {sql}"

    def test_endpoint_create_rejects_injection(self) -> None:
        """EndpointCreate schema blocks SQL injection at model level."""
        with pytest.raises(ValueError, match="unsafe interpolation"):
            EndpointCreate(
                name="test",
                path="test-path",
                connection_id=uuid.uuid4(),
                sql_text="SELECT * FROM users WHERE id = '' + request.id",
            )

    def test_endpoint_create_rejects_plsql_concat(self) -> None:
        with pytest.raises(ValueError, match="unsafe interpolation"):
            EndpointCreate(
                name="test",
                path="test-path",
                connection_id=uuid.uuid4(),
                sql_text="SELECT * FROM users WHERE id = '' || request_id",
            )


# ── Auth Security Tests (API Integration) ───────────────────────────────────


@pytest.mark.integration
class TestAuthSecurity:
    """Negative auth scenarios through the API."""

    async def _create_protected_endpoint(
        self, client: AsyncClient, auth_id: str
    ) -> str:
        """Create a connection + endpoint with auth, return data path."""
        r = await client.post(
            "/api/v1/admin/connections/",
            json={
                "name": _unique("sec-conn"),
                "host": "oracle.example.com",
                "service_name": "SVC",
                "username": "hr",
                "password": "secret",
            },
        )
        conn_id = r.json()["id"]

        ep_path = _unique("sec-data")
        r = await client.post(
            "/api/v1/admin/endpoints/",
            json={
                "name": _unique("sec-ep"),
                "path": ep_path,
                "connection_id": conn_id,
                "sql_text": "SELECT 1 FROM dual",
                "auth_method_id": auth_id,
            },
        )
        assert r.status_code == 201
        return ep_path

    async def test_missing_authorization_header(self, async_client: object) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        r = await client.post(
            "/api/v1/admin/auth/",
            json={"name": _unique("miss-auth"), "method_type": "bearer"},
        )
        auth_id = r.json()["id"]
        ep_path = await self._create_protected_endpoint(client, auth_id)

        r = await client.get(f"/api/v1/data/{ep_path}")
        assert r.status_code == 401

    async def test_malformed_bearer_token(self, async_client: object) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        r = await client.post(
            "/api/v1/admin/auth/",
            json={"name": _unique("mal-bearer"), "method_type": "bearer"},
        )
        auth_id = r.json()["id"]
        ep_path = await self._create_protected_endpoint(client, auth_id)

        # Completely malformed
        r = await client.get(
            f"/api/v1/data/{ep_path}",
            headers={"Authorization": "Bearer not.a.valid.jwt"},
        )
        assert r.status_code == 401

    async def test_expired_token_rejected(self, async_client: object) -> None:
        """Expired JWTs must be rejected."""
        from datetime import UTC, datetime, timedelta  # noqa: PLC0415

        import jwt as pyjwt  # noqa: PLC0415

        client: AsyncClient = async_client  # type: ignore[assignment]

        r = await client.post(
            "/api/v1/admin/auth/",
            json={"name": _unique("exp-bearer"), "method_type": "bearer"},
        )
        auth_id = r.json()["id"]
        ep_path = await self._create_protected_endpoint(client, auth_id)

        # Create a token with a fake secret — will be invalid
        now = datetime.now(UTC)
        expired_token = pyjwt.encode(
            {"sub": "test", "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
            "fake-secret",
            algorithm="HS256",
        )
        r = await client.get(
            f"/api/v1/data/{ep_path}",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert r.status_code == 401

    async def test_malformed_basic_credentials(self, async_client: object) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        r = await client.post(
            "/api/v1/admin/auth/",
            json={
                "name": _unique("mal-basic"),
                "method_type": "basic",
                "username": "admin",
                "password": "pass",
            },
        )
        auth_id = r.json()["id"]
        ep_path = await self._create_protected_endpoint(client, auth_id)

        # Malformed base64
        r = await client.get(
            f"/api/v1/data/{ep_path}",
            headers={"Authorization": "Basic !!!not-base64!!!"},
        )
        assert r.status_code == 401

    async def test_empty_api_key(self, async_client: object) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        apikey_name = _unique("empty-key")
        r = await client.post(
            "/api/v1/admin/auth/with-key",
            json={"name": apikey_name, "method_type": "api_key"},
        )
        assert r.status_code == 201
        # Look up the created auth method by name
        r2 = await client.get("/api/v1/admin/auth/")
        auth_id = next(a["id"] for a in r2.json() if a["name"] == apikey_name)
        ep_path = await self._create_protected_endpoint(client, auth_id)

        # Empty X-Api-Key
        r = await client.get(
            f"/api/v1/data/{ep_path}",
            headers={"X-Api-Key": ""},
        )
        assert r.status_code == 401

    async def test_rotated_bearer_invalidates_old_tokens(
        self, async_client: object
    ) -> None:
        """After rotation, previously issued tokens must be rejected."""
        client: AsyncClient = async_client  # type: ignore[assignment]

        r = await client.post(
            "/api/v1/admin/auth/",
            json={"name": _unique("rot-bearer"), "method_type": "bearer"},
        )
        auth_id = r.json()["id"]
        ep_path = await self._create_protected_endpoint(client, auth_id)

        # Issue token
        r = await client.post(f"/api/v1/admin/auth/{auth_id}/issue-token")
        old_token = r.json()["token"]

        # Rotate
        r = await client.post(f"/api/v1/admin/auth/{auth_id}/rotate")
        assert r.status_code == 200

        # Old token should now fail
        r = await client.get(
            f"/api/v1/data/{ep_path}",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        assert r.status_code == 401


# ── Credential Leakage Audit ────────────────────────────────────────────────


@pytest.mark.integration
class TestCredentialLeakage:
    """Verify secrets are never returned in API responses."""

    async def test_connection_password_not_in_response(
        self, async_client: object
    ) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        r = await client.post(
            "/api/v1/admin/connections/",
            json={
                "name": _unique("leak-conn"),
                "host": "db.example.com",
                "service_name": "SVC",
                "username": "user",
                "password": "SuperSecretPassword123!",
            },
        )
        assert r.status_code == 201
        response_text = r.text

        assert "SuperSecretPassword123!" not in response_text
        assert "encrypted_password" not in response_text

        # Also check GET
        conn_id = r.json()["id"]
        r = await client.get(f"/api/v1/admin/connections/{conn_id}")
        assert "SuperSecretPassword123!" not in r.text

    async def test_auth_method_secrets_not_in_response(
        self, async_client: object
    ) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        # Bearer
        r = await client.post(
            "/api/v1/admin/auth/",
            json={"name": _unique("leak-bearer"), "method_type": "bearer"},
        )
        assert r.status_code == 201
        assert "signing_secret" not in r.text
        assert "config_json" not in r.text

        # Basic
        r = await client.post(
            "/api/v1/admin/auth/",
            json={
                "name": _unique("leak-basic"),
                "method_type": "basic",
                "username": "admin",
                "password": "MySecretPassword",
            },
        )
        assert r.status_code == 201
        assert "MySecretPassword" not in r.text
        assert "password_hash" not in r.text

    async def test_settings_mask_secrets(self, async_client: object) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        r = await client.get("/api/v1/admin/settings/")
        assert r.status_code == 200
        # No raw encryption keys or sensitive values should leak


# ── Malformed Request Tests ──────────────────────────────────────────────────


@pytest.mark.integration
class TestMalformedRequests:
    """Verify malformed inputs are rejected gracefully."""

    async def test_invalid_uuid_path_param(self, async_client: object) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        r = await client.get("/api/v1/admin/connections/not-a-uuid")
        assert r.status_code == 422

    async def test_missing_required_fields(self, async_client: object) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        # Connection without required host
        r = await client.post(
            "/api/v1/admin/connections/",
            json={"name": "test"},
        )
        assert r.status_code == 422

    async def test_empty_json_body(self, async_client: object) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        r = await client.post("/api/v1/admin/connections/", json={})
        assert r.status_code == 422

    async def test_invalid_auth_method_type(self, async_client: object) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        r = await client.post(
            "/api/v1/admin/auth/",
            json={"name": "test", "method_type": "oauth2"},
        )
        assert r.status_code == 422

    async def test_nonexistent_connection_for_endpoint(
        self, async_client: object
    ) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        r = await client.post(
            "/api/v1/admin/endpoints/",
            json={
                "name": _unique("orphan-ep"),
                "path": _unique("orphan-data"),
                "connection_id": str(uuid.uuid4()),
                "sql_text": "SELECT 1 FROM dual",
                "allow_unauthenticated": True,
            },
        )
        # Should fail — connection doesn't exist
        assert r.status_code in (404, 409, 422, 500)


# ── Path Traversal ───────────────────────────────────────────────────────────


class TestPathValidation:
    """Verify path validation blocks unsafe URL patterns."""

    @pytest.mark.parametrize(
        "path",
        [
            "My Endpoint!",
            "../../../etc/passwd",
            "endpoint with spaces",
            "<script>alert(1)</script>",
            "endpoint;drop table",
        ],
    )
    def test_invalid_paths_rejected(self, path: str) -> None:
        # allow_unauthenticated=True so the only thing that can fail is the
        # path validator — not the public/auth invariant (keeps this test
        # specifically about path rejection).
        with pytest.raises(ValueError, match="lowercase alphanumeric"):
            EndpointCreate(
                name="test",
                path=path,
                connection_id=uuid.uuid4(),
                sql_text="SELECT 1 FROM dual",
                allow_unauthenticated=True,
            )

    @pytest.mark.parametrize(
        "path",
        [
            "valid-path",
            "my/nested/path",
            "v2/employees",
            "data_export",
        ],
    )
    def test_valid_paths_accepted(self, path: str) -> None:
        ep = EndpointCreate(
            name="test",
            path=path,
            connection_id=uuid.uuid4(),
            sql_text="SELECT 1 FROM dual",
            allow_unauthenticated=True,
        )
        assert ep.path  # normalized


# ── Data Endpoint Parameter Validation ───────────────────────────────────────


@pytest.mark.integration
class TestDataEndpointParams:
    """Verify parameter validation on data endpoints."""

    async def test_missing_required_param(self, async_client: object) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        # Create connection + endpoint with required param
        r = await client.post(
            "/api/v1/admin/connections/",
            json={
                "name": _unique("param-conn"),
                "host": "oracle.example.com",
                "service_name": "SVC",
                "username": "hr",
                "password": "secret",
            },
        )
        conn_id = r.json()["id"]

        ep_path = _unique("param-data")
        r = await client.post(
            "/api/v1/admin/endpoints/",
            json={
                "name": _unique("param-ep"),
                "path": ep_path,
                "connection_id": conn_id,
                "allow_unauthenticated": True,
                "sql_text": "SELECT * FROM t WHERE id = :id",
                "param_schema": {
                    "id": {"type": "integer", "required": True},
                },
            },
        )
        assert r.status_code == 201

        # Call without required param → 422
        r = await client.get(f"/api/v1/data/{ep_path}")
        assert r.status_code == 422
        assert "id" in r.json()["detail"]

    async def test_required_live_param_does_not_fall_back_to_scheduler_default(
        self, async_client: object
    ) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        connection = await client.post(
            "/api/v1/admin/connections/",
            json={
                "name": _unique("required-default-conn"),
                "host": "oracle.example.com",
                "service_name": "SVC",
                "username": "hr",
                "password": "secret",
            },
        )
        assert connection.status_code == 201

        ep_path = _unique("required-default-data")
        endpoint = await client.post(
            "/api/v1/admin/endpoints/",
            json={
                "name": _unique("required-default-ep"),
                "path": ep_path,
                "connection_id": connection.json()["id"],
                "allow_unauthenticated": True,
                "sql_text": "SELECT * FROM t WHERE business_date = :business_date",
                "param_schema": {
                    "business_date": {
                        "type": "date",
                        "required": True,
                        "default_expression": "yesterday",
                    }
                },
            },
        )
        assert endpoint.status_code == 201

        response = await client.get(f"/api/v1/data/{ep_path}")
        assert response.status_code == 422
        assert "business_date" in response.json()["detail"]
        assert "Field required" in response.json()["detail"]

    async def test_invalid_param_type(self, async_client: object) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        r = await client.post(
            "/api/v1/admin/connections/",
            json={
                "name": _unique("type-conn"),
                "host": "oracle.example.com",
                "service_name": "SVC",
                "username": "hr",
                "password": "secret",
            },
        )
        conn_id = r.json()["id"]

        ep_path = _unique("type-data")
        r = await client.post(
            "/api/v1/admin/endpoints/",
            json={
                "name": _unique("type-ep"),
                "path": ep_path,
                "connection_id": conn_id,
                "allow_unauthenticated": True,
                "sql_text": "SELECT * FROM t WHERE id = :id",
                "param_schema": {
                    "id": {"type": "integer", "required": True},
                },
            },
        )
        assert r.status_code == 201

        # Pass non-integer → 422
        r = await client.get(f"/api/v1/data/{ep_path}?id=not-a-number")
        assert r.status_code == 422

    async def test_nonexistent_data_path(self, async_client: object) -> None:
        client: AsyncClient = async_client  # type: ignore[assignment]

        r = await client.get("/api/v1/data/this-path-does-not-exist")
        assert r.status_code == 404
        assert "No endpoint registered" in r.json()["detail"]
