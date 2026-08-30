"""APScheduler integration — lifecycle and job execution.

Responsibilities:
- Start/stop APScheduler with FastAPI lifespan.
- Execute scheduled snapshot refresh jobs.
- Persist job runs and snapshots.
- Update schedule metadata (last_run_at, next_run_at).

The scheduler uses APScheduler's in-memory job store. Active schedules are
rehydrated from the application database whenever the process starts.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.job_run import JobRun, JobRunStatus
from app.models.snapshot import Snapshot
from app.repositories.connection import ConnectionRepository
from app.repositories.endpoint import EndpointRepository
from app.repositories.job_run import JobRunRepository
from app.repositories.schedule import ScheduleRepository
from app.repositories.snapshot import SnapshotRepository
from app.sql.executor import SqlExecutionError, execute_query
from app.sql.param_models import build_param_model

log = structlog.get_logger()

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


def resolve_scheduled_params(param_schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve every scheduled bind default, retaining explicit SQL NULLs."""
    ParamModel = build_param_model(param_schema)
    return ParamModel.model_validate({}).model_dump()


async def execute_scheduled_job(schedule_id: str, endpoint_id: str) -> None:
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

        # Create a running job record
        job_run = JobRun(
            id=run_id,
            schedule_id=sid,
            endpoint_id=eid,
            started_at=started_at,
            status=JobRunStatus.running,
        )
        await job_repo.create(job_run)
        await db.commit()

        try:
            # Load endpoint and connection
            endpoint = await ep_repo.get_by_id(eid)
            if endpoint is None:
                raise ValueError(f"Endpoint {eid} not found.")

            if not endpoint.is_active:
                raise ValueError(f"Endpoint {eid} is not active.")

            connection = await conn_repo.get_by_id(endpoint.connection_id)
            if connection is None or not connection.is_active:
                raise ValueError("Data source connection is unavailable.")

            # Scheduled snapshots have no request inputs, so validate and
            # resolve every configured static or dynamic default through the
            # same typed model used by live data requests.
            param_schema = endpoint.param_schema_json or {}
            # Keep explicit NULL defaults in the bind dictionary. Omitting a
            # None-valued entry makes Oracle see a missing bind variable rather
            # than a bind whose value is SQL NULL.
            params = resolve_scheduled_params(param_schema)

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
            retention_setting = await settings_repo.get_by_key(
                "snapshot_retention_count"
            )
            retention_count = (
                int(retention_setting.value) if retention_setting else 5
            )
            await snap_repo.delete_old(eid, keep=retention_count)

            # Mark job success
            finished_at = datetime.now(UTC)
            await job_repo.update(job_run, {
                "finished_at": finished_at,
                "status": JobRunStatus.success,
                "row_count": len(rows),
            })

            # Update schedule last_run_at
            schedule = await sched_repo.get_by_id(sid)
            if schedule:
                await sched_repo.update(schedule, {
                    "last_run_at": finished_at,
                })

            await db.commit()

            log.info(
                "scheduled_job_success",
                job_id=schedule_id,
                run_id=str(run_id),
                endpoint_id=endpoint_id,
                row_count=len(rows),
                duration_ms=duration_ms,
                success=True,
            )

        except (SqlExecutionError, ValueError, Exception) as exc:
            finished_at = datetime.now(UTC)
            error_detail = str(exc)[:5000]

            status = JobRunStatus.failed
            if "timeout" in error_detail.lower():
                status = JobRunStatus.timeout

            await job_repo.update(job_run, {
                "finished_at": finished_at,
                "status": status,
                "error_detail": error_detail,
            })

            # Update schedule last_run_at even on failure
            schedule = await sched_repo.get_by_id(sid)
            if schedule:
                await sched_repo.update(schedule, {
                    "last_run_at": finished_at,
                })

            await db.commit()

            log.error(
                "scheduled_job_failed",
                job_id=schedule_id,
                run_id=str(run_id),
                endpoint_id=endpoint_id,
                error=error_detail,
                success=False,
            )


async def restore_active_schedules() -> int:
    """Register all active database schedules in the in-memory scheduler."""
    restored = 0
    async with AsyncSessionLocal() as db:
        schedules = await ScheduleRepository(db).get_all(active_only=True)
        for schedule in schedules:
            try:
                add_schedule_job(
                    schedule_id=schedule.id,
                    endpoint_id=schedule.endpoint_id,
                    schedule_type=schedule.schedule_type,
                    cron_expression=schedule.cron_expression,
                    interval_seconds=schedule.interval_seconds,
                )
                restored += 1
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "scheduler_job_restore_failed",
                    schedule_id=str(schedule.id),
                    error=str(exc),
                )
    log.info("scheduler_jobs_restored", restored_count=restored)
    return restored


async def start_scheduler() -> None:
    """Initialize and start the APScheduler instance."""
    global _scheduler  # noqa: PLW0603

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # noqa: PLC0415

        scheduler = AsyncIOScheduler(
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
        log.error("scheduler_start_failed", error=str(exc))


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
) -> None:
    """Register a job in APScheduler."""
    if _scheduler is None:
        log.warning("scheduler_not_running", action="add_job")
        return

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
    elif schedule_type == "interval" and interval_seconds:
        kwargs["trigger"] = "interval"
        kwargs["seconds"] = interval_seconds
    else:
        log.warning("invalid_schedule_config", schedule_id=str(schedule_id))
        return

    scheduler.add_job(**kwargs)
    log.info(
        "scheduler_job_added",
        job_id=job_id,
        schedule_type=schedule_type,
    )


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
