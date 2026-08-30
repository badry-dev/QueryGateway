"""Schedule model — cron or interval-based snapshot refresh configuration."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ScheduleType(StrEnum):
    cron = "cron"
    interval = "interval"


class Schedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Scheduling configuration for a snapshot-strategy endpoint.

    Exactly one of cron_expression or interval_seconds must be set,
    consistent with the schedule_type value (enforced by service layer).
    """

    __tablename__ = "schedules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False
    )
    schedule_type: Mapped[ScheduleType] = mapped_column(
        SAEnum(ScheduleType, name="schedule_type"),
        nullable=False,
    )
    # Used when schedule_type == 'cron'. Standard 5-field cron expression.
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Used when schedule_type == 'interval'. Positive integer seconds.
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    parameter_bindings_json: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    window_config_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default=text("true")
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
