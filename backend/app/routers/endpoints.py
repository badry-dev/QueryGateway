"""Endpoint management admin API.

Admin API — all routes under /api/v1/admin/endpoints.

Routes:
    GET    /                — List all endpoints
    POST   /                — Create an endpoint
    GET    /{id}            — Get a single endpoint
    PUT    /{id}            — Update an endpoint
    DELETE /{id}            — Delete an endpoint
    POST   /preview         — Preview SQL execution
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import get_current_admin
from app.dependencies import get_db
from app.repositories.connection import ConnectionRepository
from app.repositories.endpoint import EndpointRepository
from app.repositories.schedule import ScheduleRepository
from app.schemas.endpoint import (
    EndpointCreate,
    EndpointResponse,
    EndpointUpdate,
    PublicEndpointError,
    SnapshotConfigurationError,
    SqlPreviewRequest,
    SqlPreviewResponse,
)
from app.services.endpoint import EndpointService
from app.services.schedule_bindings import ScheduleBindingError
from app.services.scheduler import remove_schedule_job

log = structlog.get_logger()

router = APIRouter(
    prefix="/api/v1/admin/endpoints",
    tags=["endpoints"],
    dependencies=[Depends(get_current_admin)],
)


def _service(db: AsyncSession = Depends(get_db)) -> EndpointService:
    return EndpointService(
        EndpointRepository(db),
        ConnectionRepository(db),
        ScheduleRepository(db),
    )


@router.get(
    "/",
    response_model=list[EndpointResponse],
    summary="List endpoints",
)
async def list_endpoints(
    active_only: bool = Query(False, description="Return only active endpoints."),
    svc: EndpointService = Depends(_service),
) -> list[EndpointResponse]:
    return list(await svc.list_endpoints(active_only=active_only))


@router.post(
    "/",
    response_model=EndpointResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create endpoint",
)
async def create_endpoint(
    payload: EndpointCreate,
    db: AsyncSession = Depends(get_db),
    svc: EndpointService = Depends(_service),
) -> EndpointResponse:
    try:
        result = await svc.create_endpoint(payload)
    except (PublicEndpointError, SnapshotConfigurationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    return result


@router.get(
    "/{endpoint_id}",
    response_model=EndpointResponse,
    summary="Get endpoint",
)
async def get_endpoint(
    endpoint_id: uuid.UUID,
    svc: EndpointService = Depends(_service),
) -> EndpointResponse:
    result = await svc.get_endpoint(endpoint_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found.")
    return result


@router.put(
    "/{endpoint_id}",
    response_model=EndpointResponse,
    summary="Update endpoint",
)
async def update_endpoint(
    endpoint_id: uuid.UUID,
    payload: EndpointUpdate,
    db: AsyncSession = Depends(get_db),
    svc: EndpointService = Depends(_service),
) -> EndpointResponse:
    try:
        result = await svc.update_endpoint(endpoint_id, payload)
    except (PublicEndpointError, ScheduleBindingError, SnapshotConfigurationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found.")
    await db.commit()
    return result


@router.delete(
    "/{endpoint_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete endpoint",
)
async def delete_endpoint(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    svc: EndpointService = Depends(_service),
) -> None:
    schedule = await ScheduleRepository(db).get_by_endpoint_id(endpoint_id)
    schedule_id = schedule.id if schedule is not None else None
    deleted = await svc.delete_endpoint(endpoint_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found.")
    await db.commit()
    if schedule_id is not None:
        remove_schedule_job(schedule_id)


@router.post(
    "/preview",
    response_model=SqlPreviewResponse,
    summary="Preview SQL execution",
    description=(
        "Execute a parameterized SQL query against an Oracle connection "
        "and return sample results.  Useful during wizard authoring."
    ),
)
async def preview_sql(
    payload: SqlPreviewRequest,
    svc: EndpointService = Depends(_service),
) -> SqlPreviewResponse:
    try:
        return await svc.preview_sql(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
