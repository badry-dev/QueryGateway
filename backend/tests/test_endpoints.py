"""Tests for endpoint management — schemas, service, and API layer.

Integration tests (requiring PostgreSQL) are marked with @pytest.mark.integration
and run in CI where the service is available.

Unit tests exercise schema validation, SQL safety, and bind parameter extraction.
"""

import uuid

import pytest
from app.models.endpoint import DataStrategy
from app.schemas.endpoint import (
    EndpointCreate,
    EndpointResponse,
    EndpointUpdate,
    ParamDescriptor,
    SnapshotConfigurationError,
    SqlPreviewRequest,
    extract_bind_params,
    require_snapshot_defaults,
    validate_sql_safety,
)

# ── SQL safety unit tests ────────────────────────────────────────────────────


def test_extract_bind_params_basic() -> None:
    sql = "SELECT * FROM employees WHERE dept_id = :dept_id AND status = :status"
    params = extract_bind_params(sql)
    assert params == ["dept_id", "status"]


def test_extract_bind_params_deduplicates() -> None:
    sql = "SELECT * FROM t WHERE a = :x AND b = :x"
    params = extract_bind_params(sql)
    assert params == ["x"]


def test_extract_bind_params_ignores_strings() -> None:
    sql = "SELECT * FROM t WHERE name = :name AND label = ':not_a_param'"
    params = extract_bind_params(sql)
    assert params == ["name"]


def test_extract_bind_params_empty() -> None:
    sql = "SELECT 1 FROM dual"
    params = extract_bind_params(sql)
    assert params == []


def test_validate_sql_safety_clean() -> None:
    sql = "SELECT * FROM employees WHERE id = :emp_id"
    errors = validate_sql_safety(sql)
    assert errors == []


def test_validate_sql_safety_string_concat() -> None:
    sql = "SELECT * FROM employees WHERE name = '' + user_input"
    errors = validate_sql_safety(sql)
    assert len(errors) > 0


def test_validate_sql_safety_fstring() -> None:
    sql = 'SELECT * FROM employees WHERE name = f"hello"'
    errors = validate_sql_safety(sql)
    assert len(errors) > 0


def test_validate_sql_safety_template() -> None:
    sql = "SELECT * FROM employees WHERE name = ${user_input}"
    errors = validate_sql_safety(sql)
    assert len(errors) > 0


# ── Schema validation unit tests ─────────────────────────────────────────────


def test_endpoint_create_valid() -> None:
    conn_id = uuid.uuid4()
    payload = EndpointCreate(
        name="test-endpoint",
        path="employees",
        connection_id=conn_id,
        sql_text="SELECT * FROM employees WHERE dept_id = :dept_id",
        param_schema={"dept_id": {"type": "integer", "required": True}},
        allow_unauthenticated=True,
    )
    assert payload.name == "test-endpoint"
    assert payload.path == "employees"
    assert payload.connection_id == conn_id


def test_date_parameter_accepts_dynamic_default() -> None:
    descriptor = ParamDescriptor(type="date", required=True, default_expression="today")
    assert descriptor.default_expression == "today"


def test_dynamic_default_rejected_for_non_date_parameter() -> None:
    with pytest.raises(ValueError, match="only for date"):
        ParamDescriptor(type="string", required=True, default_expression="today")


def test_static_and_dynamic_defaults_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="only one of"):
        ParamDescriptor(
            type="date",
            required=True,
            default="2026-08-30",
            default_expression="today",
        )


def test_optional_parameter_accepts_explicit_null_default() -> None:
    descriptor = ParamDescriptor(type="string", required=False, default_is_null=True)
    assert descriptor.default_is_null is True
    assert descriptor.default is None


def test_required_parameter_rejects_explicit_null_default() -> None:
    with pytest.raises(ValueError, match="only for optional parameters"):
        ParamDescriptor(type="string", required=True, default_is_null=True)


def test_optional_parameter_accepts_no_default() -> None:
    descriptor = ParamDescriptor(type="integer", required=False)
    assert descriptor.default is None
    assert descriptor.default_is_null is False


def test_parameter_rejects_incompatible_static_default() -> None:
    with pytest.raises(ValueError, match="Invalid default"):
        ParamDescriptor(type="integer", required=True, default="abc")


def test_endpoint_create_rejects_incompatible_static_default() -> None:
    with pytest.raises(ValueError, match="Invalid default"):
        EndpointCreate(
            name="invalid-default",
            path="invalid-default",
            connection_id=uuid.uuid4(),
            sql_text="SELECT * FROM stores WHERE id = :store_id",
            param_schema={
                "store_id": {"type": "integer", "required": True, "default": "abc"}
            },
            allow_unauthenticated=True,
        )


def test_endpoint_update_rejects_incompatible_static_default() -> None:
    with pytest.raises(ValueError, match="Invalid default"):
        EndpointUpdate(
            param_schema={
                "store_id": {"type": "integer", "required": True, "default": "abc"}
            }
        )


def test_snapshot_default_validation_rejects_incompatible_stored_default() -> None:
    with pytest.raises(SnapshotConfigurationError, match="invalid parameter schema"):
        require_snapshot_defaults(
            DataStrategy.snapshot,
            {"store_id": {"type": "integer", "required": True, "default": "abc"}},
        )


def test_snapshot_endpoint_requires_defaults_for_all_parameters() -> None:
    with pytest.raises(ValueError, match=r"Missing: :end_date, :start_date"):
        EndpointCreate(
            name="snapshot-without-defaults",
            path="snapshot-without-defaults",
            connection_id=uuid.uuid4(),
            sql_text=("SELECT * FROM orders WHERE business_date BETWEEN :start_date AND :end_date"),
            param_schema={
                "start_date": {"type": "date", "required": True},
                "end_date": {"type": "date", "required": True},
            },
            allow_unauthenticated=True,
            data_strategy="snapshot",
        )


def test_snapshot_endpoint_accepts_dynamic_defaults() -> None:
    payload = EndpointCreate(
        name="snapshot-with-dynamic-defaults",
        path="snapshot-with-dynamic-defaults",
        connection_id=uuid.uuid4(),
        sql_text=("SELECT * FROM orders WHERE business_date BETWEEN :start_date AND :end_date"),
        param_schema={
            "start_date": {
                "type": "date",
                "required": True,
                "default_expression": "yesterday",
            },
            "end_date": {
                "type": "date",
                "required": True,
                "default_expression": "today",
            },
        },
        allow_unauthenticated=True,
        data_strategy="snapshot",
    )
    assert payload.param_schema["start_date"].default_expression == "yesterday"


def test_snapshot_endpoint_accepts_explicit_null_default() -> None:
    payload = EndpointCreate(
        name="snapshot-with-null-default",
        path="snapshot-with-null-default",
        connection_id=uuid.uuid4(),
        sql_text="SELECT * FROM stores WHERE :str_id IS NULL OR id = :str_id",
        param_schema={
            "str_id": {
                "type": "string",
                "required": False,
                "default_is_null": True,
            }
        },
        allow_unauthenticated=True,
        data_strategy="snapshot",
    )
    assert payload.param_schema["str_id"].default_is_null is True


def test_parameterless_snapshot_endpoint_is_valid() -> None:
    payload = EndpointCreate(
        name="parameterless-snapshot",
        path="parameterless-snapshot",
        connection_id=uuid.uuid4(),
        sql_text="SELECT 1 FROM dual",
        allow_unauthenticated=True,
        data_strategy="snapshot",
    )
    assert payload.param_schema == {}


def test_endpoint_create_normalizes_path() -> None:
    conn_id = uuid.uuid4()
    payload = EndpointCreate(
        name="test",
        path="/My-Endpoint/",
        connection_id=conn_id,
        sql_text="SELECT 1 FROM dual",
        allow_unauthenticated=True,
    )
    assert payload.path == "my-endpoint"


def test_endpoint_create_rejects_unsafe_sql() -> None:
    with pytest.raises(ValueError, match="unsafe interpolation"):
        EndpointCreate(
            name="test",
            path="test-path",
            connection_id=uuid.uuid4(),
            sql_text="SELECT * FROM t WHERE name = '' + input",
        )


def test_endpoint_create_rejects_invalid_path() -> None:
    with pytest.raises(ValueError, match="lowercase alphanumeric"):
        EndpointCreate(
            name="test",
            path="My Endpoint!",
            connection_id=uuid.uuid4(),
            sql_text="SELECT 1 FROM dual",
        )


def test_endpoint_update_all_optional() -> None:
    payload = EndpointUpdate()
    assert payload.name is None
    assert payload.path is None
    assert payload.sql_text is None


def test_endpoint_response_fields() -> None:
    fields = EndpointResponse.model_fields
    assert "id" in fields
    assert "name" in fields
    assert "path" in fields
    assert "sql_text" in fields
    assert "param_schema" in fields
    assert "column_map" in fields
    assert "auth_method_id" in fields
    assert "data_strategy" in fields
    assert "is_active" in fields
    assert "is_deprecated" in fields


def test_sql_preview_request_rejects_unsafe() -> None:
    with pytest.raises(ValueError, match="unsafe interpolation"):
        SqlPreviewRequest(
            connection_id=uuid.uuid4(),
            sql_text="SELECT * FROM t WHERE x = '' + y",
        )


def test_sql_preview_request_valid() -> None:
    payload = SqlPreviewRequest(
        connection_id=uuid.uuid4(),
        sql_text="SELECT * FROM employees WHERE dept_id = :dept_id",
        params={"dept_id": 10},
        max_rows=5,
    )
    assert payload.max_rows == 5


# ── API integration tests (require PostgreSQL) ──────────────────────────────


@pytest.mark.integration
async def test_create_endpoint(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    # First create a connection for the endpoint
    conn_payload = {
        "name": f"test-conn-ep-{uuid.uuid4().hex[:8]}",
        "host": "oracle.example.com",
        "service_name": "ORCLPDB",
        "username": "hr",
        "password": "secret",
    }
    r = await client.post("/api/v1/admin/connections/", json=conn_payload)
    assert r.status_code == 201
    conn_id = r.json()["id"]

    ep_payload = {
        "name": f"test-endpoint-{uuid.uuid4().hex[:8]}",
        "path": f"test-ep-{uuid.uuid4().hex[:8]}",
        "connection_id": conn_id,
        "sql_text": "SELECT * FROM employees WHERE dept_id = :dept_id",
        "param_schema": {
            "dept_id": {"type": "integer", "required": True},
        },
        "allow_unauthenticated": True,
    }
    response = await client.post("/api/v1/admin/endpoints/", json=ep_payload)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == ep_payload["name"]
    assert data["path"] == ep_payload["path"]
    assert data["connection_id"] == conn_id
    assert data["is_active"] is True
    assert uuid.UUID(data["id"])


@pytest.mark.integration
async def test_create_duplicate_name_returns_409(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    conn_payload = {
        "name": f"test-conn-dup-ep-{uuid.uuid4().hex[:8]}",
        "host": "oracle.example.com",
        "service_name": "ORCLPDB",
        "username": "hr",
        "password": "secret",
    }
    r = await client.post("/api/v1/admin/connections/", json=conn_payload)
    conn_id = r.json()["id"]

    ep_name = f"dup-endpoint-{uuid.uuid4().hex[:8]}"
    ep_payload = {
        "name": ep_name,
        "path": f"dup-path-{uuid.uuid4().hex[:8]}",
        "connection_id": conn_id,
        "sql_text": "SELECT 1 FROM dual",
        "allow_unauthenticated": True,
    }
    r1 = await client.post("/api/v1/admin/endpoints/", json=ep_payload)
    assert r1.status_code == 201

    ep_payload["path"] = f"dup-path2-{uuid.uuid4().hex[:8]}"
    r2 = await client.post("/api/v1/admin/endpoints/", json=ep_payload)
    assert r2.status_code == 409


@pytest.mark.integration
async def test_create_duplicate_path_returns_409(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    conn_payload = {
        "name": f"test-conn-dup-path-{uuid.uuid4().hex[:8]}",
        "host": "oracle.example.com",
        "service_name": "ORCLPDB",
        "username": "hr",
        "password": "secret",
    }
    r = await client.post("/api/v1/admin/connections/", json=conn_payload)
    conn_id = r.json()["id"]

    ep_path = f"dup-path-{uuid.uuid4().hex[:8]}"
    ep_payload = {
        "name": f"ep1-{uuid.uuid4().hex[:8]}",
        "path": ep_path,
        "connection_id": conn_id,
        "sql_text": "SELECT 1 FROM dual",
        "allow_unauthenticated": True,
    }
    r1 = await client.post("/api/v1/admin/endpoints/", json=ep_payload)
    assert r1.status_code == 201

    ep_payload["name"] = f"ep2-{uuid.uuid4().hex[:8]}"
    r2 = await client.post("/api/v1/admin/endpoints/", json=ep_payload)
    assert r2.status_code == 409


@pytest.mark.integration
async def test_get_endpoint_not_found(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    response = await client.get(f"/api/v1/admin/endpoints/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.integration
async def test_list_endpoints(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    conn_payload = {
        "name": f"test-conn-list-ep-{uuid.uuid4().hex[:8]}",
        "host": "oracle.example.com",
        "service_name": "SVC",
        "username": "scott",
        "password": "tiger",
    }
    r = await client.post("/api/v1/admin/connections/", json=conn_payload)
    conn_id = r.json()["id"]

    ep_name = f"list-ep-{uuid.uuid4().hex[:8]}"
    ep_payload = {
        "name": ep_name,
        "path": f"list-path-{uuid.uuid4().hex[:8]}",
        "connection_id": conn_id,
        "sql_text": "SELECT 1 FROM dual",
        "allow_unauthenticated": True,
    }
    await client.post("/api/v1/admin/endpoints/", json=ep_payload)

    response = await client.get("/api/v1/admin/endpoints/")
    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    assert any(e["name"] == ep_name for e in items)


@pytest.mark.integration
async def test_update_endpoint(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    conn_payload = {
        "name": f"test-conn-upd-ep-{uuid.uuid4().hex[:8]}",
        "host": "oracle.example.com",
        "service_name": "SVC",
        "username": "scott",
        "password": "tiger",
    }
    r = await client.post("/api/v1/admin/connections/", json=conn_payload)
    conn_id = r.json()["id"]

    ep_payload = {
        "name": f"upd-ep-{uuid.uuid4().hex[:8]}",
        "path": f"upd-path-{uuid.uuid4().hex[:8]}",
        "connection_id": conn_id,
        "sql_text": "SELECT 1 FROM dual",
        "allow_unauthenticated": True,
    }
    r = await client.post("/api/v1/admin/endpoints/", json=ep_payload)
    assert r.status_code == 201
    ep_id = r.json()["id"]

    update_payload = {"description": "Updated description", "is_deprecated": True}
    r2 = await client.put(f"/api/v1/admin/endpoints/{ep_id}", json=update_payload)
    assert r2.status_code == 200
    data = r2.json()
    assert data["description"] == "Updated description"
    assert data["is_deprecated"] is True


@pytest.mark.integration
async def test_update_live_endpoint_to_snapshot_requires_merged_defaults(
    async_client: object,
) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]
    conn_payload = {
        "name": f"test-conn-snapshot-update-{uuid.uuid4().hex[:8]}",
        "host": "oracle.example.com",
        "service_name": "SVC",
        "username": "scott",
        "password": "tiger",
    }
    connection = await client.post("/api/v1/admin/connections/", json=conn_payload)
    endpoint = await client.post(
        "/api/v1/admin/endpoints/",
        json={
            "name": f"snapshot-update-{uuid.uuid4().hex[:8]}",
            "path": f"snapshot-update-{uuid.uuid4().hex[:8]}",
            "connection_id": connection.json()["id"],
            "sql_text": "SELECT * FROM orders WHERE business_date = :business_date",
            "param_schema": {"business_date": {"type": "date", "required": True}},
            "allow_unauthenticated": True,
            "data_strategy": "live",
        },
    )
    assert endpoint.status_code == 201

    invalid = await client.put(
        f"/api/v1/admin/endpoints/{endpoint.json()['id']}",
        json={"data_strategy": "snapshot"},
    )
    assert invalid.status_code == 422
    assert ":business_date" in invalid.json()["detail"]

    valid = await client.put(
        f"/api/v1/admin/endpoints/{endpoint.json()['id']}",
        json={
            "data_strategy": "snapshot",
            "param_schema": {
                "business_date": {
                    "type": "date",
                    "required": True,
                    "default_expression": "today",
                }
            },
        },
    )
    assert valid.status_code == 200
    assert valid.json()["param_schema"]["business_date"]["default_expression"] == "today"


@pytest.mark.integration
async def test_update_snapshot_with_invalid_stored_schema_returns_422(
    async_client: object,
    db_session: object,
) -> None:
    from app.models.endpoint import ApiEndpoint
    from httpx import AsyncClient
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import AsyncSession

    client: AsyncClient = async_client  # type: ignore[assignment]
    session: AsyncSession = db_session  # type: ignore[assignment]
    connection = await client.post(
        "/api/v1/admin/connections/",
        json={
            "name": f"test-conn-invalid-schema-update-{uuid.uuid4().hex[:8]}",
            "host": "oracle.example.com",
            "service_name": "SVC",
            "username": "scott",
            "password": "tiger",
        },
    )
    endpoint = await client.post(
        "/api/v1/admin/endpoints/",
        json={
            "name": f"invalid-schema-update-{uuid.uuid4().hex[:8]}",
            "path": f"invalid-schema-update-{uuid.uuid4().hex[:8]}",
            "connection_id": connection.json()["id"],
            "sql_text": "SELECT * FROM stores WHERE id = :store_id",
            "param_schema": {
                "store_id": {"type": "integer", "required": True, "default": 1}
            },
            "allow_unauthenticated": True,
            "data_strategy": "snapshot",
        },
    )
    assert endpoint.status_code == 201
    endpoint_id = uuid.UUID(endpoint.json()["id"])

    await session.execute(
        update(ApiEndpoint)
        .where(ApiEndpoint.id == endpoint_id)
        .values(
            param_schema_json={
                "store_id": {"type": "integer", "required": True, "default": "abc"}
            }
        )
    )
    await session.commit()
    session.expire_all()

    response = await client.put(
        f"/api/v1/admin/endpoints/{endpoint_id}",
        json={"description": "still invalid"},
    )

    assert response.status_code == 422
    assert "invalid parameter schema" in response.json()["detail"]


@pytest.mark.integration
async def test_delete_endpoint(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    conn_payload = {
        "name": f"test-conn-del-ep-{uuid.uuid4().hex[:8]}",
        "host": "oracle.example.com",
        "service_name": "SVC",
        "username": "scott",
        "password": "tiger",
    }
    r = await client.post("/api/v1/admin/connections/", json=conn_payload)
    conn_id = r.json()["id"]

    ep_payload = {
        "name": f"del-ep-{uuid.uuid4().hex[:8]}",
        "path": f"del-path-{uuid.uuid4().hex[:8]}",
        "connection_id": conn_id,
        "sql_text": "SELECT 1 FROM dual",
        "allow_unauthenticated": True,
    }
    r = await client.post("/api/v1/admin/endpoints/", json=ep_payload)
    assert r.status_code == 201
    ep_id = r.json()["id"]

    r_del = await client.delete(f"/api/v1/admin/endpoints/{ep_id}")
    assert r_del.status_code == 204

    r_get = await client.get(f"/api/v1/admin/endpoints/{ep_id}")
    assert r_get.status_code == 404


@pytest.mark.integration
async def test_delete_endpoint_preserves_job_history_and_removes_scheduler_job(
    async_client: object,
    db_session: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from app.models.job_run import JobRun, JobRunStatus
    from httpx import AsyncClient
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    client: AsyncClient = async_client  # type: ignore[assignment]
    session: AsyncSession = db_session  # type: ignore[assignment]

    connection = await client.post(
        "/api/v1/admin/connections/",
        json={
            "name": f"test-conn-del-history-{uuid.uuid4().hex[:8]}",
            "host": "oracle.example.com",
            "service_name": "SVC",
            "username": "scott",
            "password": "tiger",
        },
    )
    assert connection.status_code == 201

    endpoint = await client.post(
        "/api/v1/admin/endpoints/",
        json={
            "name": f"del-history-{uuid.uuid4().hex[:8]}",
            "path": f"del-history-path-{uuid.uuid4().hex[:8]}",
            "connection_id": connection.json()["id"],
            "sql_text": "SELECT 1 FROM dual",
            "allow_unauthenticated": True,
            "data_strategy": "snapshot",
        },
    )
    assert endpoint.status_code == 201
    endpoint_id = endpoint.json()["id"]

    schedule = await client.post(
        "/api/v1/admin/schedules/",
        json={
            "endpoint_id": endpoint_id,
            "schedule_type": "interval",
            "interval_seconds": 300,
        },
    )
    assert schedule.status_code == 201
    schedule_id = schedule.json()["id"]

    run_id = uuid.uuid4()
    session.add(
        JobRun(
            id=run_id,
            schedule_id=uuid.UUID(schedule_id),
            endpoint_id=uuid.UUID(endpoint_id),
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            status=JobRunStatus.success,
            row_count=1,
        )
    )
    await session.commit()

    removed_jobs: list[uuid.UUID] = []
    monkeypatch.setattr("app.routers.endpoints.remove_schedule_job", removed_jobs.append)

    deleted = await client.delete(f"/api/v1/admin/endpoints/{endpoint_id}")
    assert deleted.status_code == 204
    assert removed_jobs == [uuid.UUID(schedule_id)]

    ids = await session.execute(
        select(JobRun.endpoint_id, JobRun.schedule_id).where(JobRun.id == run_id)
    )
    assert ids.one() == (None, None)

    historical_run = await client.get(f"/api/v1/admin/schedules/jobs/{run_id}")
    assert historical_run.status_code == 200
    assert historical_run.json()["endpoint_id"] is None
    assert historical_run.json()["schedule_id"] is None

    deleted_schedule = await client.get(f"/api/v1/admin/schedules/{schedule_id}")
    assert deleted_schedule.status_code == 404


@pytest.mark.integration
async def test_data_endpoint_not_found(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    response = await client.get("/api/v1/data/nonexistent-path")
    assert response.status_code == 404
    assert "No endpoint registered" in response.json()["detail"]
