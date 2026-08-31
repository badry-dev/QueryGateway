"""Tests for schedule management — schemas, service, and API layer.

Integration tests (requiring PostgreSQL) are marked with @pytest.mark.integration
and run in CI where the service is available.

Unit tests exercise schema validation and cron/interval configuration.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
from app.schemas.schedule import (
    JobRunResponse,
    ScheduleCreate,
    ScheduleParameterBinding,
    SchedulePreviewResponse,
    ScheduleResponse,
    ScheduleUpdate,
    ScheduleWindow,
    SnapshotDetailResponse,
    SnapshotResponse,
)

# ── Schema validation unit tests ─────────────────────────────────────────────


def test_schedule_create_cron_valid() -> None:
    payload = ScheduleCreate(
        endpoint_id=uuid.uuid4(),
        schedule_type="cron",
        cron_expression="0 */6 * * *",
    )
    assert payload.schedule_type == "cron"
    assert payload.cron_expression == "0 */6 * * *"


def test_schedule_create_interval_valid() -> None:
    payload = ScheduleCreate(
        endpoint_id=uuid.uuid4(),
        schedule_type="interval",
        interval_seconds=300,
    )
    assert payload.schedule_type == "interval"
    assert payload.interval_seconds == 300


def test_schedule_create_accepts_timezone_and_declarative_bindings() -> None:
    payload = ScheduleCreate(
        endpoint_id=uuid.uuid4(),
        schedule_type="cron",
        cron_expression="0 6 * * *",
        timezone="Asia/Riyadh",
        parameter_bindings={
            "start_date": ScheduleParameterBinding(source="window_start"),
            "end_date": ScheduleParameterBinding(source="window_end"),
        },
        window=ScheduleWindow(preset="last_n_complete_days", days=7),
    )

    assert payload.timezone == "Asia/Riyadh"
    assert payload.parameter_bindings["start_date"].source == "window_start"
    assert payload.window == ScheduleWindow(preset="last_n_complete_days", days=7)


def test_schedule_create_rejects_unknown_timezone() -> None:
    with pytest.raises(ValueError, match="Unknown IANA timezone"):
        ScheduleCreate(
            endpoint_id=uuid.uuid4(),
            schedule_type="cron",
            cron_expression="0 6 * * *",
            timezone="Mars/Olympus_Mons",
        )


def test_schedule_create_cron_requires_expression() -> None:
    with pytest.raises(ValueError, match="cron_expression is required"):
        ScheduleCreate(
            endpoint_id=uuid.uuid4(),
            schedule_type="cron",
        )


def test_schedule_create_interval_requires_seconds() -> None:
    with pytest.raises(ValueError, match="interval_seconds is required"):
        ScheduleCreate(
            endpoint_id=uuid.uuid4(),
            schedule_type="interval",
        )


def test_schedule_create_invalid_cron_fields() -> None:
    with pytest.raises(ValueError, match="5 fields"):
        ScheduleCreate(
            endpoint_id=uuid.uuid4(),
            schedule_type="cron",
            cron_expression="0 0 *",
        )


@pytest.mark.parametrize(
    "cron_expression",
    [
        "invalid invalid invalid invalid invalid",
        "60 * * * *",
        "0 24 * * *",
        "0 0 32 * *",
        "0 0 * 13 *",
        "0 0 * * 7",
        "*/0 * * * *",
    ],
)
def test_schedule_create_rejects_invalid_cron_syntax(cron_expression: str) -> None:
    with pytest.raises(ValueError, match="Invalid cron expression"):
        ScheduleCreate(
            endpoint_id=uuid.uuid4(),
            schedule_type="cron",
            cron_expression=cron_expression,
        )


def test_schedule_update_rejects_invalid_cron_syntax() -> None:
    with pytest.raises(ValueError, match="Invalid cron expression"):
        ScheduleUpdate(cron_expression="60 * * * *")


def test_schedule_create_interval_minimum() -> None:
    with pytest.raises(ValueError):
        ScheduleCreate(
            endpoint_id=uuid.uuid4(),
            schedule_type="interval",
            interval_seconds=5,
        )


def test_schedule_create_invalid_type() -> None:
    with pytest.raises(ValueError):
        ScheduleCreate(
            endpoint_id=uuid.uuid4(),
            schedule_type="weekly",
        )


def test_schedule_update_all_optional() -> None:
    payload = ScheduleUpdate()
    assert payload.schedule_type is None
    assert payload.cron_expression is None
    assert payload.interval_seconds is None
    assert payload.is_active is None


def test_schedule_response_fields() -> None:
    fields = ScheduleResponse.model_fields
    assert "id" in fields
    assert "endpoint_id" in fields
    assert "schedule_type" in fields
    assert "cron_expression" in fields
    assert "interval_seconds" in fields
    assert "is_active" in fields
    assert "last_run_at" in fields
    assert "next_run_at" in fields
    assert "timezone" in fields
    assert "parameter_bindings" in fields
    assert "window" in fields


def test_schedule_preview_response_contains_resolved_run_context() -> None:
    fields = SchedulePreviewResponse.model_fields
    assert "runs" in fields


def test_job_run_response_fields() -> None:
    fields = JobRunResponse.model_fields
    assert "id" in fields
    assert "schedule_id" in fields
    assert "endpoint_id" in fields
    assert "started_at" in fields
    assert "finished_at" in fields
    assert "status" in fields
    assert "row_count" in fields
    assert "error_detail" in fields
    assert "scheduled_for" in fields
    assert "logical_date" in fields
    assert "window_start" in fields
    assert "window_end" in fields
    assert "resolved_parameters" in fields
    assert "trigger_source" in fields
    assert "binding_hash" in fields


def test_job_run_response_allows_deleted_schedule_history() -> None:
    now = datetime.now(UTC)
    response = JobRunResponse(
        id=uuid.uuid4(),
        schedule_id=None,
        endpoint_id=uuid.uuid4(),
        started_at=now,
        finished_at=now,
        status="success",
        row_count=1,
        error_detail=None,
        created_at=now,
    )
    assert response.schedule_id is None


def test_job_run_response_allows_deleted_endpoint_history() -> None:
    now = datetime.now(UTC)
    response = JobRunResponse(
        id=uuid.uuid4(),
        schedule_id=uuid.uuid4(),
        endpoint_id=None,
        started_at=now,
        finished_at=now,
        status="success",
        row_count=1,
        error_detail=None,
        created_at=now,
    )
    assert response.endpoint_id is None


def test_snapshot_response_fields() -> None:
    fields = SnapshotResponse.model_fields
    assert "id" in fields
    assert "endpoint_id" in fields
    assert "job_run_id" in fields
    assert "row_count" in fields
    assert "created_at" in fields


def test_snapshot_detail_response_fields() -> None:
    fields = SnapshotDetailResponse.model_fields
    assert "data" in fields
    assert "row_count" in fields


# ── API integration tests (require PostgreSQL) ──────────────────────────────


async def _create_snapshot_endpoint_with_date_range(client: object) -> str:
    from httpx import AsyncClient

    typed_client: AsyncClient = client  # type: ignore[assignment]
    connection = await typed_client.post(
        "/api/v1/admin/connections/",
        json={
            "name": f"schedule-binding-conn-{uuid.uuid4().hex[:8]}",
            "host": "oracle.example.com",
            "service_name": "ORCLPDB",
            "username": "hr",
            "password": "test-password",
        },
    )
    assert connection.status_code == 201
    endpoint = await typed_client.post(
        "/api/v1/admin/endpoints/",
        json={
            "name": f"schedule-binding-ep-{uuid.uuid4().hex[:8]}",
            "path": f"schedule-binding-path-{uuid.uuid4().hex[:8]}",
            "connection_id": connection.json()["id"],
            "allow_unauthenticated": True,
            "sql_text": (
                "SELECT * FROM orders WHERE business_date BETWEEN :start_date AND :end_date"
            ),
            "param_schema": {
                "start_date": {
                    "type": "date",
                    "required": True,
                    "snapshot_filter": {
                        "column": "business_date",
                        "operator": "gte",
                    },
                },
                "end_date": {
                    "type": "date",
                    "required": True,
                    "snapshot_filter": {
                        "column": "business_date",
                        "operator": "lte",
                    },
                },
            },
            "data_strategy": "snapshot",
        },
    )
    assert endpoint.status_code == 201
    return str(endpoint.json()["id"])


@pytest.mark.integration
async def test_schedule_bindings_are_required_at_schedule_creation(
    async_client: object,
) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]
    endpoint_id = await _create_snapshot_endpoint_with_date_range(client)

    missing = await client.post(
        "/api/v1/admin/schedules/",
        json={
            "endpoint_id": endpoint_id,
            "schedule_type": "cron",
            "cron_expression": "0 6 * * *",
            "timezone": "Asia/Riyadh",
            "parameter_bindings": {
                "end_date": {"source": "run_date"},
            },
        },
    )
    assert missing.status_code == 422
    assert "Missing schedule bindings: :start_date" in missing.json()["detail"]

    created = await client.post(
        "/api/v1/admin/schedules/",
        json={
            "endpoint_id": endpoint_id,
            "schedule_type": "cron",
            "cron_expression": "0 6 * * *",
            "timezone": "Asia/Riyadh",
            "parameter_bindings": {
                "start_date": {"source": "relative_date", "offset_days": -7},
                "end_date": {"source": "run_date"},
            },
        },
    )
    assert created.status_code == 201
    assert created.json()["timezone"] == "Asia/Riyadh"
    assert created.json()["parameter_bindings"]["start_date"] == {
        "source": "relative_date",
        "value": None,
        "offset_days": -7,
    }


@pytest.mark.integration
async def test_endpoint_update_cannot_invalidate_attached_schedule(
    async_client: object,
) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]
    endpoint_id = await _create_snapshot_endpoint_with_date_range(client)
    created = await client.post(
        "/api/v1/admin/schedules/",
        json={
            "endpoint_id": endpoint_id,
            "schedule_type": "cron",
            "cron_expression": "0 6 * * *",
            "timezone": "Asia/Riyadh",
            "parameter_bindings": {
                "start_date": {"source": "relative_date", "offset_days": -7},
                "end_date": {"source": "run_date"},
            },
        },
    )
    assert created.status_code == 201

    invalid_type = await client.put(
        f"/api/v1/admin/endpoints/{endpoint_id}",
        json={
            "param_schema": {
                "start_date": {
                    "type": "string",
                    "required": True,
                    "snapshot_filter": {
                        "column": "business_date",
                        "operator": "gte",
                    },
                },
                "end_date": {
                    "type": "date",
                    "required": True,
                    "snapshot_filter": {
                        "column": "business_date",
                        "operator": "lte",
                    },
                },
            }
        },
    )
    assert invalid_type.status_code == 422
    assert ":start_date must be a date parameter" in invalid_type.json()["detail"]

    invalid_schema = await client.put(
        f"/api/v1/admin/endpoints/{endpoint_id}",
        json={
            "param_schema": {
                "start_date": {
                    "type": "date",
                    "required": True,
                    "snapshot_filter": {
                        "column": "business_date",
                        "operator": "gte",
                    },
                },
                "replacement_end_date": {
                    "type": "date",
                    "required": True,
                    "snapshot_filter": {
                        "column": "business_date",
                        "operator": "lte",
                    },
                },
            }
        },
    )
    assert invalid_schema.status_code == 422
    assert "continue to match" in invalid_schema.json()["detail"]

    live_strategy = await client.put(
        f"/api/v1/admin/endpoints/{endpoint_id}",
        json={"data_strategy": "live"},
    )
    assert live_strategy.status_code == 422
    assert "Delete the attached schedule" in live_strategy.json()["detail"]

    unchanged = await client.get(f"/api/v1/admin/endpoints/{endpoint_id}")
    assert unchanged.json()["data_strategy"] == "snapshot"
    assert set(unchanged.json()["param_schema"]) == {"start_date", "end_date"}


@pytest.mark.integration
async def test_schedule_rejects_live_endpoint(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]
    connection = await client.post(
        "/api/v1/admin/connections/",
        json={
            "name": f"live-schedule-conn-{uuid.uuid4().hex[:8]}",
            "host": "oracle.example.com",
            "service_name": "ORCLPDB",
            "username": "hr",
            "password": "test-password",
        },
    )
    endpoint = await client.post(
        "/api/v1/admin/endpoints/",
        json={
            "name": f"live-schedule-ep-{uuid.uuid4().hex[:8]}",
            "path": f"live-schedule-path-{uuid.uuid4().hex[:8]}",
            "connection_id": connection.json()["id"],
            "allow_unauthenticated": True,
            "sql_text": "SELECT 1 FROM dual",
            "data_strategy": "live",
        },
    )

    response = await client.post(
        "/api/v1/admin/schedules/",
        json={
            "endpoint_id": endpoint.json()["id"],
            "schedule_type": "interval",
            "interval_seconds": 60,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Schedules are supported only for snapshot endpoints."


@pytest.mark.integration
async def test_preview_schedule_resolves_next_runs(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]
    endpoint_id = await _create_snapshot_endpoint_with_date_range(client)

    response = await client.post(
        "/api/v1/admin/schedules/preview",
        json={
            "endpoint_id": endpoint_id,
            "schedule_type": "cron",
            "cron_expression": "0 6 * * *",
            "timezone": "Asia/Riyadh",
            "parameter_bindings": {
                "start_date": {"source": "window_start"},
                "end_date": {"source": "window_end"},
            },
            "window": {"preset": "last_n_complete_days", "days": 7},
            "count": 3,
        },
    )

    assert response.status_code == 200
    runs = response.json()["runs"]
    assert len(runs) == 3
    assert all(run["scheduled_for"].endswith("+03:00") for run in runs)
    assert all(run["resolved_parameters"]["start_date"] for run in runs)
    assert all(run["resolved_parameters"]["end_date"] for run in runs)


@pytest.mark.integration
async def test_scheduled_execution_persists_logical_context_and_is_idempotent(
    async_client: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from app.services import scheduler as scheduler_service
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]
    endpoint_id = await _create_snapshot_endpoint_with_date_range(client)
    created = await client.post(
        "/api/v1/admin/schedules/",
        json={
            "endpoint_id": endpoint_id,
            "schedule_type": "cron",
            "cron_expression": "0 6 * * *",
            "timezone": "Asia/Riyadh",
            "parameter_bindings": {
                "start_date": {"source": "window_start"},
                "end_date": {"source": "window_end"},
            },
            "window": {"preset": "last_n_complete_days", "days": 7},
        },
    )
    assert created.status_code == 201
    schedule_id = created.json()["id"]

    execute_query = AsyncMock(
        return_value=(
            ["ORDER_ID"],
            [{"ORDER_ID": 42}],
            12,
        )
    )
    monkeypatch.setattr(scheduler_service, "execute_query", execute_query)
    scheduled_for = datetime(2026, 8, 31, 3, tzinfo=UTC)

    await scheduler_service.execute_scheduled_job(
        schedule_id,
        endpoint_id,
        scheduled_for=scheduled_for,
    )
    await scheduler_service.execute_scheduled_job(
        schedule_id,
        endpoint_id,
        scheduled_for=scheduled_for,
    )

    runs_response = await client.get(
        "/api/v1/admin/schedules/jobs/",
        params={"schedule_id": schedule_id},
    )
    assert runs_response.status_code == 200
    runs = runs_response.json()
    assert len(runs) == 1
    assert runs[0]["status"] == "success"
    assert runs[0]["scheduled_for"] == "2026-08-31T03:00:00Z"
    assert runs[0]["logical_date"] == "2026-08-31"
    assert runs[0]["window_start"] == "2026-08-24"
    assert runs[0]["window_end"] == "2026-08-30"
    assert runs[0]["resolved_parameters"] == {
        "start_date": "2026-08-24",
        "end_date": "2026-08-30",
    }
    assert runs[0]["trigger_source"] == "scheduled"
    assert len(runs[0]["binding_hash"]) == 64
    execute_query.assert_awaited_once()
    assert execute_query.await_args is not None
    assert execute_query.await_args.kwargs["params"] == {
        "start_date": date(2026, 8, 24),
        "end_date": date(2026, 8, 30),
    }


@pytest.mark.integration
async def test_run_now_accepts_an_explicit_logical_date(
    async_client: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from app.services import schedule as schedule_service
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]
    endpoint_id = await _create_snapshot_endpoint_with_date_range(client)
    created = await client.post(
        "/api/v1/admin/schedules/",
        json={
            "endpoint_id": endpoint_id,
            "schedule_type": "cron",
            "cron_expression": "0 6 * * *",
            "timezone": "Asia/Riyadh",
            "parameter_bindings": {
                "start_date": {"source": "relative_date", "offset_days": -1},
                "end_date": {"source": "run_date"},
            },
        },
    )
    execute_job = AsyncMock()
    monkeypatch.setattr(schedule_service, "execute_scheduled_job", execute_job)

    response = await client.post(
        f"/api/v1/admin/schedules/{created.json()['id']}/run",
        json={"logical_date": "2026-08-30"},
    )

    assert response.status_code == 202
    execute_job.assert_awaited_once()
    assert execute_job.await_args is not None
    assert execute_job.await_args.kwargs["trigger_source"] == "manual"
    assert execute_job.await_args.kwargs["scheduled_for"].isoformat() == "2026-08-30T00:00:00+03:00"


@pytest.mark.integration
async def test_create_schedule(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    # Create connection and endpoint first
    conn_payload = {
        "name": f"test-conn-sched-{uuid.uuid4().hex[:8]}",
        "host": "oracle.example.com",
        "service_name": "ORCLPDB",
        "username": "hr",
        "password": "secret",
    }
    r = await client.post("/api/v1/admin/connections/", json=conn_payload)
    assert r.status_code == 201
    conn_id = r.json()["id"]

    ep_payload = {
        "name": f"sched-ep-{uuid.uuid4().hex[:8]}",
        "path": f"sched-path-{uuid.uuid4().hex[:8]}",
        "connection_id": conn_id,
        "allow_unauthenticated": True,
        "sql_text": "SELECT 1 FROM dual",
        "data_strategy": "snapshot",
    }
    r = await client.post("/api/v1/admin/endpoints/", json=ep_payload)
    assert r.status_code == 201
    ep_id = r.json()["id"]

    # Create schedule
    sched_payload = {
        "endpoint_id": ep_id,
        "schedule_type": "interval",
        "interval_seconds": 60,
    }
    response = await client.post("/api/v1/admin/schedules/", json=sched_payload)
    assert response.status_code == 201
    data = response.json()
    assert data["endpoint_id"] == ep_id
    assert data["schedule_type"] == "interval"
    assert data["interval_seconds"] == 60
    assert data["is_active"] is True
    assert uuid.UUID(data["id"])


@pytest.mark.integration
async def test_create_schedule_with_invalid_stored_schema_returns_422(
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
            "name": f"test-conn-invalid-schema-schedule-{uuid.uuid4().hex[:8]}",
            "host": "oracle.example.com",
            "service_name": "SVC",
            "username": "scott",
            "password": "tiger",
        },
    )
    endpoint = await client.post(
        "/api/v1/admin/endpoints/",
        json={
            "name": f"invalid-schema-schedule-{uuid.uuid4().hex[:8]}",
            "path": f"invalid-schema-schedule-{uuid.uuid4().hex[:8]}",
            "connection_id": connection.json()["id"],
            "sql_text": "SELECT * FROM stores WHERE id = :store_id",
            "param_schema": {
                "store_id": {
                    "type": "integer",
                    "required": True,
                    "default": 1,
                    "snapshot_filter": {"column": "id", "operator": "eq"},
                }
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
            param_schema_json={"store_id": {"type": "integer", "required": True, "default": "abc"}}
        )
    )
    await session.flush()
    session.expire_all()

    response = await client.post(
        "/api/v1/admin/schedules/",
        json={
            "endpoint_id": str(endpoint_id),
            "schedule_type": "interval",
            "interval_seconds": 60,
        },
    )

    assert response.status_code == 422
    assert "invalid parameter schema" in response.json()["detail"]


@pytest.mark.integration
async def test_create_duplicate_schedule_returns_409(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    conn_payload = {
        "name": f"test-conn-dup-sched-{uuid.uuid4().hex[:8]}",
        "host": "oracle.example.com",
        "service_name": "ORCLPDB",
        "username": "hr",
        "password": "secret",
    }
    r = await client.post("/api/v1/admin/connections/", json=conn_payload)
    conn_id = r.json()["id"]

    ep_payload = {
        "name": f"dup-sched-ep-{uuid.uuid4().hex[:8]}",
        "path": f"dup-sched-path-{uuid.uuid4().hex[:8]}",
        "connection_id": conn_id,
        "allow_unauthenticated": True,
        "sql_text": "SELECT 1 FROM dual",
        "data_strategy": "snapshot",
    }
    r = await client.post("/api/v1/admin/endpoints/", json=ep_payload)
    ep_id = r.json()["id"]

    sched_payload = {
        "endpoint_id": ep_id,
        "schedule_type": "interval",
        "interval_seconds": 60,
    }

    r1 = await client.post("/api/v1/admin/schedules/", json=sched_payload)
    assert r1.status_code == 201

    r2 = await client.post("/api/v1/admin/schedules/", json=sched_payload)
    assert r2.status_code == 409


@pytest.mark.integration
async def test_list_schedules(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    response = await client.get("/api/v1/admin/schedules/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.integration
async def test_get_schedule_not_found(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    response = await client.get(f"/api/v1/admin/schedules/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.integration
async def test_update_schedule(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    # Setup
    conn_payload = {
        "name": f"test-conn-upd-sched-{uuid.uuid4().hex[:8]}",
        "host": "oracle.example.com",
        "service_name": "SVC",
        "username": "scott",
        "password": "tiger",
    }
    r = await client.post("/api/v1/admin/connections/", json=conn_payload)
    conn_id = r.json()["id"]

    ep_payload = {
        "name": f"upd-sched-ep-{uuid.uuid4().hex[:8]}",
        "path": f"upd-sched-path-{uuid.uuid4().hex[:8]}",
        "connection_id": conn_id,
        "allow_unauthenticated": True,
        "sql_text": "SELECT 1 FROM dual",
        "data_strategy": "snapshot",
    }
    r = await client.post("/api/v1/admin/endpoints/", json=ep_payload)
    ep_id = r.json()["id"]

    sched_payload = {
        "endpoint_id": ep_id,
        "schedule_type": "interval",
        "interval_seconds": 300,
    }
    r = await client.post("/api/v1/admin/schedules/", json=sched_payload)
    assert r.status_code == 201
    sched_id = r.json()["id"]

    # Update
    update_payload = {"interval_seconds": 600, "is_active": False}
    r2 = await client.put(f"/api/v1/admin/schedules/{sched_id}", json=update_payload)
    assert r2.status_code == 200
    data = r2.json()
    assert data["interval_seconds"] == 600
    assert data["is_active"] is False


@pytest.mark.integration
async def test_delete_schedule(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    # Setup
    conn_payload = {
        "name": f"test-conn-del-sched-{uuid.uuid4().hex[:8]}",
        "host": "oracle.example.com",
        "service_name": "SVC",
        "username": "scott",
        "password": "tiger",
    }
    r = await client.post("/api/v1/admin/connections/", json=conn_payload)
    conn_id = r.json()["id"]

    ep_payload = {
        "name": f"del-sched-ep-{uuid.uuid4().hex[:8]}",
        "path": f"del-sched-path-{uuid.uuid4().hex[:8]}",
        "connection_id": conn_id,
        "allow_unauthenticated": True,
        "sql_text": "SELECT 1 FROM dual",
        "data_strategy": "snapshot",
    }
    r = await client.post("/api/v1/admin/endpoints/", json=ep_payload)
    ep_id = r.json()["id"]

    sched_payload = {
        "endpoint_id": ep_id,
        "schedule_type": "cron",
        "cron_expression": "0 0 * * *",
    }
    r = await client.post("/api/v1/admin/schedules/", json=sched_payload)
    assert r.status_code == 201
    sched_id = r.json()["id"]

    # Delete
    r_del = await client.delete(f"/api/v1/admin/schedules/{sched_id}")
    assert r_del.status_code == 204

    # Verify deleted
    r_get = await client.get(f"/api/v1/admin/schedules/{sched_id}")
    assert r_get.status_code == 404


@pytest.mark.integration
async def test_delete_schedule_preserves_job_run_history(
    async_client: object, db_session: object
) -> None:
    from app.models.job_run import JobRun, JobRunStatus
    from httpx import AsyncClient
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    client: AsyncClient = async_client  # type: ignore[assignment]
    db: AsyncSession = db_session  # type: ignore[assignment]

    connection = await client.post(
        "/api/v1/admin/connections/",
        json={
            "name": f"test-conn-history-{uuid.uuid4().hex[:8]}",
            "host": "oracle.example.com",
            "service_name": "SVC",
            "username": "scott",
            "password": "test-password",
        },
    )
    endpoint = await client.post(
        "/api/v1/admin/endpoints/",
        json={
            "name": f"history-ep-{uuid.uuid4().hex[:8]}",
            "path": f"history-path-{uuid.uuid4().hex[:8]}",
            "connection_id": connection.json()["id"],
            "allow_unauthenticated": True,
            "sql_text": "SELECT 1 FROM dual",
            "data_strategy": "snapshot",
        },
    )
    schedule = await client.post(
        "/api/v1/admin/schedules/",
        json={
            "endpoint_id": endpoint.json()["id"],
            "schedule_type": "interval",
            "interval_seconds": 300,
        },
    )
    schedule_id = uuid.UUID(schedule.json()["id"])
    job_run = JobRun(
        schedule_id=schedule_id,
        endpoint_id=uuid.UUID(endpoint.json()["id"]),
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status=JobRunStatus.success,
        row_count=1,
    )
    db.add(job_run)
    await db.commit()

    deleted = await client.delete(f"/api/v1/admin/schedules/{schedule_id}")
    assert deleted.status_code == 204

    preserved = await db.scalar(select(JobRun).where(JobRun.id == job_run.id))
    assert preserved is not None
    await db.refresh(preserved)
    assert preserved.schedule_id is None


@pytest.mark.integration
async def test_list_job_runs(async_client: object) -> None:
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    response = await client.get("/api/v1/admin/schedules/jobs/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
