"""APScheduler integration — lifecycle and job execution.

Responsibilities:
- Start/stop APScheduler with FastAPI lifespan.
- Execute scheduled snapshot refresh jobs.
- Persist job runs and snapshots.
- Update schedule metadata (last_run_at, next_run_at).

The scheduler uses APScheduler's in-memory job store. Active schedules are
rehydrated from the application database whenever the process starts.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.job_run import JobRun, JobRunStatus
from app.models.snapshot import Snapshot
from app.repositories.connection import ConnectionRepository
from app.repositories.endpoint import EndpointRepository
from app.repositories.job_run import JobRunRepository
from app.repositories.schedule import ScheduleRepository
from app.repositories.snapshot import SnapshotRepository
from app.schemas.schedule import ScheduleWindow
from app.services.schedule_bindings import resolve_schedule_parameters
from app.sql.executor import execute_query

log = structlog.get_logger().bind(
    request_id=None,
    user="scheduler",
    endpoint=None,
    status=None,
    duration_ms=None,
    method="SCHEDULE",
    client_ip=None,
)

# Module-level scheduler instance — initialized in start_scheduler().
_scheduler: Any = None


def _get_sync_database_url() -> str:
    """Convert async database URL to sync for APScheduler job store."""
    url = settings.database_url
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return url


def get_scheduler() -> Any:
    """Return the running scheduler instance (or None)."""
    return _scheduler


def _binding_hash(
    *,
    timezone_name: str,
    parameter_bindings: dict[str, object],
    window: dict[str, object] | None,
) -> str:
    payload = {
        "timezone": timezone_name,
        "parameter_bindings": parameter_bindings,
        "window": window,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _get_next_run_at(schedule_id: uuid.UUID) -> datetime | None:
    if _scheduler is None:
        return None
    try:
        job = _scheduler.get_job(str(schedule_id))
        next_run_time = getattr(job, "next_run_time", None)
        return next_run_time if isinstance(next_run_time, datetime) else None
    except Exception:  # noqa: BLE001
        return None


async def execute_scheduled_job(
    schedule_id: str,
    endpoint_id: str,
    *,
    scheduled_for: datetime | None = None,
    trigger_source: str = "scheduled",
) -> None:
    """Execute a single scheduled job — query Oracle, save snapshot.

    This function is called by APScheduler in a thread. We create our own
    async DB session so we are independent of any request context.
    """
    sid = uuid.UUID(schedule_id)
    eid = uuid.UUID(endpoint_id)
    run_id = uuid.uuid4()
    started_at = datetime.now(UTC)

    log.info(
        "scheduled_job_start",
        job_id=schedule_id,
        run_id=str(run_id),
        endpoint_id=endpoint_id,
    )

    async with AsyncSessionLocal() as db:
        job_repo = JobRunRepository(db)
        snap_repo = SnapshotRepository(db)
        sched_repo = ScheduleRepository(db)
        ep_repo = EndpointRepository(db)
        conn_repo = ConnectionRepository(db)

        schedule = await sched_repo.get_by_id(sid)
        if schedule is None:
            log.error(
                "scheduled_job_missing_schedule",
                job_id=schedule_id,
                endpoint_id=endpoint_id,
            )
            return

        logical_run_time = (
            scheduled_for
            or (schedule.next_run_at if trigger_source == "scheduled" else started_at)
            or started_at
        )
        if logical_run_time.tzinfo is None:
            logical_run_time = logical_run_time.replace(tzinfo=UTC)

        existing_run = await job_repo.get_by_schedule_and_scheduled_for(sid, logical_run_time)
        if existing_run is not None:
            log.info(
                "scheduled_job_duplicate_skipped",
                job_id=schedule_id,
                existing_run_id=str(existing_run.id),
                scheduled_for=logical_run_time.isoformat(),
            )
            return

        binding_hash = _binding_hash(
            timezone_name=schedule.timezone,
            parameter_bindings=schedule.parameter_bindings_json or {},
            window=schedule.window_config_json,
        )

        # Create a running job record before external I/O. The unique logical
        # run key makes retries/multiple workers idempotent for a given fire time.
        job_run = JobRun(
            id=run_id,
            schedule_id=sid,
            endpoint_id=eid,
            started_at=started_at,
            status=JobRunStatus.running,
            scheduled_for=logical_run_time,
            trigger_source=trigger_source,
            binding_hash=binding_hash,
        )
        try:
            await job_repo.create(job_run)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            log.info(
                "scheduled_job_duplicate_skipped",
                job_id=schedule_id,
                scheduled_for=logical_run_time.isoformat(),
            )
            return

        try:
            # Load endpoint and connection
            endpoint = await ep_repo.get_by_id(eid)
            if endpoint is None:
                raise ValueError(f"Endpoint {eid} not found.")

            if not endpoint.is_active:
                raise ValueError(f"Endpoint {eid} is not active.")

            param_schema = endpoint.param_schema_json or {}
            window = (
                ScheduleWindow.model_validate(schedule.window_config_json)
                if schedule.window_config_json
                else None
            )
            context = resolve_schedule_parameters(
                param_schema=param_schema,
                parameter_bindings=schedule.parameter_bindings_json or {},
                timezone_name=schedule.timezone,
                scheduled_for=logical_run_time,
                window=window,
            )
            resolved_parameters = jsonable_encoder(context.parameters)
            await job_repo.update(
                job_run,
                {
                    "logical_date": context.logical_date,
                    "window_start": context.window_start,
                    "window_end": context.window_end,
                    "resolved_params_json": resolved_parameters,
                },
            )
            await db.commit()
            params = context.parameters

            connection = await conn_repo.get_by_id(endpoint.connection_id)
            if connection is None or not connection.is_active:
                raise ValueError("Data source connection is unavailable.")

            columns, rows, duration_ms = await execute_query(
                connection=connection,
                sql=endpoint.sql_text,
                params=params,
                max_rows=10000,
            )

            # Apply column mapping
            column_map = endpoint.column_map_json or {}
            if column_map:
                mapped_rows: list[dict[str, object]] = []
                for row in rows:
                    new_row: dict[str, object] = {}
                    for key, value in row.items():
                        output_key = column_map.get(key)
                        if isinstance(output_key, str):
                            new_row[output_key] = value
                        else:
                            new_row[key] = value
                    mapped_rows.append(new_row)
                rows = mapped_rows

            # Save snapshot
            snapshot = Snapshot(
                endpoint_id=eid,
                job_run_id=run_id,
                data=rows,
                row_count=len(rows),
            )
            await snap_repo.create(snapshot)

            # Clean up old snapshots according to configured retention.
            # snapshot_retention_count is a runtime DB setting (default: 5).
            from app.repositories.settings import SettingsRepository  # noqa: PLC0415

            settings_repo = SettingsRepository(db)
            retention_setting = await settings_repo.get_by_key("snapshot_retention_count")
            retention_count = int(retention_setting.value) if retention_setting else 5
            await snap_repo.delete_old(eid, keep=retention_count)

            # Mark job success
            finished_at = datetime.now(UTC)
            await job_repo.update(
                job_run,
                {
                    "finished_at": finished_at,
                    "status": JobRunStatus.success,
                    "row_count": len(rows),
                },
            )

            # Update schedule last_run_at
            current_schedule = await sched_repo.get_by_id(sid)
            if current_schedule:
                schedule_changes: dict[str, object] = {
                    "last_run_at": finished_at,
                }
                next_run_at = _get_next_run_at(sid)
                if next_run_at is not None:
                    schedule_changes["next_run_at"] = next_run_at
                await sched_repo.update(current_schedule, schedule_changes)

            await db.commit()

            log.info(
                "scheduled_job_success",
                job_id=schedule_id,
                run_id=str(run_id),
                endpoint_id=endpoint_id,
                row_count=len(rows),
                duration_ms=duration_ms,
                scheduled_for=logical_run_time.isoformat(),
                logical_date=context.logical_date.isoformat(),
                binding_hash=binding_hash,
                success=True,
            )

        except Exception as exc:  # noqa: BLE001
            finished_at = datetime.now(UTC)
            error_detail = str(exc)[:5000]

            status = JobRunStatus.failed
            if "timeout" in error_detail.lower():
                status = JobRunStatus.timeout

            await job_repo.update(
                job_run,
                {
                    "finished_at": finished_at,
                    "status": status,
                    "error_detail": error_detail,
                },
            )

            # Update schedule last_run_at even on failure
            current_schedule = await sched_repo.get_by_id(sid)
            if current_schedule:
                schedule_changes = {
                    "last_run_at": finished_at,
                }
                next_run_at = _get_next_run_at(sid)
                if next_run_at is not None:
                    schedule_changes["next_run_at"] = next_run_at
                await sched_repo.update(current_schedule, schedule_changes)

            await db.commit()

            log.error(
                "scheduled_job_failed",
                job_id=schedule_id,
                run_id=str(run_id),
                endpoint_id=endpoint_id,
                scheduled_for=logical_run_time.isoformat(),
                binding_hash=binding_hash,
                error=error_detail,
                success=False,
            )


async def restore_active_schedules() -> int:
    """Register all active database schedules in the in-memory scheduler."""
    restored = 0
    failed_schedule_ids: list[str] = []
    async with AsyncSessionLocal() as db:
        schedule_repo = ScheduleRepository(db)
        schedules = await schedule_repo.get_all(active_only=True)
        updated_next_run = False
        for schedule in schedules:
            try:
                next_run_at = add_schedule_job(
                    schedule_id=schedule.id,
                    endpoint_id=schedule.endpoint_id,
                    schedule_type=schedule.schedule_type,
                    cron_expression=schedule.cron_expression,
                    interval_seconds=schedule.interval_seconds,
                    timezone_name=getattr(schedule, "timezone", "UTC"),
                )
                if not isinstance(next_run_at, datetime):
                    raise ValueError("Schedule configuration could not be registered.")
                await schedule_repo.update(schedule, {"next_run_at": next_run_at})
                updated_next_run = True
                restored += 1
            except Exception as exc:  # noqa: BLE001
                failed_schedule_ids.append(str(schedule.id))
                log.error(
                    "scheduler_job_restore_failed",
                    schedule_id=str(schedule.id),
                    error=str(exc),
                )
        if updated_next_run:
            await db.commit()
    if failed_schedule_ids:
        failed = ", ".join(failed_schedule_ids)
        raise RuntimeError(f"Failed to restore active schedules: {failed}")
    log.info("scheduler_jobs_restored", restored_count=restored)
    return restored


async def start_scheduler() -> None:
    """Initialize and start the APScheduler instance."""
    global _scheduler  # noqa: PLW0603

    scheduler = None
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # noqa: PLC0415

        scheduler = AsyncIOScheduler(
            timezone=ZoneInfo("UTC"),
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 60,
            },
        )
        scheduler.start()
        _scheduler = scheduler
        log.info("scheduler_started")
        await restore_active_schedules()
    except Exception as exc:  # noqa: BLE001
        if _scheduler is not None:
            stop_scheduler()
        elif scheduler is not None:
            try:
                scheduler.shutdown(wait=False)
            except Exception as shutdown_exc:  # noqa: BLE001
                log.warning("scheduler_cleanup_failed", error=str(shutdown_exc))
        log.error("scheduler_start_failed", error=str(exc))
        raise


def stop_scheduler() -> None:
    """Shut down the scheduler gracefully."""
    global _scheduler  # noqa: PLW0603
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
            log.info("scheduler_stopped")
        except Exception as exc:  # noqa: BLE001
            log.warning("scheduler_stop_error", error=str(exc))
        _scheduler = None


def add_schedule_job(
    schedule_id: uuid.UUID,
    endpoint_id: uuid.UUID,
    schedule_type: str,
    cron_expression: str | None = None,
    interval_seconds: int | None = None,
    timezone_name: str = "UTC",
) -> datetime | None:
    """Register a job in APScheduler."""
    if _scheduler is None:
        log.warning("scheduler_not_running", action="add_job")
        return None

    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # noqa: PLC0415

    scheduler: AsyncIOScheduler = _scheduler

    job_id = str(schedule_id)

    # Remove existing job if present
    try:
        scheduler.remove_job(job_id)
    except Exception:  # noqa: BLE001
        log.debug("scheduler_job_not_found", job_id=job_id)

    kwargs = {
        "func": execute_scheduled_job,
        "id": job_id,
        "args": [str(schedule_id), str(endpoint_id)],
        "replace_existing": True,
    }

    if schedule_type == "cron" and cron_expression:
        parts = cron_expression.strip().split()
        kwargs["trigger"] = "cron"
        kwargs["minute"] = parts[0]
        kwargs["hour"] = parts[1]
        kwargs["day"] = parts[2]
        kwargs["month"] = parts[3]
        kwargs["day_of_week"] = parts[4]
        kwargs["timezone"] = ZoneInfo(timezone_name)
    elif schedule_type == "interval" and interval_seconds:
        kwargs["trigger"] = "interval"
        kwargs["seconds"] = interval_seconds
        kwargs["timezone"] = ZoneInfo(timezone_name)
    else:
        log.warning("invalid_schedule_config", schedule_id=str(schedule_id))
        return None

    job = scheduler.add_job(**kwargs)
    log.info(
        "scheduler_job_added",
        job_id=job_id,
        schedule_type=schedule_type,
        timezone=timezone_name,
    )
    next_run_time = getattr(job, "next_run_time", None)
    return next_run_time if isinstance(next_run_time, datetime) else None


def remove_schedule_job(schedule_id: uuid.UUID) -> None:
    """Remove a job from APScheduler."""
    if _scheduler is None:
        return

    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # noqa: PLC0415

    scheduler: AsyncIOScheduler = _scheduler

    try:
        scheduler.remove_job(str(schedule_id))
        log.info("scheduler_job_removed", job_id=str(schedule_id))
    except Exception:  # noqa: BLE001
        log.debug("scheduler_job_not_found", job_id=str(schedule_id))


def pause_schedule_job(schedule_id: uuid.UUID) -> None:
    """Pause a job in APScheduler."""
    if _scheduler is None:
        return

    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # noqa: PLC0415

    scheduler: AsyncIOScheduler = _scheduler

    try:
        scheduler.pause_job(str(schedule_id))
        log.info("scheduler_job_paused", job_id=str(schedule_id))
    except Exception:  # noqa: BLE001
        log.debug("scheduler_job_not_found", job_id=str(schedule_id))


def resume_schedule_job(schedule_id: uuid.UUID) -> None:
    """Resume a paused job in APScheduler."""
    if _scheduler is None:
        return

    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # noqa: PLC0415

    scheduler: AsyncIOScheduler = _scheduler

    try:
        scheduler.resume_job(str(schedule_id))
        log.info("scheduler_job_resumed", job_id=str(schedule_id))
    except Exception:  # noqa: BLE001
        log.debug("scheduler_job_not_found", job_id=str(schedule_id))
