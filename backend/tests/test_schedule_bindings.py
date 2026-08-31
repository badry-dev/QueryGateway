"""Behavioral tests for schedule-owned parameter bindings."""

from datetime import UTC, date, datetime

import pytest
from app.schemas.schedule import ScheduleParameterBinding, ScheduleWindow
from app.services.schedule_bindings import (
    ScheduleBindingError,
    preview_schedule_runs,
    resolve_schedule_parameters,
)

DATE_RANGE_SCHEMA = {
    "start_date": {"type": "date", "required": True},
    "end_date": {"type": "date", "required": True},
    "store_id": {
        "type": "string",
        "required": False,
        "default_is_null": True,
    },
}


def test_resolve_schedule_parameters_uses_logical_date_in_schedule_timezone() -> None:
    context = resolve_schedule_parameters(
        param_schema=DATE_RANGE_SCHEMA,
        parameter_bindings={
            "start_date": ScheduleParameterBinding(source="relative_date", offset_days=-7),
            "end_date": ScheduleParameterBinding(source="run_date"),
            "store_id": ScheduleParameterBinding(source="null"),
        },
        timezone_name="Asia/Riyadh",
        scheduled_for=datetime(2026, 8, 30, 21, 30, tzinfo=UTC),
    )

    assert context.logical_date == date(2026, 8, 31)
    assert context.parameters == {
        "start_date": date(2026, 8, 24),
        "end_date": date(2026, 8, 31),
        "store_id": None,
    }
    assert context.window_start is None
    assert context.window_end is None


@pytest.mark.parametrize(
    ("window", "scheduled_for", "expected_start", "expected_end"),
    [
        (
            ScheduleWindow(preset="previous_day"),
            datetime(2026, 8, 31, 3, tzinfo=UTC),
            date(2026, 8, 30),
            date(2026, 8, 30),
        ),
        (
            ScheduleWindow(preset="last_n_complete_days", days=7),
            datetime(2026, 8, 31, 3, tzinfo=UTC),
            date(2026, 8, 24),
            date(2026, 8, 30),
        ),
        (
            ScheduleWindow(preset="week_to_date"),
            datetime(2026, 9, 2, 3, tzinfo=UTC),
            date(2026, 8, 31),
            date(2026, 9, 2),
        ),
        (
            ScheduleWindow(preset="previous_week"),
            datetime(2026, 9, 2, 3, tzinfo=UTC),
            date(2026, 8, 24),
            date(2026, 8, 30),
        ),
        (
            ScheduleWindow(preset="month_to_date"),
            datetime(2024, 2, 29, 3, tzinfo=UTC),
            date(2024, 2, 1),
            date(2024, 2, 29),
        ),
        (
            ScheduleWindow(preset="previous_month"),
            datetime(2024, 3, 1, 3, tzinfo=UTC),
            date(2024, 2, 1),
            date(2024, 2, 29),
        ),
    ],
)
def test_resolve_schedule_parameters_supports_calendar_windows(
    window: ScheduleWindow,
    scheduled_for: datetime,
    expected_start: date,
    expected_end: date,
) -> None:
    context = resolve_schedule_parameters(
        param_schema={
            "start_date": {"type": "date", "required": True},
            "end_date": {"type": "date", "required": True},
        },
        parameter_bindings={
            "start_date": ScheduleParameterBinding(source="window_start"),
            "end_date": ScheduleParameterBinding(source="window_end"),
        },
        window=window,
        timezone_name="UTC",
        scheduled_for=scheduled_for,
    )

    assert context.parameters == {
        "start_date": expected_start,
        "end_date": expected_end,
    }
    assert context.window_start == expected_start
    assert context.window_end == expected_end


def test_resolve_schedule_parameters_coerces_typed_literals() -> None:
    context = resolve_schedule_parameters(
        param_schema={
            "limit": {"type": "integer", "required": True},
            "enabled": {"type": "boolean", "required": True},
            "as_of": {"type": "date", "required": True},
        },
        parameter_bindings={
            "limit": ScheduleParameterBinding(source="literal", value="25"),
            "enabled": ScheduleParameterBinding(source="literal", value="yes"),
            "as_of": ScheduleParameterBinding(source="literal", value="31-08-2026"),
        },
        timezone_name="UTC",
        scheduled_for=datetime(2026, 8, 31, tzinfo=UTC),
    )

    assert context.parameters == {
        "limit": 25,
        "enabled": True,
        "as_of": date(2026, 8, 31),
    }


def test_schedule_can_override_optional_endpoint_default_with_sql_null() -> None:
    context = resolve_schedule_parameters(
        param_schema={
            "store_id": {
                "type": "string",
                "required": False,
                "default": "ALL",
            }
        },
        parameter_bindings={
            "store_id": ScheduleParameterBinding(source="null"),
        },
        timezone_name="UTC",
        scheduled_for=datetime(2026, 8, 31, tzinfo=UTC),
    )

    assert context.parameters == {"store_id": None}


@pytest.mark.parametrize(
    ("bindings", "message"),
    [
        ({}, "Missing schedule bindings: :end_date, :start_date, :store_id"),
        (
            {
                "start_date": ScheduleParameterBinding(source="run_date"),
                "end_date": ScheduleParameterBinding(source="run_date"),
                "store_id": ScheduleParameterBinding(source="null"),
                "unknown": ScheduleParameterBinding(source="literal", value="x"),
            },
            "Unknown schedule bindings: :unknown",
        ),
    ],
)
def test_resolve_schedule_parameters_requires_exact_bind_coverage(
    bindings: dict[str, ScheduleParameterBinding], message: str
) -> None:
    with pytest.raises(ScheduleBindingError, match=message):
        resolve_schedule_parameters(
            param_schema=DATE_RANGE_SCHEMA,
            parameter_bindings=bindings,
            timezone_name="UTC",
            scheduled_for=datetime(2026, 8, 31, tzinfo=UTC),
        )


def test_resolve_schedule_parameters_rejects_null_for_required_parameter() -> None:
    with pytest.raises(ScheduleBindingError, match=":start_date cannot use SQL NULL"):
        resolve_schedule_parameters(
            param_schema=DATE_RANGE_SCHEMA,
            parameter_bindings={
                "start_date": ScheduleParameterBinding(source="null"),
                "end_date": ScheduleParameterBinding(source="run_date"),
                "store_id": ScheduleParameterBinding(source="null"),
            },
            timezone_name="UTC",
            scheduled_for=datetime(2026, 8, 31, tzinfo=UTC),
        )


def test_resolve_schedule_parameters_requires_window_for_window_sources() -> None:
    with pytest.raises(ScheduleBindingError, match="Window configuration is required"):
        resolve_schedule_parameters(
            param_schema=DATE_RANGE_SCHEMA,
            parameter_bindings={
                "start_date": ScheduleParameterBinding(source="window_start"),
                "end_date": ScheduleParameterBinding(source="window_end"),
                "store_id": ScheduleParameterBinding(source="null"),
            },
            timezone_name="UTC",
            scheduled_for=datetime(2026, 8, 31, tzinfo=UTC),
        )


def test_preview_schedule_runs_returns_next_three_logical_contexts() -> None:
    previews = preview_schedule_runs(
        schedule_type="cron",
        cron_expression="0 6 * * *",
        interval_seconds=None,
        timezone_name="Asia/Riyadh",
        param_schema={"run_date": {"type": "date", "required": True}},
        parameter_bindings={
            "run_date": ScheduleParameterBinding(source="run_date"),
        },
        window=None,
        from_time=datetime(2026, 8, 30, 20, tzinfo=UTC),
        count=3,
    )

    assert [preview.scheduled_for.isoformat() for preview in previews] == [
        "2026-08-31T06:00:00+03:00",
        "2026-09-01T06:00:00+03:00",
        "2026-09-02T06:00:00+03:00",
    ]
    assert [preview.logical_date for preview in previews] == [
        date(2026, 8, 31),
        date(2026, 9, 1),
        date(2026, 9, 2),
    ]
    assert [preview.resolved_parameters["run_date"] for preview in previews] == [
        date(2026, 8, 31),
        date(2026, 9, 1),
        date(2026, 9, 2),
    ]


def test_preview_schedule_runs_preserves_local_cron_time_across_dst() -> None:
    previews = preview_schedule_runs(
        schedule_type="cron",
        cron_expression="0 1 * * *",
        interval_seconds=None,
        timezone_name="America/New_York",
        param_schema={"run_date": {"type": "date", "required": True}},
        parameter_bindings={
            "run_date": ScheduleParameterBinding(source="run_date"),
        },
        window=None,
        from_time=datetime(2026, 3, 7, tzinfo=UTC),
        count=3,
    )

    assert [preview.scheduled_for.isoformat() for preview in previews] == [
        "2026-03-07T01:00:00-05:00",
        "2026-03-08T01:00:00-05:00",
        "2026-03-09T01:00:00-04:00",
    ]
