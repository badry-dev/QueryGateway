"""Mandatory authentication for every dynamic data endpoint.

The legacy ``allow_unauthenticated`` field is retained for stored/API contract
compatibility, but now opts into platform-admin Bearer fallback. It never
permits anonymous data access.
"""

import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from app.auth.jwt_utils import create_access_token
from app.config import settings
from app.schemas.endpoint import EndpointCreate
from app.services.data import DataService
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ── Schema-level guard (unit) ────────────────────────────────────────────────


def test_create_without_auth_or_optin_rejected() -> None:
    """No auth method and no explicit opt-in must be rejected at the schema."""
    with pytest.raises(ValueError, match="allow_unauthenticated"):
        EndpointCreate(
            name="t",
            path="p",
            connection_id=uuid.uuid4(),
            sql_text="SELECT 1 FROM dual",
        )


def test_create_platform_auth_fallback_allowed() -> None:
    """No endpoint method plus explicit platform fallback remains valid."""
    ep = EndpointCreate(
        name="t",
        path="p",
        connection_id=uuid.uuid4(),
        sql_text="SELECT 1 FROM dual",
        allow_unauthenticated=True,
    )
    assert ep.allow_unauthenticated is True


def test_create_with_auth_method_allowed() -> None:
    """Attaching an auth method satisfies the invariant without the flag."""
    ep = EndpointCreate(
        name="t",
        path="p",
        connection_id=uuid.uuid4(),
        sql_text="SELECT 1 FROM dual",
        auth_method_id=uuid.uuid4(),
    )
    assert ep.allow_unauthenticated is False


@pytest.mark.asyncio
async def test_data_service_rejects_anonymous_legacy_public_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DataService(cast(AsyncSession, object()))
    endpoint = SimpleNamespace(
        id=uuid.uuid4(),
        auth_method_id=None,
        allow_unauthenticated=True,
        data_strategy=SimpleNamespace(value="snapshot"),
    )
    monkeypatch.setattr(service, "_resolve_endpoint", AsyncMock(return_value=endpoint))
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/data/legacy-public",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "scheme": "http",
            "root_path": "",
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.serve("legacy-public", request)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_data_service_accepts_platform_auth_for_legacy_public_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = DataService(cast(AsyncSession, object()))
    endpoint = SimpleNamespace(
        id=uuid.uuid4(),
        auth_method_id=None,
        allow_unauthenticated=True,
        data_strategy=SimpleNamespace(value="snapshot"),
    )
    monkeypatch.setattr(service, "_resolve_endpoint", AsyncMock(return_value=endpoint))
    serve_snapshot = AsyncMock(return_value=JSONResponse(status_code=503, content={}))
    monkeypatch.setattr(service, "_serve_snapshot", serve_snapshot)
    token, _ = create_access_token(
        subject=settings.admin_username,
        secret=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expire_minutes=5,
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/data/legacy-public",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
            "scheme": "http",
            "root_path": "",
        }
    )

    result = await service.serve("legacy-public", request)

    assert result.principal == settings.admin_username
    serve_snapshot.assert_awaited_once()


# ── API integration ──────────────────────────────────────────────────────────


async def _make_connection(client: AsyncClient) -> str:
    r = await client.post(
        "/api/v1/admin/connections/",
        json={
            "name": _unique("pub-conn"),
            "host": "oracle.example.com",
            "service_name": "SVC",
            "username": "hr",
            "password": "secret",
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


@pytest.mark.integration
async def test_create_endpoint_no_auth_returns_422(async_client: object) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    conn_id = await _make_connection(client)

    r = await client.post(
        "/api/v1/admin/endpoints/",
        json={
            "name": _unique("pub-ep"),
            "path": _unique("pub-data"),
            "connection_id": conn_id,
            "sql_text": "SELECT 1 FROM dual",
            # No auth_method_id and allow_unauthenticated defaults to False.
        },
    )
    assert r.status_code == 422
    body = r.text
    assert "allow_unauthenticated" in body


@pytest.mark.integration
async def test_create_explicit_public_endpoint_201(async_client: object) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    conn_id = await _make_connection(client)

    r = await client.post(
        "/api/v1/admin/endpoints/",
        json={
            "name": _unique("pub-ep"),
            "path": _unique("pub-data"),
            "connection_id": conn_id,
            "sql_text": "SELECT 1 FROM dual",
            "allow_unauthenticated": True,
        },
    )
    assert r.status_code == 201
    assert r.json()["allow_unauthenticated"] is True


@pytest.mark.integration
async def test_update_detaching_auth_without_optin_returns_422(
    async_client: object,
) -> None:
    """Removing the auth method without opting into public access is rejected."""
    client: AsyncClient = async_client  # type: ignore[assignment]
    conn_id = await _make_connection(client)

    # Create a protected endpoint.
    r = await client.post(
        "/api/v1/admin/auth/",
        json={"name": _unique("pub-auth"), "method_type": "bearer"},
    )
    auth_id = r.json()["id"]
    r = await client.post(
        "/api/v1/admin/endpoints/",
        json={
            "name": _unique("pub-ep"),
            "path": _unique("pub-data"),
            "connection_id": conn_id,
            "sql_text": "SELECT 1 FROM dual",
            "auth_method_id": auth_id,
        },
    )
    assert r.status_code == 201
    ep_id = r.json()["id"]

    # Detach the auth method without opting into public access → 422.
    r = await client.put(
        f"/api/v1/admin/endpoints/{ep_id}",
        json={"auth_method_id": None},
    )
    assert r.status_code == 422

    # Detaching while opting in is allowed.
    r = await client.put(
        f"/api/v1/admin/endpoints/{ep_id}",
        json={"auth_method_id": None, "allow_unauthenticated": True},
    )
    assert r.status_code == 200
    assert r.json()["allow_unauthenticated"] is True


@pytest.mark.integration
async def test_legacy_public_endpoint_requires_platform_authentication(
    async_client: object, unauth_client: AsyncClient
) -> None:
    """The legacy public flag never permits anonymous data access."""
    admin: AsyncClient = async_client  # type: ignore[assignment]
    conn_id = await _make_connection(admin)

    ep_path = _unique("pub-data")
    r = await admin.post(
        "/api/v1/admin/endpoints/",
        json={
            "name": _unique("pub-ep"),
            "path": ep_path,
            "connection_id": conn_id,
            "sql_text": "SELECT 1 FROM dual",
            "data_strategy": "snapshot",
            "allow_unauthenticated": True,
        },
    )
    assert r.status_code == 201

    with capture_logs() as logs:
        resp = await unauth_client.get(f"/api/v1/data/{ep_path}")

    assert resp.status_code == 401
    denials = [e for e in logs if e.get("event") == "unauthenticated_endpoint_denied"]
    assert denials, f"expected unauthenticated_endpoint_denied, got {logs}"
    assert not any(e.get("event") == "public_endpoint_served" for e in logs)

    # The shared admin client carries a valid platform bearer token. It reaches
    # the snapshot path and returns 503 only because no snapshot exists yet.
    authenticated = await admin.get(f"/api/v1/data/{ep_path}")
    assert authenticated.status_code == 503

    authorization = admin.headers["Authorization"]
    token = authorization.removeprefix("Bearer ")
    whitespace_authenticated = await unauth_client.get(
        f"/api/v1/data/{ep_path}",
        headers={"Authorization": f"Bearer   {token}  "},
    )
    assert whitespace_authenticated.status_code == 503


@pytest.mark.integration
async def test_deleting_auth_method_default_denies_endpoint(
    async_client: object, unauth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Deleting an auth method that an endpoint references (FK ondelete=SET NULL)
    must NOT make the endpoint public — it default-denies with 401. Closes the
    M1 side-channel where a protected endpoint could silently become public."""
    admin: AsyncClient = async_client  # type: ignore[assignment]
    conn_id = await _make_connection(admin)

    r = await admin.post(
        "/api/v1/admin/auth/",
        json={"name": _unique("orphan-auth"), "method_type": "bearer"},
    )
    auth_id = r.json()["id"]
    ep_path = _unique("orphan-data")
    r = await admin.post(
        "/api/v1/admin/endpoints/",
        json={
            "name": _unique("orphan-ep"),
            "path": ep_path,
            "connection_id": conn_id,
            "sql_text": "SELECT 1 FROM dual",
            "data_strategy": "snapshot",
            "auth_method_id": auth_id,
        },
    )
    assert r.status_code == 201

    # Delete the auth method → the FK ondelete=SET NULL orphans the endpoint.
    r = await admin.delete(f"/api/v1/admin/auth/{auth_id}")
    assert r.status_code == 204
    # The shared test session caches the endpoint with its old auth_method_id;
    # drop the cache so the next read reflects the DB-side SET NULL (production
    # opens a fresh session per request).
    db_session.expire_all()

    with capture_logs() as logs:
        resp = await unauth_client.get(f"/api/v1/data/{ep_path}")

    assert resp.status_code == 401  # default-deny, NOT served publicly
    denials = [e for e in logs if e.get("event") == "unauthenticated_endpoint_denied"]
    assert denials, f"expected unauthenticated_endpoint_denied, got {logs}"
    # The deny event must be self-contained for audit (§3.5): the same
    # mandatory fields that public_endpoint_served carries must be present so
    # the denial is independently traceable.
    assert denials[0]["endpoint"] == ep_path
    assert denials[0]["status"] == 401
    assert denials[0]["user"] == "anonymous"
    assert denials[0]["method"] == "GET"
    assert "request_id" in denials[0]
    assert "client_ip" in denials[0]
    assert "duration_ms" in denials[0]
    assert not any(e.get("event") == "public_endpoint_served" for e in logs)

    # A valid platform-admin token must not bypass an orphaned endpoint's
    # explicit fallback setting. The administrator must repair the endpoint
    # configuration before data access resumes.
    authenticated = await admin.get(f"/api/v1/data/{ep_path}")
    assert authenticated.status_code == 401
