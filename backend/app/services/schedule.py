"""Schedule service — business logic for schedule management.

Responsibilities:
- Validate schedule configuration.
- CRUD operations with uniqueness checks (one schedule per endpoint).
- Control actions: run now, pause/resume.
- Integrate with APScheduler via scheduler service.
- Emit structured audit log entries.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import structlog

from app.models.endpoint import DataStrategy
from app.models.schedule import Schedule
from app.repositories.endpoint import EndpointRepository
from app.repositories.job_run import JobRunRepository
from app.repositories.schedule import ScheduleRepository
from app.repositories.snapshot import SnapshotRepository
from app.schemas.schedule import (
    JobRunResponse,
    ScheduleCreate,
    ScheduleParameterBinding,
    SchedulePreviewRequest,
    SchedulePreviewResponse,
    ScheduleResponse,
    ScheduleRunRequest,
    ScheduleUpdate,
    ScheduleWindow,
    SnapshotDetailResponse,
    SnapshotResponse,
)
from app.services.schedule_bindings import (
    ScheduleBindingError,
    preview_schedule_runs,
    resolve_schedule_parameters,
)
from app.services.scheduler import (
    add_schedule_job,
    execute_scheduled_job,
    pause_schedule_job,
    remove_schedule_job,
    resume_schedule_job,
)

log = structlog.get_logger()


def _to_response(obj: Schedule) -> ScheduleResponse:
    parameter_bindings = {
        name: ScheduleParameterBinding.model_validate(binding)
        for name, binding in (obj.parameter_bindings_json or {}).items()
    }
    window = (
        ScheduleWindow.model_validate(obj.window_config_json) if obj.window_config_json else None
    )
    return ScheduleResponse(
        id=obj.id,
        endpoint_id=obj.endpoint_id,
        schedule_type=obj.schedule_type,
        cron_expression=obj.cron_expression,
        interval_seconds=obj.interval_seconds,
        timezone=obj.timezone,
        parameter_bindings=parameter_bindings,
        window=window,
        is_active=obj.is_active,
        last_run_at=obj.last_run_at,
        next_run_at=obj.next_run_at,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


def _bindings_to_json(
    bindings: dict[str, ScheduleParameterBinding],
) -> dict[str, object]:
    return {name: binding.model_dump(mode="json") for name, binding in bindings.items()}


def _window_to_json(window: ScheduleWindow | None) -> dict[str, object] | None:
    return window.model_dump(mode="json") if window is not None else None


def _validate_snapshot_bindings(
    *,
    endpoint_strategy: DataStrategy,
    param_schema: dict[str, object],
    parameter_bindings: dict[str, ScheduleParameterBinding] | dict[str, object],
    timezone: str,
    window: ScheduleWindow | dict[str, object] | None,
) -> None:
    if endpoint_strategy != DataStrategy.snapshot:
        raise ScheduleBindingError("Schedules are supported only for snapshot endpoints.")
    resolve_schedule_parameters(
        param_schema=param_schema,
        parameter_bindings=parameter_bindings,
        timezone_name=timezone,
        scheduled_for=datetime.now(UTC),
        window=window,
    )


def _validate_schedule_timing(
    *,
    schedule_type: str,
    cron_expression: str | None,
    interval_seconds: int | None,
) -> None:
    if schedule_type == "cron" and not cron_expression:
        raise ValueError("cron_expression is required when schedule_type is 'cron'.")
    if schedule_type == "interval" and not interval_seconds:
        raise ValueError("interval_seconds is required when schedule_type is 'interval'.")


class ScheduleService:
    """Business logic layer for schedule management."""

    def __init__(
        self,
        repo: ScheduleRepository,
        ep_repo: EndpointRepository | None = None,
        job_repo: JobRunRepository | None = None,
        snap_repo: SnapshotRepository | None = None,
    ) -> None:
        self._repo = repo
        self._ep_repo = ep_repo
        self._job_repo = job_repo
        self._snap_repo = snap_repo

    async def list_schedules(self, *, active_only: bool = False) -> Sequence[ScheduleResponse]:
        rows = await self._repo.get_all(active_only=active_only)
        return [_to_response(r) for r in rows]

    async def get_schedule(self, schedule_id: uuid.UUID) -> ScheduleResponse | None:
        obj = await self._repo.get_by_id(schedule_id)
        return _to_response(obj) if obj else None

    async def create_schedule(
        self, payload: ScheduleCreate, *, actor: str = "system"
    ) -> ScheduleResponse:
        # Verify endpoint exists
        if self._ep_repo:
            ep = await self._ep_repo.get_by_id(payload.endpoint_id)
            if ep is None:
                raise ValueError(f"Endpoint '{payload.endpoint_id}' not found.")
            _validate_snapshot_bindings(
                endpoint_strategy=ep.data_strategy,
                param_schema=ep.param_schema_json or {},
                parameter_bindings=payload.parameter_bindings,
                timezone=payload.timezone,
                window=payload.window,
            )

        # Check uniqueness — one schedule per endpoint
        existing = await self._repo.get_by_endpoint_id(payload.endpoint_id)
        if existing:
            raise ValueError(f"A schedule already exists for endpoint '{payload.endpoint_id}'.")

        obj = Schedule(
            endpoint_id=payload.endpoint_id,
            schedule_type=payload.schedule_type,
            cron_expression=payload.cron_expression,
            interval_seconds=payload.interval_seconds,
            timezone=payload.timezone,
            parameter_bindings_json=_bindings_to_json(payload.parameter_bindings),
            window_config_json=_window_to_json(payload.window),
            is_active=payload.is_active,
        )
        obj = await self._repo.create(obj)

        # Register with APScheduler if active
        if obj.is_active:
            next_run_at = add_schedule_job(
                schedule_id=obj.id,
                endpoint_id=obj.endpoint_id,
                schedule_type=obj.schedule_type,
                cron_expression=obj.cron_expression,
                interval_seconds=obj.interval_seconds,
                timezone_name=obj.timezone,
            )
            if next_run_at is not None:
                obj = await self._repo.update(obj, {"next_run_at": next_run_at})

        log.info(
            "schedule_created",
            schedule_id=str(obj.id),
            endpoint_id=str(obj.endpoint_id),
            schedule_type=obj.schedule_type,
            actor=actor,
        )
        return _to_response(obj)

    async def update_schedule(
        self,
        schedule_id: uuid.UUID,
        payload: ScheduleUpdate,
        *,
        actor: str = "system",
    ) -> ScheduleResponse | None:
        obj = await self._repo.get_by_id(schedule_id)
        if obj is None:
            return None

        _updatable = {
            "schedule_type",
            "cron_expression",
            "interval_seconds",
            "timezone",
            "parameter_bindings",
            "window",
            "is_active",
        }
        for field in {"schedule_type", "timezone", "parameter_bindings", "is_active"}:
            if field in payload.model_fields_set and getattr(payload, field) is None:
                raise ValueError(f"{field} cannot be null.")

        effective_schedule_type = payload.schedule_type or obj.schedule_type
        effective_cron_expression = (
            payload.cron_expression
            if "cron_expression" in payload.model_fields_set
            else obj.cron_expression
        )
        effective_interval_seconds = (
            payload.interval_seconds
            if "interval_seconds" in payload.model_fields_set
            else obj.interval_seconds
        )
        _validate_schedule_timing(
            schedule_type=effective_schedule_type,
            cron_expression=effective_cron_expression,
            interval_seconds=effective_interval_seconds,
        )

        changes: dict[str, object] = {}
        for field in payload.model_fields_set & _updatable:
            if field == "parameter_bindings":
                changes["parameter_bindings_json"] = _bindings_to_json(
                    payload.parameter_bindings or {}
                )
            elif field == "window":
                changes["window_config_json"] = _window_to_json(payload.window)
            else:
                changes[field] = getattr(payload, field)

        if self._ep_repo:
            endpoint = await self._ep_repo.get_by_id(obj.endpoint_id)
            if endpoint is None:
                raise ValueError(f"Endpoint '{obj.endpoint_id}' not found.")
            effective_bindings: dict[str, ScheduleParameterBinding] | dict[str, object]
            if "parameter_bindings" in payload.model_fields_set:
                effective_bindings = payload.parameter_bindings or {}
            else:
                effective_bindings = obj.parameter_bindings_json or {}
            effective_window: ScheduleWindow | dict[str, object] | None
            if "window" in payload.model_fields_set:
                effective_window = payload.window
            else:
                effective_window = obj.window_config_json
            _validate_snapshot_bindings(
                endpoint_strategy=endpoint.data_strategy,
                param_schema=endpoint.param_schema_json or {},
                parameter_bindings=effective_bindings,
                timezone=payload.timezone or obj.timezone,
                window=effective_window,
            )

        obj = await self._repo.update(obj, changes)

        # Sync with APScheduler
        if obj.is_active:
            next_run_at = add_schedule_job(
                schedule_id=obj.id,
                endpoint_id=obj.endpoint_id,
                schedule_type=obj.schedule_type,
                cron_expression=obj.cron_expression,
                interval_seconds=obj.interval_seconds,
                timezone_name=obj.timezone,
            )
            if next_run_at is not None:
                obj = await self._repo.update(obj, {"next_run_at": next_run_at})
        else:
            remove_schedule_job(obj.id)

        log.info(
            "schedule_updated",
            schedule_id=str(obj.id),
            changed_fields=list(changes.keys()),
            actor=actor,
        )
        return _to_response(obj)

    async def delete_schedule(self, schedule_id: uuid.UUID, *, actor: str = "system") -> bool:
        obj = await self._repo.get_by_id(schedule_id)
        if obj is None:
            return False

        await self._repo.delete(obj)

        log.info(
            "schedule_deleted",
            schedule_id=str(schedule_id),
            endpoint_id=str(obj.endpoint_id),
            actor=actor,
        )
        return True

    async def run_now(
        self, schedule_id: uuid.UUID, payload: ScheduleRunRequest | None = None
    ) -> None:
        """Trigger immediate execution of a schedule's job."""
        obj = await self._repo.get_by_id(schedule_id)
        if obj is None:
            raise ValueError("Schedule not found.")

        log.info("schedule_run_now", schedule_id=str(schedule_id))
        scheduled_for = None
        if payload is not None and payload.logical_date is not None:
            scheduled_for = datetime.combine(
                payload.logical_date,
                time.min,
                tzinfo=ZoneInfo(obj.timezone),
            )
        await execute_scheduled_job(
            str(schedule_id),
            str(obj.endpoint_id),
            scheduled_for=scheduled_for,
            trigger_source="manual",
        )

    async def preview_schedule(self, payload: SchedulePreviewRequest) -> SchedulePreviewResponse:
        if not self._ep_repo:
            raise ValueError("Endpoint repository not available.")
        endpoint = await self._ep_repo.get_by_id(payload.endpoint_id)
        if endpoint is None:
            raise ValueError(f"Endpoint '{payload.endpoint_id}' not found.")
        _validate_snapshot_bindings(
            endpoint_strategy=endpoint.data_strategy,
            param_schema=endpoint.param_schema_json or {},
            parameter_bindings=payload.parameter_bindings,
            timezone=payload.timezone,
            window=payload.window,
        )
        runs = preview_schedule_runs(
            schedule_type=payload.schedule_type,
            cron_expression=payload.cron_expression,
            interval_seconds=payload.interval_seconds,
            timezone_name=payload.timezone,
            param_schema=endpoint.param_schema_json or {},
            parameter_bindings=payload.parameter_bindings,
            window=payload.window,
            count=payload.count,
        )
        return SchedulePreviewResponse(runs=runs)

    async def pause(self, schedule_id: uuid.UUID) -> ScheduleResponse | None:
        """Pause a schedule."""
        obj = await self._repo.get_by_id(schedule_id)
        if obj is None:
            return None

        obj = await self._repo.update(obj, {"is_active": False})
        pause_schedule_job(obj.id)

        log.info("schedule_paused", schedule_id=str(schedule_id))
        return _to_response(obj)

    async def resume(self, schedule_id: uuid.UUID) -> ScheduleResponse | None:
        """Resume a paused schedule."""
        obj = await self._repo.get_by_id(schedule_id)
        if obj is None:
            return None

        obj = await self._repo.update(obj, {"is_active": True})
        resume_schedule_job(obj.id)

        # Re-register the job to ensure it's in APScheduler
        next_run_at = add_schedule_job(
            schedule_id=obj.id,
            endpoint_id=obj.endpoint_id,
            schedule_type=obj.schedule_type,
            cron_expression=obj.cron_expression,
            interval_seconds=obj.interval_seconds,
            timezone_name=obj.timezone,
        )
        if next_run_at is not None:
            obj = await self._repo.update(obj, {"next_run_at": next_run_at})

        log.info("schedule_resumed", schedule_id=str(schedule_id))
        return _to_response(obj)

    # ── Job run queries ──────────────────────────────────────────────────

    async def list_job_runs(
        self,
        *,
        schedule_id: uuid.UUID | None = None,
        endpoint_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> Sequence[JobRunResponse]:
        if not self._job_repo:
            raise ValueError("Job run repository not available.")
        rows = await self._job_repo.get_all(
            schedule_id=schedule_id,
            endpoint_id=endpoint_id,
            limit=limit,
        )
        return [
            JobRunResponse(
                id=r.id,
                schedule_id=r.schedule_id,
                endpoint_id=r.endpoint_id,
                started_at=r.started_at,
                finished_at=r.finished_at,
                status=r.status,
                row_count=r.row_count,
                error_detail=r.error_detail,
                scheduled_for=r.scheduled_for,
                logical_date=r.logical_date,
                window_start=r.window_start,
                window_end=r.window_end,
                resolved_parameters=r.resolved_params_json,
                trigger_source=r.trigger_source,
                binding_hash=r.binding_hash,
                created_at=r.created_at,
            )
            for r in rows
        ]

    # ── Snapshot queries ─────────────────────────────────────────────────

    async def list_snapshots(
        self, endpoint_id: uuid.UUID, *, limit: int = 10
    ) -> Sequence[SnapshotResponse]:
        if not self._snap_repo:
            raise ValueError("Snapshot repository not available.")
        rows = await self._snap_repo.get_by_endpoint(endpoint_id, limit=limit)
        return [
            SnapshotResponse(
                id=r.id,
                endpoint_id=r.endpoint_id,
                job_run_id=r.job_run_id,
                row_count=r.row_count,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def get_snapshot(self, snapshot_id: uuid.UUID) -> SnapshotDetailResponse | None:
        if not self._snap_repo:
            raise ValueError("Snapshot repository not available.")
        snap = await self._snap_repo.get_by_id(snapshot_id)
        if snap is None:
            return None
        return SnapshotDetailResponse(
            id=snap.id,
            endpoint_id=snap.endpoint_id,
            job_run_id=snap.job_run_id,
            data=snap.data if isinstance(snap.data, list) else [],
            row_count=snap.row_count,
            created_at=snap.created_at,
        )
