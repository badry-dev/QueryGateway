"""JobRun repository — raw DB access for job execution records."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select

from app.models.job_run import JobRun
from app.repositories.base import BaseCrudRepository


class JobRunRepository(BaseCrudRepository[JobRun]):
    """Data-access layer for job run audit records.

    Inherits ``get_by_id`` / ``create`` / ``update`` from
    ``BaseCrudRepository``. Only ``get_all`` is custom because it filters
    by ``schedule_id`` / ``endpoint_id`` rather than the base
    ``active_only`` flag.
    """

    model = JobRun

    async def get_by_schedule_and_scheduled_for(
        self, schedule_id: uuid.UUID, scheduled_for: datetime
    ) -> JobRun | None:
        result = await self._db.execute(
            select(JobRun).where(
                JobRun.schedule_id == schedule_id,
                JobRun.scheduled_for == scheduled_for,
            )
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        *,
        schedule_id: uuid.UUID | None = None,
        endpoint_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> Sequence[JobRun]:
        stmt = select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
        if schedule_id is not None:
            stmt = stmt.where(JobRun.schedule_id == schedule_id)
        if endpoint_id is not None:
            stmt = stmt.where(JobRun.endpoint_id == endpoint_id)
        result = await self._db.execute(stmt)
        return result.scalars().all()
