"""JobRun model — immutable execution audit record for each scheduler invocation."""

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
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
    __table_args__ = (
        UniqueConstraint(
            "schedule_id",
            "scheduled_for",
            name="uq_job_runs_schedule_scheduled_for",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schedules.id", ondelete="SET NULL"), nullable=True
    )
    endpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("endpoints.id", ondelete="SET NULL"), nullable=True
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[JobRunStatus] = mapped_column(
        SAEnum(JobRunStatus, name="job_run_status"),
        nullable=False,
        default=JobRunStatus.running,
    )
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Truncated error detail; full stack trace goes to structured log.
    error_detail: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    logical_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    resolved_params_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    trigger_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    binding_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
