"""Schedule management admin API.

Admin API — all routes under /api/v1/admin/schedules.

Routes:
    GET    /                       — List all schedules
    POST   /                       — Create a schedule
    POST   /preview                — Preview logical runs and resolved bindings
    GET    /{id}                   — Get a single schedule
    PUT    /{id}                   — Update a schedule
    DELETE /{id}                   — Delete a schedule
    POST   /{id}/run               — Run now, optionally for a logical date
    POST   /{id}/pause             — Pause a schedule
    POST   /{id}/resume            — Resume a schedule
    GET    /jobs/                   — List job runs
    GET    /jobs/{id}               — Get a single job run
    GET    /snapshots/{endpoint_id} — List snapshots for an endpoint
    GET    /snapshots/detail/{id}   — Get a single snapshot with data
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import get_current_admin
from app.dependencies import get_db
from app.repositories.endpoint import EndpointRepository
from app.repositories.job_run import JobRunRepository
from app.repositories.schedule import ScheduleRepository
from app.repositories.snapshot import SnapshotRepository
from app.schemas.schedule import (
    JobRunResponse,
    ScheduleCreate,
    SchedulePreviewRequest,
    SchedulePreviewResponse,
    ScheduleResponse,
    ScheduleRunRequest,
    ScheduleUpdate,
    SnapshotDetailResponse,
    SnapshotResponse,
)
from app.services.schedule import ScheduleService
from app.services.schedule_bindings import ScheduleBindingError
from app.services.scheduler import remove_schedule_job

log = structlog.get_logger()

router = APIRouter(
    prefix="/api/v1/admin/schedules",
    tags=["schedules"],
    dependencies=[Depends(get_current_admin)],
)


def _service(db: AsyncSession = Depends(get_db)) -> ScheduleService:
    return ScheduleService(
        ScheduleRepository(db),
        EndpointRepository(db),
        JobRunRepository(db),
        SnapshotRepository(db),
    )


# ── Schedule CRUD ────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=list[ScheduleResponse],
    summary="List schedules",
)
async def list_schedules(
    active_only: bool = Query(False, description="Return only active schedules."),
    svc: ScheduleService = Depends(_service),
) -> list[ScheduleResponse]:
    return list(await svc.list_schedules(active_only=active_only))


@router.post(
    "/",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create schedule",
)
async def create_schedule(
    payload: ScheduleCreate,
    db: AsyncSession = Depends(get_db),
    svc: ScheduleService = Depends(_service),
) -> ScheduleResponse:
    try:
        result = await svc.create_schedule(payload)
    except ScheduleBindingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    return result


@router.post(
    "/preview",
    response_model=SchedulePreviewResponse,
    summary="Preview resolved schedule runs",
)
async def preview_schedule(
    payload: SchedulePreviewRequest,
    svc: ScheduleService = Depends(_service),
) -> SchedulePreviewResponse:
    try:
        return await svc.preview_schedule(payload)
    except ScheduleBindingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Get schedule",
)
async def get_schedule(
    schedule_id: uuid.UUID,
    svc: ScheduleService = Depends(_service),
) -> ScheduleResponse:
    result = await svc.get_schedule(schedule_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found.")
    return result


@router.put(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Update schedule",
)
async def update_schedule(
    schedule_id: uuid.UUID,
    payload: ScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    svc: ScheduleService = Depends(_service),
) -> ScheduleResponse:
    try:
        result = await svc.update_schedule(schedule_id, payload)
    except ScheduleBindingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found.")
    await db.commit()
    return result


@router.delete(
    "/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete schedule",
)
async def delete_schedule(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    svc: ScheduleService = Depends(_service),
) -> None:
    deleted = await svc.delete_schedule(schedule_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found.")
    await db.commit()
    remove_schedule_job(schedule_id)


# ── Control actions ──────────────────────────────────────────────────────────


@router.post(
    "/{schedule_id}/run",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run schedule now",
    description="Trigger immediate execution of the scheduled job.",
)
async def run_now(
    schedule_id: uuid.UUID,
    payload: ScheduleRunRequest | None = None,
    svc: ScheduleService = Depends(_service),
) -> dict[str, str]:
    try:
        await svc.run_now(schedule_id, payload)
    except ScheduleBindingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"status": "executed"}


@router.post(
    "/{schedule_id}/pause",
    response_model=ScheduleResponse,
    summary="Pause schedule",
)
async def pause_schedule(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    svc: ScheduleService = Depends(_service),
) -> ScheduleResponse:
    result = await svc.pause(schedule_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found.")
    await db.commit()
    return result


@router.post(
    "/{schedule_id}/resume",
    response_model=ScheduleResponse,
    summary="Resume schedule",
)
async def resume_schedule(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    svc: ScheduleService = Depends(_service),
) -> ScheduleResponse:
    result = await svc.resume(schedule_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found.")
    await db.commit()
    return result


# ── Job run queries ──────────────────────────────────────────────────────────


@router.get(
    "/jobs/",
    response_model=list[JobRunResponse],
    summary="List job runs",
)
async def list_job_runs(
    schedule_id: uuid.UUID | None = Query(None),
    endpoint_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    svc: ScheduleService = Depends(_service),
) -> list[JobRunResponse]:
    return list(
        await svc.list_job_runs(
            schedule_id=schedule_id,
            endpoint_id=endpoint_id,
            limit=limit,
        )
    )


@router.get(
    "/jobs/{job_run_id}",
    response_model=JobRunResponse,
    summary="Get job run",
)
async def get_job_run(
    job_run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JobRunResponse:
    repo = JobRunRepository(db)
    obj = await repo.get_by_id(job_run_id)
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job run not found.")
    return JobRunResponse(
        id=obj.id,
        schedule_id=obj.schedule_id,
        endpoint_id=obj.endpoint_id,
        started_at=obj.started_at,
        finished_at=obj.finished_at,
        status=obj.status,
        row_count=obj.row_count,
        error_detail=obj.error_detail,
        scheduled_for=obj.scheduled_for,
        logical_date=obj.logical_date,
        window_start=obj.window_start,
        window_end=obj.window_end,
        resolved_parameters=obj.resolved_params_json,
        trigger_source=obj.trigger_source,
        binding_hash=obj.binding_hash,
        created_at=obj.created_at,
    )


# ── Snapshot queries ─────────────────────────────────────────────────────────


@router.get(
    "/snapshots/{endpoint_id}",
    response_model=list[SnapshotResponse],
    summary="List snapshots for endpoint",
)
async def list_snapshots(
    endpoint_id: uuid.UUID,
    limit: int = Query(10, ge=1, le=50),
    svc: ScheduleService = Depends(_service),
) -> list[SnapshotResponse]:
    return list(await svc.list_snapshots(endpoint_id, limit=limit))


@router.get(
    "/snapshots/detail/{snapshot_id}",
    response_model=SnapshotDetailResponse,
    summary="Get snapshot with data",
)
async def get_snapshot(
    snapshot_id: uuid.UUID,
    svc: ScheduleService = Depends(_service),
) -> SnapshotDetailResponse:
    result = await svc.get_snapshot(snapshot_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found.")
    return result
