"""Typed request filtering for persisted snapshot rows."""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.sql.param_models import build_param_model

SnapshotFilterOperator = Literal["eq", "gte", "lte"]


@dataclass(frozen=True)
class CompiledSnapshotFilter:
    """One validated request parameter to persisted-row comparison."""

    parameter: str
    column: str
    operator: SnapshotFilterOperator
    null_means_all: bool
    value_model: type[BaseModel]

    def coerce_value(self, value: object) -> Any:
        return self.value_model.model_validate({self.parameter: value}).model_dump()[self.parameter]


def _compile_filters(param_schema: dict[str, object]) -> list[CompiledSnapshotFilter]:
    compiled: list[CompiledSnapshotFilter] = []
    for name, descriptor in param_schema.items():
        if not isinstance(descriptor, dict):
            continue
        mapping = descriptor.get("snapshot_filter")
        if not isinstance(mapping, dict):
            continue
        column = mapping.get("column")
        operator = mapping.get("operator")
        if not isinstance(column, str) or operator not in {"eq", "gte", "lte"}:
            continue
        compiled.append(
            CompiledSnapshotFilter(
                parameter=name,
                column=column,
                operator=operator,
                null_means_all=mapping.get("null_means_all") is True,
                value_model=build_param_model({name: descriptor}, enforce_required=True),
            )
        )
    return compiled


def snapshot_covers_request(
    *,
    param_schema: dict[str, object],
    request_params: dict[str, object],
    resolved_params: dict[str, object],
) -> bool:
    """Return whether one snapshot job run contains the requested selection."""
    for item in _compile_filters(param_schema):
        requested = request_params.get(item.parameter)
        if requested is None:
            # When SQL NULL explicitly means "all values", an omitted public
            # filter also asks for all values. A fixed-value schedule run is
            # only a subset and cannot satisfy that request.
            if item.null_means_all and (
                item.parameter not in resolved_params or resolved_params[item.parameter] is not None
            ):
                return False
            continue
        if item.parameter not in resolved_params:
            return False
        resolved = resolved_params[item.parameter]
        if resolved is None:
            if item.operator == "eq" and item.null_means_all:
                continue
            return False
        try:
            coverage_value = item.coerce_value(resolved)
        except ValidationError, ValueError, TypeError:
            return False
        if item.operator == "eq" and coverage_value != requested:
            return False
        # A scheduled lower bound must start on or before the requested lower bound.
        if item.operator == "gte" and coverage_value > requested:
            return False
        # A scheduled upper bound must end on or after the requested upper bound.
        if item.operator == "lte" and coverage_value < requested:
            return False
    return True


def validate_snapshot_parameter_ranges(
    *,
    param_schema: dict[str, object],
    request_params: dict[str, object],
) -> None:
    """Reject an inclusive lower bound that is later than its upper bound."""
    bounds: dict[str, dict[str, Any]] = {}
    for item in _compile_filters(param_schema):
        if item.operator not in {"gte", "lte"}:
            continue
        value = request_params.get(item.parameter)
        if value is not None:
            bounds.setdefault(item.column, {})[item.operator] = value

    for column, values in bounds.items():
        lower = values.get("gte")
        upper = values.get("lte")
        if lower is not None and upper is not None and lower > upper:
            raise ValueError(f"Snapshot filter lower bound exceeds upper bound for '{column}'.")


def unavailable_snapshot_filter_columns(
    *,
    rows: list[dict[str, object]],
    param_schema: dict[str, object],
) -> list[str]:
    """Return configured output columns absent from a non-empty snapshot."""
    if not rows:
        return []
    available = {column for row in rows for column in row}
    return sorted({item.column for item in _compile_filters(param_schema)} - available)


def filter_snapshot_rows(
    *,
    rows: list[dict[str, object]],
    param_schema: dict[str, object],
    request_params: dict[str, object],
) -> list[dict[str, object]]:
    """Apply explicitly configured, typed comparisons to cached rows."""
    filters = _compile_filters(param_schema)
    filtered: list[dict[str, object]] = []
    for row in rows:
        matches = True
        for item in filters:
            requested = request_params.get(item.parameter)
            if requested is None:
                continue
            if item.column not in row:
                matches = False
                break
            try:
                row_value = item.coerce_value(row[item.column])
            except ValidationError, ValueError, TypeError:
                matches = False
                break
            if row_value is None:
                matches = False
                break
            if item.operator == "eq" and row_value != requested:
                matches = False
                break
            if item.operator == "gte" and row_value < requested:
                matches = False
                break
            if item.operator == "lte" and row_value > requested:
                matches = False
                break
        if matches:
            filtered.append(row)
    return filtered
