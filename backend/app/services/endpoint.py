"""Endpoint service — business logic for API endpoint management.

Responsibilities:
- Validate uniqueness (name, path) before persistence.
- Validate SQL safety (bind-only, no interpolation).
- Extract bind parameters from SQL text.
- Orchestrate SQL preview execution.
- Map endpoint model to/from response schemas.
- Emit structured audit log entries.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from pydantic import ValidationError

from app.models.endpoint import ApiEndpoint, DataStrategy
from app.repositories.connection import ConnectionRepository
from app.repositories.endpoint import EndpointRepository
from app.repositories.schedule import ScheduleRepository
from app.schemas.endpoint import (
    PUBLIC_OPT_IN_MESSAGE,
    EndpointCreate,
    EndpointResponse,
    EndpointUpdate,
    ParamDescriptor,
    PublicEndpointError,
    SnapshotConfigurationError,
    SqlPreviewRequest,
    SqlPreviewResponse,
    extract_bind_params,
)
from app.services.schedule_bindings import ScheduleBindingError, resolve_schedule_parameters
from app.sql.executor import SqlExecutionError, execute_query

log = structlog.get_logger()


def _to_response(obj: ApiEndpoint) -> EndpointResponse:
    param_schema: dict[str, ParamDescriptor] = {}
    if obj.param_schema_json:
        for k, v in obj.param_schema_json.items():
            if isinstance(v, dict):
                try:
                    param_schema[k] = ParamDescriptor(**v)
                except ValidationError as exc:
                    raise SnapshotConfigurationError(
                        "Endpoint has an invalid parameter schema."
                    ) from exc

    column_map: dict[str, str] = {}
    if obj.column_map_json:
        for k, v in obj.column_map_json.items():
            if isinstance(v, str):
                column_map[k] = v

    return EndpointResponse(
        id=obj.id,
        name=obj.name,
        description=obj.description,
        path=obj.path,
        connection_id=obj.connection_id,
        sql_text=obj.sql_text,
        param_schema=param_schema,
        column_map=column_map,
        auth_method_id=obj.auth_method_id,
        allow_unauthenticated=obj.allow_unauthenticated,
        data_strategy=obj.data_strategy,
        version=obj.version,
        is_active=obj.is_active,
        is_deprecated=obj.is_deprecated,
        deprecation_note=obj.deprecation_note,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


class EndpointService:
    """Business logic layer for API endpoint management."""

    def __init__(
        self,
        repo: EndpointRepository,
        conn_repo: ConnectionRepository | None = None,
        schedule_repo: ScheduleRepository | None = None,
    ) -> None:
        self._repo = repo
        self._conn_repo = conn_repo
        self._schedule_repo = schedule_repo

    async def list_endpoints(self, *, active_only: bool = False) -> Sequence[EndpointResponse]:
        rows = await self._repo.get_all(active_only=active_only)
        return [_to_response(r) for r in rows]

    async def get_endpoint(self, endpoint_id: uuid.UUID) -> EndpointResponse | None:
        obj = await self._repo.get_by_id(endpoint_id)
        return _to_response(obj) if obj else None

    async def create_endpoint(
        self, payload: EndpointCreate, *, actor: str = "system"
    ) -> EndpointResponse:
        # Uniqueness checks
        existing_name = await self._repo.get_by_name(payload.name)
        if existing_name:
            raise ValueError(f"An endpoint named '{payload.name}' already exists.")

        existing_path = await self._repo.get_by_path(payload.path)
        if existing_path:
            raise ValueError(f"An endpoint with path '{payload.path}' already exists.")

        # Verify connection exists
        if self._conn_repo:
            conn = await self._conn_repo.get_by_id(payload.connection_id)
            if conn is None:
                raise ValueError(f"Connection '{payload.connection_id}' not found.")

        # Serialize param_schema and column_map to JSON-compatible dicts
        param_json = {k: v.model_dump() for k, v in payload.param_schema.items()}
        col_map_json = dict(payload.column_map)

        obj = ApiEndpoint(
            name=payload.name,
            description=payload.description,
            path=payload.path,
            connection_id=payload.connection_id,
            sql_text=payload.sql_text,
            param_schema_json=param_json,
            column_map_json=col_map_json,
            auth_method_id=payload.auth_method_id,
            allow_unauthenticated=payload.allow_unauthenticated,
            data_strategy=payload.data_strategy,
            is_active=payload.is_active,
        )
        obj = await self._repo.create(obj)

        log.info(
            "endpoint_created",
            endpoint_id=str(obj.id),
            name=obj.name,
            path=obj.path,
            actor=actor,
        )
        return _to_response(obj)

    async def update_endpoint(
        self,
        endpoint_id: uuid.UUID,
        payload: EndpointUpdate,
        *,
        actor: str = "system",
    ) -> EndpointResponse | None:
        obj = await self._repo.get_by_id(endpoint_id)
        if obj is None:
            return None

        _updatable = {
            "name",
            "description",
            "path",
            "connection_id",
            "sql_text",
            "auth_method_id",
            "allow_unauthenticated",
            "data_strategy",
            "is_active",
            "is_deprecated",
            "deprecation_note",
        }
        changes: dict[str, object] = {
            field: getattr(payload, field) for field in payload.model_fields_set & _updatable
        }

        # Always preserve an authentication path in the merged state: either a
        # dedicated endpoint method or the platform-admin Bearer fallback.
        effective_auth = (
            payload.auth_method_id
            if "auth_method_id" in payload.model_fields_set
            else obj.auth_method_id
        )
        effective_fallback = (
            payload.allow_unauthenticated
            if "allow_unauthenticated" in payload.model_fields_set
            else obj.allow_unauthenticated
        )
        if effective_auth is None and not effective_fallback:
            raise PublicEndpointError(PUBLIC_OPT_IN_MESSAGE)

        if "data_strategy" in payload.model_fields_set and payload.data_strategy is None:
            raise SnapshotConfigurationError("data_strategy cannot be null.")
        # Uniqueness check on name change
        if payload.name is not None and payload.name != obj.name:
            conflict = await self._repo.get_by_name(payload.name)
            if conflict:
                raise ValueError(f"An endpoint named '{payload.name}' already exists.")

        # Uniqueness check on path change
        if payload.path is not None and payload.path != obj.path:
            conflict = await self._repo.get_by_path(payload.path)
            if conflict:
                raise ValueError(f"An endpoint with path '{payload.path}' already exists.")

        effective_param_schema: dict[str, object] = obj.param_schema_json or {}

        # Handle param_schema serialization
        if "param_schema" in payload.model_fields_set and payload.param_schema is not None:
            effective_param_schema = {
                k: v.model_dump() for k, v in payload.param_schema.items()
            }
            changes["param_schema_json"] = effective_param_schema
            changes.pop("param_schema", None)

        # Handle column_map serialization
        if "column_map" in payload.model_fields_set and payload.column_map is not None:
            changes["column_map_json"] = dict(payload.column_map)
            changes.pop("column_map", None)

        if self._schedule_repo is not None:
            schedule = await self._schedule_repo.get_by_endpoint_id(endpoint_id)
            if schedule is not None:
                effective_strategy = payload.data_strategy or obj.data_strategy
                if effective_strategy != DataStrategy.snapshot:
                    raise ScheduleBindingError(
                        "Delete the attached schedule before changing this endpoint to live data."
                    )

                effective_sql = payload.sql_text or obj.sql_text
                sql_params = set(extract_bind_params(effective_sql))
                schema_params = set(effective_param_schema)
                if sql_params != schema_params:
                    raise ScheduleBindingError(
                        "Endpoint SQL and parameter schema must continue to match while a schedule "
                        "is attached."
                    )

                resolve_schedule_parameters(
                    param_schema=effective_param_schema,
                    parameter_bindings=schedule.parameter_bindings_json or {},
                    timezone_name=schedule.timezone,
                    scheduled_for=datetime.now(UTC),
                    window=schedule.window_config_json,
                )

        obj = await self._repo.update(obj, changes)

        log.info(
            "endpoint_updated",
            endpoint_id=str(obj.id),
            name=obj.name,
            changed_fields=list(changes.keys()),
            actor=actor,
        )
        return _to_response(obj)

    async def delete_endpoint(self, endpoint_id: uuid.UUID, *, actor: str = "system") -> bool:
        obj = await self._repo.get_by_id(endpoint_id)
        if obj is None:
            return False

        name = obj.name
        await self._repo.delete(obj)

        log.info(
            "endpoint_deleted",
            endpoint_id=str(endpoint_id),
            name=name,
            actor=actor,
        )
        return True

    async def preview_sql(self, payload: SqlPreviewRequest) -> SqlPreviewResponse:
        """Execute SQL in preview mode and return sample results."""
        if not self._conn_repo:
            raise ValueError("Connection repository not available for preview.")

        conn = await self._conn_repo.get_by_id(payload.connection_id)
        if conn is None:
            raise ValueError(f"Connection '{payload.connection_id}' not found.")

        if not conn.is_active:
            raise ValueError("Connection is not active.")

        bind_params = extract_bind_params(payload.sql_text)

        try:
            columns, rows, duration_ms = await execute_query(
                connection=conn,
                sql=payload.sql_text,
                params=dict(payload.params),
                max_rows=payload.max_rows,
            )
        except SqlExecutionError as exc:
            raise ValueError(str(exc)) from exc

        return SqlPreviewResponse(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            bind_params=bind_params,
            duration_ms=duration_ms,
        )
