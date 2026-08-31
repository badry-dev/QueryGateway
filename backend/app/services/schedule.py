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

import structlog

from app.models.schedule import Schedule
from app.repositories.endpoint import EndpointRepository
from app.repositories.job_run import JobRunRepository
from app.repositories.schedule import ScheduleRepository
from app.repositories.snapshot import SnapshotRepository
from app.schemas.endpoint import require_snapshot_defaults
from app.schemas.schedule import (
    JobRunResponse,
    ScheduleCreate,
    ScheduleResponse,
    ScheduleUpdate,
    SnapshotDetailResponse,
    SnapshotResponse,
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
    return ScheduleResponse(
        id=obj.id,
        endpoint_id=obj.endpoint_id,
        schedule_type=obj.schedule_type,
        cron_expression=obj.cron_expression,
        interval_seconds=obj.interval_seconds,
        is_active=obj.is_active,
        last_run_at=obj.last_run_at,
        next_run_at=obj.next_run_at,
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


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

    async def list_schedules(
        self, *, active_only: bool = False
    ) -> Sequence[ScheduleResponse]:
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
            require_snapshot_defaults(ep.data_strategy, ep.param_schema_json or {})

        # Check uniqueness — one schedule per endpoint
        existing = await self._repo.get_by_endpoint_id(payload.endpoint_id)
        if existing:
            raise ValueError(
                f"A schedule already exists for endpoint '{payload.endpoint_id}'."
            )

        obj = Schedule(
            endpoint_id=payload.endpoint_id,
            schedule_type=payload.schedule_type,
            cron_expression=payload.cron_expression,
            interval_seconds=payload.interval_seconds,
            is_active=payload.is_active,
        )
        obj = await self._repo.create(obj)

        # Register with APScheduler if active
        if obj.is_active:
            add_schedule_job(
                schedule_id=obj.id,
                endpoint_id=obj.endpoint_id,
                schedule_type=obj.schedule_type,
                cron_expression=obj.cron_expression,
                interval_seconds=obj.interval_seconds,
            )

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
            "is_active",
        }
        changes: dict[str, object] = {
            field: getattr(payload, field)
            for field in payload.model_fields_set & _updatable
        }

        obj = await self._repo.update(obj, changes)

        # Sync with APScheduler
        if obj.is_active:
            add_schedule_job(
                schedule_id=obj.id,
                endpoint_id=obj.endpoint_id,
                schedule_type=obj.schedule_type,
                cron_expression=obj.cron_expression,
                interval_seconds=obj.interval_seconds,
            )
        else:
            remove_schedule_job(obj.id)

        log.info(
            "schedule_updated",
            schedule_id=str(obj.id),
            changed_fields=list(changes.keys()),
            actor=actor,
        )
        return _to_response(obj)

    async def delete_schedule(
        self, schedule_id: uuid.UUID, *, actor: str = "system"
    ) -> bool:
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

    async def run_now(self, schedule_id: uuid.UUID) -> None:
        """Trigger immediate execution of a schedule's job."""
        obj = await self._repo.get_by_id(schedule_id)
        if obj is None:
            raise ValueError("Schedule not found.")

        log.info("schedule_run_now", schedule_id=str(schedule_id))
        await execute_scheduled_job(str(schedule_id), str(obj.endpoint_id))

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
        add_schedule_job(
            schedule_id=obj.id,
            endpoint_id=obj.endpoint_id,
            schedule_type=obj.schedule_type,
            cron_expression=obj.cron_expression,
            interval_seconds=obj.interval_seconds,
        )

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

    async def get_snapshot(
        self, snapshot_id: uuid.UUID
    ) -> SnapshotDetailResponse | None:
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
