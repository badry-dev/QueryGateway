"""Resolve declarative schedule bindings against a deterministic logical date."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.schemas.endpoint import ParamDescriptor
from app.schemas.schedule import (
    ScheduleParameterBinding,
    ScheduleRunPreview,
    ScheduleWindow,
)
from app.sql.param_models import build_param_model


class ScheduleBindingError(ValueError):
    """Raised when a schedule cannot resolve every endpoint SQL bind safely."""


@dataclass(frozen=True)
class ResolvedScheduleContext:
    parameters: dict[str, Any]
    logical_date: date
    window_start: date | None
    window_end: date | None


def _normalise_bindings(
    bindings: dict[str, ScheduleParameterBinding] | dict[str, object],
) -> dict[str, ScheduleParameterBinding]:
    return {
        name: (
            binding
            if isinstance(binding, ScheduleParameterBinding)
            else ScheduleParameterBinding.model_validate(binding)
        )
        for name, binding in bindings.items()
    }


def _normalise_param_schema(param_schema: dict[str, Any]) -> dict[str, ParamDescriptor]:
    try:
        return {
            name: (
                descriptor
                if isinstance(descriptor, ParamDescriptor)
                else ParamDescriptor.model_validate(descriptor)
            )
            for name, descriptor in param_schema.items()
        }
    except ValidationError as exc:
        raise ScheduleBindingError("Endpoint has an invalid parameter schema.") from exc


def _resolve_window(logical_date: date, window: ScheduleWindow) -> tuple[date, date]:
    if window.preset == "previous_day":
        day = logical_date - timedelta(days=1)
        return day, day
    if window.preset == "last_n_complete_days":
        if window.days is None:  # Defensive; schema validation normally catches this.
            raise ScheduleBindingError("last_n_complete_days requires days.")
        end = logical_date - timedelta(days=1)
        return end - timedelta(days=window.days - 1), end
    if window.preset == "week_to_date":
        return logical_date - timedelta(days=logical_date.weekday()), logical_date
    if window.preset == "previous_week":
        current_week_start = logical_date - timedelta(days=logical_date.weekday())
        end = current_week_start - timedelta(days=1)
        return end - timedelta(days=6), end
    if window.preset == "month_to_date":
        return logical_date.replace(day=1), logical_date
    if window.preset == "previous_month":
        end = logical_date.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    raise ScheduleBindingError(f"Unsupported window preset: {window.preset}")


def resolve_schedule_parameters(
    *,
    param_schema: dict[str, Any],
    parameter_bindings: dict[str, ScheduleParameterBinding] | dict[str, object],
    timezone_name: str,
    scheduled_for: datetime,
    window: ScheduleWindow | dict[str, object] | None = None,
) -> ResolvedScheduleContext:
    """Resolve and type-check every SQL bind for one logical schedule run."""
    if scheduled_for.tzinfo is None:
        raise ScheduleBindingError("scheduled_for must include a timezone.")

    descriptors = _normalise_param_schema(param_schema)
    bindings = _normalise_bindings(parameter_bindings)
    expected = set(descriptors)
    supplied = set(bindings)
    missing = sorted(expected - supplied)
    unknown = sorted(supplied - expected)
    if missing:
        names = ", ".join(f":{name}" for name in missing)
        raise ScheduleBindingError(f"Missing schedule bindings: {names}")
    if unknown:
        names = ", ".join(f":{name}" for name in unknown)
        raise ScheduleBindingError(f"Unknown schedule bindings: {names}")

    logical_date = scheduled_for.astimezone(ZoneInfo(timezone_name)).date()
    parsed_window = (
        window
        if isinstance(window, ScheduleWindow)
        else ScheduleWindow.model_validate(window)
        if window is not None
        else None
    )
    uses_window = any(
        binding.source in {"window_start", "window_end"} for binding in bindings.values()
    )
    if uses_window and parsed_window is None:
        raise ScheduleBindingError("Window configuration is required for window bindings.")

    window_start: date | None = None
    window_end: date | None = None
    if parsed_window is not None:
        window_start, window_end = _resolve_window(logical_date, parsed_window)

    raw_parameters: dict[str, object] = {}
    for name, binding in bindings.items():
        descriptor = descriptors[name]
        param_type = descriptor.type
        is_required = descriptor.required

        if binding.source == "null":
            if is_required:
                raise ScheduleBindingError(f":{name} cannot use SQL NULL because it is required.")
            raw_parameters[name] = None
            continue

        if (
            binding.source
            in {
                "run_date",
                "relative_date",
                "window_start",
                "window_end",
            }
            and param_type != "date"
        ):
            raise ScheduleBindingError(f":{name} must be a date parameter to use {binding.source}.")

        if binding.source == "literal":
            raw_parameters[name] = binding.value
        elif binding.source == "run_date":
            raw_parameters[name] = logical_date
        elif binding.source == "relative_date":
            raw_parameters[name] = logical_date + timedelta(days=binding.offset_days or 0)
        elif binding.source == "window_start":
            raw_parameters[name] = window_start
        elif binding.source == "window_end":
            raw_parameters[name] = window_end

    try:
        ParamModel = build_param_model(
            {name: descriptor.model_dump() for name, descriptor in descriptors.items()}
        )
        parameters = ParamModel.model_validate(raw_parameters).model_dump()
    except (ValidationError, ValueError) as exc:
        raise ScheduleBindingError(f"Invalid resolved schedule parameters: {exc}") from exc

    return ResolvedScheduleContext(
        parameters=parameters,
        logical_date=logical_date,
        window_start=window_start,
        window_end=window_end,
    )


def preview_schedule_runs(
    *,
    schedule_type: str,
    cron_expression: str | None,
    interval_seconds: int | None,
    timezone_name: str,
    param_schema: dict[str, Any],
    parameter_bindings: dict[str, ScheduleParameterBinding] | dict[str, object],
    window: ScheduleWindow | dict[str, object] | None,
    from_time: datetime | None = None,
    count: int = 3,
) -> list[ScheduleRunPreview]:
    """Return upcoming logical runs and their resolved parameters."""
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    zone = ZoneInfo(timezone_name)
    cursor = from_time or datetime.now(UTC)
    if cursor.tzinfo is None:
        raise ScheduleBindingError("from_time must include a timezone.")

    try:
        if schedule_type == "cron" and cron_expression:
            trigger = CronTrigger.from_crontab(cron_expression, timezone=zone)
        elif schedule_type == "interval" and interval_seconds:
            trigger = IntervalTrigger(
                seconds=interval_seconds,
                start_date=(cursor + timedelta(seconds=interval_seconds)).astimezone(zone),
                timezone=zone,
            )
        else:
            raise ScheduleBindingError("Invalid schedule timing configuration.")
    except ValueError as exc:
        raise ScheduleBindingError(f"Invalid schedule timing configuration: {exc}") from exc

    previews: list[ScheduleRunPreview] = []
    previous_fire_time: datetime | None = None
    for _ in range(count):
        next_fire_time = trigger.get_next_fire_time(previous_fire_time, cursor)
        if next_fire_time is None:
            break
        context = resolve_schedule_parameters(
            param_schema=param_schema,
            parameter_bindings=parameter_bindings,
            timezone_name=timezone_name,
            scheduled_for=next_fire_time,
            window=window,
        )
        previews.append(
            ScheduleRunPreview(
                scheduled_for=next_fire_time,
                logical_date=context.logical_date,
                window_start=context.window_start,
                window_end=context.window_end,
                resolved_parameters=context.parameters,
            )
        )
        previous_fire_time = next_fire_time
        cursor = next_fire_time
    return previews
