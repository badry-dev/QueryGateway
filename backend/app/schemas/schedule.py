"""Pydantic schemas for schedule, job run, and snapshot resources."""

import uuid
from datetime import date, datetime
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

# ── Schedule schemas ─────────────────────────────────────────────────────────


BindingSource = Literal[
    "literal",
    "null",
    "run_date",
    "relative_date",
    "window_start",
    "window_end",
]
WindowPreset = Literal[
    "previous_day",
    "last_n_complete_days",
    "week_to_date",
    "previous_week",
    "month_to_date",
    "previous_month",
]


class ScheduleParameterBinding(BaseModel):
    """Declarative source for one SQL bind during scheduled execution."""

    source: BindingSource
    value: str | int | float | bool | None = None
    offset_days: int | None = Field(None, ge=-36500, le=36500)

    @model_validator(mode="after")
    def validate_source_options(self) -> Self:
        if self.source == "literal" and self.value is None:
            raise ValueError("Literal bindings require a value; use source='null' for SQL NULL.")
        if self.source == "relative_date" and self.offset_days is None:
            raise ValueError("Relative-date bindings require offset_days.")
        if self.source != "literal" and self.value is not None:
            raise ValueError("A value is supported only for literal bindings.")
        if self.source != "relative_date" and self.offset_days is not None:
            raise ValueError("offset_days is supported only for relative-date bindings.")
        return self


class ScheduleWindow(BaseModel):
    """Reusable inclusive date window resolved from a schedule's logical date."""

    preset: WindowPreset
    days: int | None = Field(None, ge=1, le=3660)

    @model_validator(mode="after")
    def validate_days(self) -> Self:
        if self.preset == "last_n_complete_days" and self.days is None:
            raise ValueError("last_n_complete_days requires days.")
        if self.preset != "last_n_complete_days" and self.days is not None:
            raise ValueError("days is supported only for last_n_complete_days.")
        return self


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown IANA timezone: {value}") from exc
    return value


def _validate_cron_expression(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    parts = normalized.split()
    if len(parts) != 5:
        raise ValueError("Cron expression must have exactly 5 fields.")

    from apscheduler.triggers.cron import CronTrigger  # noqa: PLC0415

    try:
        CronTrigger.from_crontab(normalized)
    except ValueError as exc:
        raise ValueError(f"Invalid cron expression: {exc}") from exc
    return normalized


class ScheduleCreate(BaseModel):
    endpoint_id: uuid.UUID
    schedule_type: str = Field(..., pattern=r"^(cron|interval)$")
    cron_expression: str | None = None
    interval_seconds: int | None = Field(None, ge=10)
    timezone: str = "UTC"
    parameter_bindings: dict[str, ScheduleParameterBinding] = Field(default_factory=dict)
    window: ScheduleWindow | None = None
    is_active: bool = True

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return _validate_timezone(value)

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, v: str | None) -> str | None:
        """Validate cron syntax and ranges with APScheduler's parser."""
        return _validate_cron_expression(v)

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
    timezone: str | None = None
    parameter_bindings: dict[str, ScheduleParameterBinding] | None = None
    window: ScheduleWindow | None = None
    is_active: bool | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        return _validate_timezone(value) if value is not None else None

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, value: str | None) -> str | None:
        return _validate_cron_expression(value)


class ScheduleResponse(BaseModel):
    id: uuid.UUID
    endpoint_id: uuid.UUID
    schedule_type: str
    cron_expression: str | None
    interval_seconds: int | None
    timezone: str
    parameter_bindings: dict[str, ScheduleParameterBinding]
    window: ScheduleWindow | None
    is_active: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SchedulePreviewRequest(BaseModel):
    endpoint_id: uuid.UUID
    schedule_type: str = Field(..., pattern=r"^(cron|interval)$")
    cron_expression: str | None = None
    interval_seconds: int | None = Field(None, ge=10)
    timezone: str = "UTC"
    parameter_bindings: dict[str, ScheduleParameterBinding] = Field(default_factory=dict)
    window: ScheduleWindow | None = None
    count: int = Field(3, ge=1, le=10)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return _validate_timezone(value)

    @field_validator("cron_expression")
    @classmethod
    def validate_cron(cls, value: str | None) -> str | None:
        return _validate_cron_expression(value)

    def model_post_init(self, __context: object) -> None:
        if self.schedule_type == "cron" and not self.cron_expression:
            raise ValueError("cron_expression is required when schedule_type is 'cron'.")
        if self.schedule_type == "interval" and not self.interval_seconds:
            raise ValueError("interval_seconds is required when schedule_type is 'interval'.")


class ScheduleRunPreview(BaseModel):
    scheduled_for: datetime
    logical_date: date
    window_start: date | None
    window_end: date | None
    resolved_parameters: dict[str, object]


class SchedulePreviewResponse(BaseModel):
    runs: list[ScheduleRunPreview]


class ScheduleRunRequest(BaseModel):
    logical_date: date | None = None


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
    scheduled_for: datetime | None = None
    logical_date: date | None = None
    window_start: date | None = None
    window_end: date | None = None
    resolved_parameters: dict[str, object] | None = None
    trigger_source: str | None = None
    binding_hash: str | None = None
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
