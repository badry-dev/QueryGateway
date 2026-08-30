"""Pydantic schemas for schedule, job run, and snapshot resources."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# ── Schedule schemas ─────────────────────────────────────────────────────────


class ScheduleCreate(BaseModel):
    endpoint_id: uuid.UUID
    schedule_type: str = Field(..., pattern=r"^(cron|interval)$")
    cron_expression: str | None = None
    interval_seconds: int | None = Field(None, ge=10)
    is_active: bool = True

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str | None, info: object) -> str | None:
        """Basic cron expression validation (5-field format)."""
        if v is None:
            return v
        parts = v.strip().split()
        if len(parts) != 5:
            raise ValueError("Cron expression must have exactly 5 fields.")
        return v.strip()

    @field_validator("interval_seconds")
    @classmethod
    def validate_interval(cls, v: int | None) -> int | None:
        if v is not None and v < 10:
            raise ValueError("Interval must be at least 10 seconds.")
        return v

    def model_post_init(self, __context: object) -> None:
        if self.schedule_type == "cron" and not self.cron_expression:
            raise ValueError("cron_expression is required when schedule_type is 'cron'.")
        if self.schedule_type == "interval" and not self.interval_seconds:
            raise ValueError("interval_seconds is required when schedule_type is 'interval'.")


class ScheduleUpdate(BaseModel):
    schedule_type: str | None = Field(None, pattern=r"^(cron|interval)$")
    cron_expression: str | None = None
    interval_seconds: int | None = Field(None, ge=10)
    is_active: bool | None = None


class ScheduleResponse(BaseModel):
    id: uuid.UUID
    endpoint_id: uuid.UUID
    schedule_type: str
    cron_expression: str | None
    interval_seconds: int | None
    is_active: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── JobRun schemas ───────────────────────────────────────────────────────────


class JobRunResponse(BaseModel):
    id: uuid.UUID
    schedule_id: uuid.UUID | None
    endpoint_id: uuid.UUID | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    row_count: int | None
    error_detail: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Snapshot schemas ─────────────────────────────────────────────────────────


class SnapshotResponse(BaseModel):
    id: uuid.UUID
    endpoint_id: uuid.UUID
    job_run_id: uuid.UUID | None
    row_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SnapshotDetailResponse(BaseModel):
    """Full snapshot including data payload."""

    id: uuid.UUID
    endpoint_id: uuid.UUID
    job_run_id: uuid.UUID | None
    data: list[dict[str, object]]
    row_count: int
    created_at: datetime

    model_config = {"from_attributes": True}
