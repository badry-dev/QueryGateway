"""JobRun model — immutable execution audit record for each scheduler invocation."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class JobRunStatus(StrEnum):
    running = "running"
    success = "success"
    failed = "failed"
    timeout = "timeout"


class JobRun(UUIDPrimaryKeyMixin, Base):
    """Immutable log of a single scheduler execution.

    Records are append-only; never updated after initial insert.
    finished_at, status, row_count, and error_detail are updated
    when the job completes.
    """

    __tablename__ = "job_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schedules.id", ondelete="SET NULL"), nullable=True
    )
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("endpoints.id", ondelete="RESTRICT"), nullable=False
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[JobRunStatus] = mapped_column(
        SAEnum(JobRunStatus, name="job_run_status"),
        nullable=False,
        default=JobRunStatus.running,
    )
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Truncated error detail; full stack trace goes to structured log.
    error_detail: Mapped[str | None] = mapped_column(String(5000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
