"""Public snapshot endpoints enforce and apply declared request parameters."""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import pytest
from app.models.endpoint import ApiEndpoint, DataStrategy
from app.models.job_run import JobRun, JobRunStatus
from app.models.snapshot import Snapshot
from app.repositories.job_run import JobRunRepository
from app.schemas.endpoint import EndpointCreate, ParamDescriptor
from app.services.snapshot_filtering import (
    compile_snapshot_filters,
    validate_snapshot_parameter_ranges,
    validate_snapshot_rows_match_resolved_parameters,
)
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs


def test_snapshot_filter_contract_is_preserved_in_parameter_schema() -> None:
    descriptor = ParamDescriptor(
        type="integer",
        required=False,
        default_is_null=True,
        snapshot_filter={
            "column": "store_id",
            "operator": "eq",
            "null_means_all": True,
        },
    )

    assert descriptor.snapshot_filter is not None
    assert descriptor.snapshot_filter.column == "store_id"
    assert descriptor.snapshot_filter.null_means_all is True


def test_snapshot_endpoint_rejects_parameter_without_filter_mapping() -> None:
    with pytest.raises(ValueError, match="snapshot filter mappings"):
        EndpointCreate(
            name="unmapped-snapshot",
            path="unmapped-snapshot",
            connection_id=uuid.uuid4(),
            sql_text="SELECT * FROM stores WHERE store_id = :store_id",
            param_schema={"store_id": {"type": "integer", "required": True}},
            allow_unauthenticated=True,
            data_strategy="snapshot",
        )


def test_null_means_all_is_rejected_for_range_filter() -> None:
    with pytest.raises(ValueError, match="null_means_all"):
        ParamDescriptor(
            type="date",
            snapshot_filter={
                "column": "business_date",
                "operator": "gte",
                "null_means_all": True,
            },
        )


def test_null_means_all_is_rejected_for_required_parameter() -> None:
    with pytest.raises(ValueError, match="optional parameters"):
        ParamDescriptor(
            type="integer",
            required=True,
            snapshot_filter={
                "column": "store_id",
                "operator": "eq",
                "null_means_all": True,
            },
        )


def test_snapshot_range_mappings_require_matching_parameter_types() -> None:
    with pytest.raises(ValueError, match="same declared parameter type"):
        EndpointCreate(
            name="mixed-range-types",
            path="mixed-range-types",
            connection_id=uuid.uuid4(),
            sql_text=(
                "SELECT * FROM orders "
                "WHERE business_date >= :start_date AND business_date <= :end_date"
            ),
            param_schema={
                "start_date": {
                    "type": "integer",
                    "snapshot_filter": {
                        "column": "business_date",
                        "operator": "gte",
                    },
                },
                "end_date": {
                    "type": "string",
                    "snapshot_filter": {
                        "column": "business_date",
                        "operator": "lte",
                    },
                },
            },
            allow_unauthenticated=True,
            data_strategy="snapshot",
        )


def test_snapshot_range_validation_retains_duplicate_directional_bounds() -> None:
    filters = compile_snapshot_filters(
        {
            "strict_start": {
                "type": "integer",
                "snapshot_filter": {"column": "sequence", "operator": "gte"},
            },
            "loose_start": {
                "type": "integer",
                "snapshot_filter": {"column": "sequence", "operator": "gte"},
            },
            "end": {
                "type": "integer",
                "snapshot_filter": {"column": "sequence", "operator": "lte"},
            },
        }
    )

    with pytest.raises(ValueError, match="lower bound exceeds upper bound"):
        validate_snapshot_parameter_ranges(
            filters=filters,
            request_params={"strict_start": 10, "loose_start": 5, "end": 7},
        )


def test_snapshot_integrity_rejects_cached_dates_outside_resolved_window() -> None:
    filters = compile_snapshot_filters(
        {
            "start_date": {
                "type": "date",
                "snapshot_filter": {"column": "DT", "operator": "gte"},
            },
            "end_date": {
                "type": "date",
                "snapshot_filter": {"column": "DT", "operator": "lte"},
            },
        }
    )

    with pytest.raises(
        ValueError,
        match="1 of 1 cached rows do not match the schedule's resolved filter parameters",
    ):
        validate_snapshot_rows_match_resolved_parameters(
            rows=[{"DT": "0026-08-24 00:00:00", "ORDER_COUNT": 0}],
            filters=filters,
            resolved_params={
                "start_date": date(2026, 8, 24),
                "end_date": date(2026, 8, 31),
            },
        )


def test_snapshot_integrity_accepts_empty_and_in_window_results() -> None:
    filters = compile_snapshot_filters(
        {
            "start_date": {
                "type": "date",
                "snapshot_filter": {"column": "DT", "operator": "gte"},
            },
            "end_date": {
                "type": "date",
                "snapshot_filter": {"column": "DT", "operator": "lte"},
            },
        }
    )
    resolved_params = {
        "start_date": date(2026, 8, 24),
        "end_date": date(2026, 8, 31),
    }

    validate_snapshot_rows_match_resolved_parameters(
        rows=[],
        filters=filters,
        resolved_params=resolved_params,
    )
    validate_snapshot_rows_match_resolved_parameters(
        rows=[{"DT": "2026-08-24 17:30:00", "ORDER_COUNT": 4}],
        filters=filters,
        resolved_params=resolved_params,
    )


async def _seed_snapshot_endpoint(
    client: AsyncClient,
    session: AsyncSession,
) -> str:
    connection = await client.post(
        "/api/v1/admin/connections/",
        json={
            "name": f"snapshot-filter-conn-{uuid.uuid4().hex[:8]}",
            "host": "oracle.example.com",
            "service_name": "SVC",
            "username": "hr",
            "password": "secret",
        },
    )
    assert connection.status_code == 201

    path = f"snapshot-filter-{uuid.uuid4().hex[:8]}"
    endpoint = ApiEndpoint(
        name=f"snapshot-filter-{uuid.uuid4().hex[:8]}",
        path=path,
        connection_id=uuid.UUID(connection.json()["id"]),
        sql_text=(
            "SELECT * FROM orders "
            "WHERE business_date BETWEEN :start_date AND :end_date "
            "AND (:store_id IS NULL OR store_id = :store_id)"
        ),
        param_schema_json={
            "start_date": {
                "type": "date",
                "required": True,
                "snapshot_filter": {"column": "business_date", "operator": "gte"},
            },
            "end_date": {
                "type": "date",
                "required": True,
                "snapshot_filter": {"column": "business_date", "operator": "lte"},
            },
            "store_id": {
                "type": "integer",
                "required": False,
                "default_is_null": True,
                "snapshot_filter": {
                    "column": "store_id",
                    "operator": "eq",
                    "null_means_all": True,
                },
            },
        },
        column_map_json={},
        allow_unauthenticated=True,
        data_strategy=DataStrategy.snapshot,
    )
    session.add(endpoint)
    await session.flush()

    run = JobRun(
        endpoint_id=endpoint.id,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status=JobRunStatus.success,
        row_count=2,
        resolved_params_json={
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "store_id": None,
        },
        trigger_source="schedule",
    )
    session.add(run)
    await session.flush()

    session.add(
        Snapshot(
            endpoint_id=endpoint.id,
            job_run_id=run.id,
            data=[
                {"business_date": "2026-08-10", "store_id": 1, "amount": 10},
                {"business_date": "2026-08-20", "store_id": 2, "amount": 20},
            ],
            row_count=2,
        )
    )
    await session.flush()
    return path


@pytest.mark.integration
async def test_snapshot_requires_declared_required_parameters(
    async_client: object,
    db_session: AsyncSession,
) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    path = await _seed_snapshot_endpoint(client, db_session)

    response = await client.get(f"/api/v1/data/{path}")

    assert response.status_code == 422
    assert "Field required" in response.json()["detail"]
    assert any(name in response.json()["detail"] for name in ("start_date", "end_date"))


@pytest.mark.integration
async def test_snapshot_filters_dates_and_store_as_data_parameters(
    async_client: object,
    db_session: AsyncSession,
) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    path = await _seed_snapshot_endpoint(client, db_session)

    response = await client.get(
        f"/api/v1/data/{path}",
        params={
            "start_date": "2026-08-15",
            "end_date": "2026-08-25",
            "store_id": "2",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == [{"business_date": "2026-08-20", "store_id": 2, "amount": 20}]
    assert response.json()["meta"]["row_count"] == 1


@pytest.mark.integration
async def test_snapshot_filters_oracle_datetime_strings_as_dates(
    async_client: object,
    db_session: AsyncSession,
) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    path = await _seed_snapshot_endpoint(client, db_session)
    endpoint = (
        await db_session.execute(select(ApiEndpoint).where(ApiEndpoint.path == path))
    ).scalar_one()
    snapshot = (
        await db_session.execute(select(Snapshot).where(Snapshot.endpoint_id == endpoint.id))
    ).scalar_one()
    snapshot.data = [
        {"business_date": "2026-08-10 00:00:00", "store_id": 1, "amount": 10},
        {"business_date": "2026-08-20 17:45:00", "store_id": 2, "amount": 20},
    ]
    await db_session.flush()

    response = await client.get(
        f"/api/v1/data/{path}",
        params={
            "start_date": "2026-08-15",
            "end_date": "2026-08-25",
            "store_id": "2",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == [
        {"business_date": "2026-08-20 17:45:00", "store_id": 2, "amount": 20}
    ]


@pytest.mark.integration
async def test_snapshot_rejects_request_outside_retained_coverage(
    async_client: object,
    db_session: AsyncSession,
) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    path = await _seed_snapshot_endpoint(client, db_session)

    response = await client.get(
        f"/api/v1/data/{path}",
        params={"start_date": "2026-09-01", "end_date": "2026-09-07"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "snapshot_out_of_coverage"


@pytest.mark.integration
async def test_snapshot_rejects_reversed_parameter_range(
    async_client: object,
    db_session: AsyncSession,
) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    path = await _seed_snapshot_endpoint(client, db_session)

    response = await client.get(
        f"/api/v1/data/{path}",
        params={"start_date": "2026-08-25", "end_date": "2026-08-15"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_parameter_range"


@pytest.mark.integration
async def test_snapshot_rejection_log_contains_required_request_context(
    async_client: object,
    db_session: AsyncSession,
) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    path = await _seed_snapshot_endpoint(client, db_session)

    with capture_logs() as logs:
        response = await client.get(
            f"/api/v1/data/{path}",
            params={"start_date": "2026-08-25", "end_date": "2026-08-15"},
            headers={"X-Request-ID": "snapshot-review-log"},
        )

    assert response.status_code == 422
    rejection = next(
        entry for entry in logs if entry.get("event") == "invalid_snapshot_parameter_range"
    )
    assert rejection["request_id"] == "snapshot-review-log"
    assert rejection["endpoint"] == path
    assert rejection["status"] == 422
    assert rejection["method"] == "GET"
    assert rejection["user"]
    assert "client_ip" in rejection
    assert rejection["duration_ms"] >= 0


@pytest.mark.integration
async def test_snapshot_returns_empty_data_for_no_matches_inside_coverage(
    async_client: object,
    db_session: AsyncSession,
) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    path = await _seed_snapshot_endpoint(client, db_session)

    response = await client.get(
        f"/api/v1/data/{path}",
        params={
            "start_date": "2026-08-21",
            "end_date": "2026-08-22",
            "store_id": "1",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["meta"]["row_count"] == 0


@pytest.mark.integration
async def test_snapshot_rejects_retained_rows_that_contradict_resolved_coverage(
    async_client: object,
    db_session: AsyncSession,
) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    path = await _seed_snapshot_endpoint(client, db_session)
    endpoint = (
        await db_session.execute(select(ApiEndpoint).where(ApiEndpoint.path == path))
    ).scalar_one()
    snapshot = (
        await db_session.execute(select(Snapshot).where(Snapshot.endpoint_id == endpoint.id))
    ).scalar_one()
    snapshot.data = [{"business_date": "0026-08-20 00:00:00", "store_id": 2, "amount": 20}]
    snapshot.row_count = 1
    await db_session.flush()

    with capture_logs() as logs:
        response = await client.get(
            f"/api/v1/data/{path}",
            params={"start_date": "2026-08-20", "end_date": "2026-08-20"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "code": "snapshot_integrity_failed",
        "detail": "No retained snapshot passed integrity validation.",
    }
    rejection = next(entry for entry in logs if entry.get("event") == "snapshot_integrity_failed")
    assert rejection["status"] == 503
    assert rejection["snapshot_ids"] == [str(snapshot.id)]
    assert "1 of 1 cached rows do not match" in rejection["integrity_errors"][0]


@pytest.mark.integration
async def test_snapshot_selects_newest_retained_snapshot_that_covers_request(
    async_client: object,
    db_session: AsyncSession,
) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    path = await _seed_snapshot_endpoint(client, db_session)
    endpoint = (
        await db_session.execute(select(ApiEndpoint).where(ApiEndpoint.path == path))
    ).scalar_one()

    newer_run = JobRun(
        endpoint_id=endpoint.id,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status=JobRunStatus.success,
        row_count=1,
        resolved_params_json={
            "start_date": "2026-08-25",
            "end_date": "2026-08-31",
            "store_id": None,
        },
        trigger_source="schedule",
    )
    db_session.add(newer_run)
    await db_session.flush()
    db_session.add(
        Snapshot(
            endpoint_id=endpoint.id,
            job_run_id=newer_run.id,
            data=[{"business_date": "2026-08-30", "store_id": 2, "amount": 30}],
            row_count=1,
            created_at=datetime.now(UTC) + timedelta(minutes=1),
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/v1/data/{path}",
        params={
            "start_date": "2026-08-20",
            "end_date": "2026-08-20",
            "store_id": "2",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == [{"business_date": "2026-08-20", "store_id": 2, "amount": 20}]


@pytest.mark.integration
async def test_snapshot_candidate_job_runs_are_loaded_in_one_batch(
    async_client: object,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    path = await _seed_snapshot_endpoint(client, db_session)
    original_get_by_ids = JobRunRepository.get_by_ids
    batch_call_count = 0

    async def tracked_get_by_ids(
        repository: JobRunRepository,
        job_run_ids: Sequence[uuid.UUID],
    ) -> Sequence[JobRun]:
        nonlocal batch_call_count
        batch_call_count += 1
        return await original_get_by_ids(repository, job_run_ids)

    monkeypatch.setattr(JobRunRepository, "get_by_ids", tracked_get_by_ids)

    response = await client.get(
        f"/api/v1/data/{path}",
        params={"start_date": "2026-08-20", "end_date": "2026-08-20"},
    )

    assert response.status_code == 200
    assert batch_call_count == 1


@pytest.mark.integration
async def test_omitted_all_value_filter_skips_fixed_value_snapshot(
    async_client: object,
    db_session: AsyncSession,
) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    path = await _seed_snapshot_endpoint(client, db_session)
    endpoint = (
        await db_session.execute(select(ApiEndpoint).where(ApiEndpoint.path == path))
    ).scalar_one()

    fixed_store_run = JobRun(
        endpoint_id=endpoint.id,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status=JobRunStatus.success,
        row_count=1,
        resolved_params_json={
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "store_id": 1,
        },
        trigger_source="schedule",
    )
    db_session.add(fixed_store_run)
    await db_session.flush()
    db_session.add(
        Snapshot(
            endpoint_id=endpoint.id,
            job_run_id=fixed_store_run.id,
            data=[{"business_date": "2026-08-20", "store_id": 1, "amount": 99}],
            row_count=1,
            created_at=datetime.now(UTC) + timedelta(minutes=1),
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/v1/data/{path}",
        params={"start_date": "2026-08-20", "end_date": "2026-08-20"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == [{"business_date": "2026-08-20", "store_id": 2, "amount": 20}]


@pytest.mark.integration
async def test_omitted_optional_filter_requires_a_null_resolved_snapshot(
    async_client: object,
    db_session: AsyncSession,
) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    path = await _seed_snapshot_endpoint(client, db_session)
    endpoint = (
        await db_session.execute(select(ApiEndpoint).where(ApiEndpoint.path == path))
    ).scalar_one()
    stored_descriptor = endpoint.param_schema_json["store_id"]
    assert isinstance(stored_descriptor, dict)
    store_descriptor = dict(stored_descriptor)
    stored_mapping = store_descriptor["snapshot_filter"]
    assert isinstance(stored_mapping, dict)
    store_mapping = dict(stored_mapping)
    store_mapping["null_means_all"] = False
    store_descriptor["snapshot_filter"] = store_mapping
    endpoint.param_schema_json = {
        **endpoint.param_schema_json,
        "store_id": store_descriptor,
    }

    fixed_store_run = JobRun(
        endpoint_id=endpoint.id,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        status=JobRunStatus.success,
        row_count=1,
        resolved_params_json={
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "store_id": 1,
        },
        trigger_source="schedule",
    )
    db_session.add(fixed_store_run)
    await db_session.flush()
    db_session.add(
        Snapshot(
            endpoint_id=endpoint.id,
            job_run_id=fixed_store_run.id,
            data=[{"business_date": "2026-08-20", "store_id": 1, "amount": 99}],
            row_count=1,
            created_at=datetime.now(UTC) + timedelta(minutes=1),
        )
    )
    await db_session.flush()

    response = await client.get(
        f"/api/v1/data/{path}",
        params={"start_date": "2026-08-20", "end_date": "2026-08-20"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == [{"business_date": "2026-08-20", "store_id": 2, "amount": 20}]


@pytest.mark.integration
async def test_legacy_snapshot_cannot_silently_ignore_unmapped_parameters(
    async_client: object,
    db_session: AsyncSession,
) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    path = await _seed_snapshot_endpoint(client, db_session)
    endpoint = (
        await db_session.execute(select(ApiEndpoint).where(ApiEndpoint.path == path))
    ).scalar_one()
    endpoint.param_schema_json = {
        name: {key: value for key, value in descriptor.items() if key != "snapshot_filter"}
        for name, descriptor in endpoint.param_schema_json.items()
        if isinstance(descriptor, dict)
    }
    await db_session.flush()

    response = await client.get(
        f"/api/v1/data/{path}",
        params={"start_date": "2026-08-15", "end_date": "2026-08-25"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "snapshot_filter_not_configured"


@pytest.mark.integration
async def test_snapshot_rejects_unavailable_cached_filter_column(
    async_client: object,
    db_session: AsyncSession,
) -> None:
    client: AsyncClient = async_client  # type: ignore[assignment]
    path = await _seed_snapshot_endpoint(client, db_session)
    endpoint = (
        await db_session.execute(select(ApiEndpoint).where(ApiEndpoint.path == path))
    ).scalar_one()
    store_descriptor = endpoint.param_schema_json["store_id"]
    assert isinstance(store_descriptor, dict)
    store_descriptor["snapshot_filter"] = {
        "column": "missing_store_column",
        "operator": "eq",
        "null_means_all": True,
    }
    await db_session.flush()

    response = await client.get(
        f"/api/v1/data/{path}",
        params={
            "start_date": "2026-08-15",
            "end_date": "2026-08-25",
            "store_id": "2",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "snapshot_filter_column_unavailable"
