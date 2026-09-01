"""Typed request filtering for persisted snapshot rows."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
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
    param_type: str
    coercion_key: str
    value_model: type[BaseModel]

    def coerce_value(self, value: object) -> Any:
        """Coerce one scheduled or cached value using the parameter's declared type."""
        return self.value_model.model_validate({"value": value}).model_dump()["value"]


def _coercion_descriptor(descriptor: dict[str, object]) -> dict[str, object]:
    """Return only descriptor fields that affect validation of a supplied value."""
    coercion_descriptor: dict[str, object] = {
        "type": descriptor.get("type", "string"),
        "required": True,
    }
    if "max_length" in descriptor:
        coercion_descriptor["max_length"] = descriptor["max_length"]
    return coercion_descriptor


@lru_cache(maxsize=256)
def _cached_value_model(coercion_key: str) -> type[BaseModel]:
    """Build each distinct snapshot value model once per process."""
    descriptor = json.loads(coercion_key)
    return build_param_model({"value": descriptor}, enforce_required=True)


def compile_snapshot_filters(
    param_schema: dict[str, object],
) -> tuple[CompiledSnapshotFilter, ...]:
    """Compile persisted filter mappings once for one snapshot request."""
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
        coercion_key = json.dumps(
            _coercion_descriptor(descriptor),
            sort_keys=True,
            separators=(",", ":"),
        )
        compiled.append(
            CompiledSnapshotFilter(
                parameter=name,
                column=column,
                operator=operator,
                null_means_all=mapping.get("null_means_all") is True,
                param_type=str(descriptor.get("type", "string")),
                coercion_key=coercion_key,
                value_model=_cached_value_model(coercion_key),
            )
        )
    return tuple(compiled)


def _coerce_cached_row_value(item: CompiledSnapshotFilter, value: object) -> Any:
    """Normalize Oracle DATE/TIMESTAMP strings before typed comparison."""
    if item.param_type == "date" and isinstance(value, str):
        try:
            value = datetime.fromisoformat(value).date()
        except ValueError:
            # The shared date coercer still accepts the documented DD-MM-YYYY form.
            pass
    return item.coerce_value(value)


def snapshot_covers_request(
    *,
    filters: tuple[CompiledSnapshotFilter, ...],
    request_params: Mapping[str, object],
    resolved_params: Mapping[str, object],
) -> bool:
    """Return whether one snapshot job run contains the requested selection."""
    for item in filters:
        requested = request_params.get(item.parameter)
        if requested is None:
            # An omitted optional request is the same SQL NULL input used by a
            # scheduled run. A fixed-value run is only a subset regardless of
            # whether that query interprets NULL as all values or as a literal.
            if item.parameter not in resolved_params or resolved_params[item.parameter] is not None:
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
    filters: tuple[CompiledSnapshotFilter, ...],
    request_params: dict[str, object],
) -> None:
    """Reject an inclusive lower bound that is later than its upper bound."""
    bounds: dict[str, dict[str, list[Any]]] = {}
    for item in filters:
        if item.operator not in {"gte", "lte"}:
            continue
        value = request_params.get(item.parameter)
        if value is not None:
            bounds.setdefault(item.column, {}).setdefault(item.operator, []).append(value)

    for column, values in bounds.items():
        lower_values = values.get("gte", [])
        upper_values = values.get("lte", [])
        try:
            lower = max(lower_values) if lower_values else None
            upper = min(upper_values) if upper_values else None
        except TypeError as exc:
            raise ValueError(
                f"Snapshot filter bounds have incompatible types for '{column}'."
            ) from exc
        if lower is not None and upper is not None:
            try:
                reversed_range = lower > upper
            except TypeError as exc:
                raise ValueError(
                    f"Snapshot filter bounds have incompatible types for '{column}'."
                ) from exc
            if reversed_range:
                raise ValueError(f"Snapshot filter lower bound exceeds upper bound for '{column}'.")


def unavailable_snapshot_filter_columns(
    *,
    rows: list[dict[str, object]],
    filters: tuple[CompiledSnapshotFilter, ...],
) -> list[str]:
    """Return configured output columns absent from a non-empty snapshot."""
    if not rows:
        return []
    # TODO: Resolve configured filter columns against snapshot keys case-insensitively before both
    # availability validation and row filtering, while rejecting ambiguous keys that differ only
    # by case.
    available = {column for row in rows for column in row}
    return sorted({item.column for item in filters} - available)


def filter_snapshot_rows(
    *,
    rows: list[dict[str, object]],
    filters: tuple[CompiledSnapshotFilter, ...],
    request_params: dict[str, object],
) -> list[dict[str, object]]:
    """Apply explicitly configured, typed comparisons to cached rows."""
    filtered: list[dict[str, object]] = []
    for row in rows:
        matches = True
        coerced_values: dict[tuple[str, str], Any] = {}
        for item in filters:
            requested = request_params.get(item.parameter)
            if requested is None:
                continue
            if item.column not in row:
                matches = False
                break
            try:
                cache_key = (item.column, item.coercion_key)
                if cache_key not in coerced_values:
                    coerced_values[cache_key] = _coerce_cached_row_value(item, row[item.column])
                row_value = coerced_values[cache_key]
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


def validate_snapshot_rows_match_resolved_parameters(
    *,
    rows: list[dict[str, object]],
    filters: tuple[CompiledSnapshotFilter, ...],
    resolved_params: Mapping[str, object],
) -> None:
    """Reject non-empty snapshot results that contradict their resolved schedule bounds."""
    if not rows:
        return

    missing_columns = unavailable_snapshot_filter_columns(rows=rows, filters=filters)
    if missing_columns:
        raise ValueError(
            "Snapshot integrity validation failed: configured filter columns are absent from "
            f"the cached output: {', '.join(missing_columns)}."
        )

    normalized_params = dict(resolved_params)
    for item in filters:
        if item.parameter not in resolved_params or resolved_params[item.parameter] is None:
            continue
        try:
            normalized_params[item.parameter] = item.coerce_value(resolved_params[item.parameter])
        except (ValidationError, ValueError, TypeError) as exc:
            raise ValueError(
                "Snapshot integrity validation failed: the schedule's resolved parameter "
                f":{item.parameter} cannot be coerced to {item.param_type}."
            ) from exc

    matching_rows = filter_snapshot_rows(
        rows=rows,
        filters=filters,
        request_params=normalized_params,
    )
    invalid_row_count = len(rows) - len(matching_rows)
    if invalid_row_count:
        columns = sorted({item.column for item in filters})
        raise ValueError(
            "Snapshot integrity validation failed: "
            f"{invalid_row_count} of {len(rows)} cached rows do not match the schedule's "
            f"resolved filter parameters for columns: {', '.join(columns)}."
        )
