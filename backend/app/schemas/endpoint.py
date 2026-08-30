"""Pydantic schemas for API endpoint management (Phase 4).

Public contract rules:
- ``sql_text`` must use named bind parameters (``:`param_name``).
- ``path`` must be a valid URL segment (no leading slash, no whitespace).
- ``param_schema_json`` maps parameter names to type/required/default descriptors.
- ``column_map_json`` maps source column names to output names (optional).
"""

import re
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.endpoint import DataStrategy

# Regex to find named bind parameters in Oracle SQL (:param_name).
_BIND_PARAM_RE = re.compile(r":([A-Za-z_]\w*)")

# Reject obvious string-interpolation patterns that bypass bind variables.
_UNSAFE_PATTERNS = [
    re.compile(r"'\s*\+"),  # ' +
    re.compile(r"\+\s*'"),  # + '
    re.compile(r"'\s*\|\|"),  # ' ||  (PL/SQL concat)
    re.compile(r"\|\|\s*'"),  # || '
    re.compile(r"\bf['\"]"),  # Python f-string (f' / f")
    re.compile(r"\{[^}]+\}"),  # Template interpolation {var}
    re.compile(r"\$\{"),  # ${var}
]

# Valid path segment: lowercase alphanumeric, hyphens, underscores, slashes.
_PATH_RE = re.compile(r"^[a-z0-9][a-z0-9\-_/]*$")

# Message shown when an endpoint has no dedicated auth method and has not opted
# into the platform-admin Bearer fallback. Anonymous data access is forbidden.
PUBLIC_OPT_IN_MESSAGE = (
    "Endpoint has no auth_method_id. Attach an endpoint auth method, or set "
    "allow_unauthenticated=true to use platform-admin Bearer authentication. "
    "Anonymous data access is not supported."
)


class PublicEndpointError(ValueError):
    """Raised when an endpoint has no configured authentication path."""


class SnapshotConfigurationError(ValueError):
    """Raised when a snapshot endpoint cannot execute without request inputs."""


def extract_bind_params(sql: str) -> list[str]:
    """Return deduplicated bind parameter names from SQL text."""
    # Exclude matches inside single-quoted string literals.
    cleaned = re.sub(r"'[^']*'", "", sql)
    return list(dict.fromkeys(_BIND_PARAM_RE.findall(cleaned)))


def validate_sql_safety(sql: str) -> list[str]:
    """Return a list of safety violation messages (empty if safe)."""
    errors: list[str] = []
    for pattern in _UNSAFE_PATTERNS:
        if pattern.search(sql):
            errors.append(
                f"SQL contains potentially unsafe interpolation pattern: {pattern.pattern}"
            )
    return errors


class ParamDescriptor(BaseModel):
    """Schema for a single bind parameter."""

    type: str = Field(
        "string",
        description="Parameter type: string, integer, float, date, boolean.",
        pattern=r"^(string|integer|float|date|boolean)$",
    )
    required: bool = True
    default: str | int | float | bool | None = None
    default_is_null: bool = Field(
        False,
        description=(
            "Use an explicit SQL NULL when this optional parameter is omitted. "
            "This is distinct from having no configured default."
        ),
    )
    default_expression: Literal["today", "yesterday"] | None = Field(
        None,
        description=(
            "Dynamic date default evaluated from the application server date "
            "when the query executes."
        ),
    )
    description: str | None = None
    max_length: int | None = Field(
        None,
        ge=1,
        description="Maximum allowed length for string parameters.",
    )

    @model_validator(mode="after")
    def optional_must_have_default(self) -> Self:
        configured_defaults = sum(
            (
                self.default is not None,
                self.default_is_null,
                self.default_expression is not None,
            )
        )
        if configured_defaults > 1:
            raise ValueError(
                "Declare only one of default, default_is_null, or default_expression."
            )
        if self.default_is_null and self.required:
            raise ValueError("A NULL default is supported only for optional parameters.")
        if self.default_expression is not None and self.type != "date":
            raise ValueError("default_expression is supported only for date parameters.")
        if configured_defaults:
            from app.sql.param_models import build_param_model  # noqa: PLC0415

            try:
                model = build_param_model({"value": self.model_dump()})
                model.model_validate({})
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid default for parameter type '{self.type}'."
                ) from exc
        return self


def missing_snapshot_defaults(
    param_schema: Mapping[str, object],
) -> list[str]:
    """Return snapshot bind names that cannot be resolved without a request."""
    missing: list[str] = []
    for name, raw_descriptor in param_schema.items():
        if isinstance(raw_descriptor, ParamDescriptor):
            descriptor = raw_descriptor
        elif isinstance(raw_descriptor, dict):
            descriptor = ParamDescriptor.model_validate(raw_descriptor)
        else:
            missing.append(name)
            continue

        if (
            descriptor.default is None
            and not descriptor.default_is_null
            and descriptor.default_expression is None
        ):
            missing.append(name)
    return sorted(missing)


def require_snapshot_defaults(
    data_strategy: DataStrategy,
    param_schema: Mapping[str, object],
) -> None:
    """Reject snapshot endpoints whose binds require caller-supplied values."""
    if data_strategy != DataStrategy.snapshot:
        return
    missing = missing_snapshot_defaults(param_schema)
    if missing:
        names = ", ".join(f":{name}" for name in missing)
        raise SnapshotConfigurationError(
            f"Snapshot endpoints require a default for every parameter. Missing: {names}."
        )


class EndpointCreate(BaseModel):
    """Payload for POST /api/v1/admin/endpoints."""

    name: str = Field(..., min_length=1, max_length=255, description="Unique display name.")
    description: str | None = Field(None, max_length=1000)
    path: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="URL path segment after /api/v1/data/ — must be unique.",
    )
    connection_id: uuid.UUID = Field(..., description="Oracle connection to use.")
    sql_text: str = Field(..., min_length=1, description="Parameterized SQL query.")
    param_schema: dict[str, ParamDescriptor] = Field(
        default_factory=dict,
        description="Bind parameter definitions.",
    )
    column_map: dict[str, str] = Field(
        default_factory=dict,
        description="Optional output column rename map: {source_col: output_col}.",
    )
    auth_method_id: uuid.UUID | None = Field(
        None, description="Auth method to enforce on this endpoint."
    )
    allow_unauthenticated: bool = Field(
        False,
        description=(
            "Legacy-named opt-in to platform-admin Bearer authentication when "
            "auth_method_id is omitted. It never permits anonymous access."
        ),
    )
    data_strategy: DataStrategy = DataStrategy.live
    is_active: bool = True

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        v = v.strip("/").lower()
        if not _PATH_RE.match(v):
            raise ValueError(
                "Path must contain only lowercase alphanumeric, hyphens, underscores, or slashes."
            )
        return v

    @model_validator(mode="after")
    def require_auth_or_explicit_fallback(self) -> Self:
        # Without a dedicated method, require explicit use of the platform
        # Bearer fallback. The legacy field name does not permit anonymity.
        if self.auth_method_id is None and not self.allow_unauthenticated:
            raise ValueError(PUBLIC_OPT_IN_MESSAGE)
        return self

    @field_validator("sql_text")
    @classmethod
    def validate_sql(cls, v: str) -> str:
        errors = validate_sql_safety(v)
        if errors:
            raise ValueError("; ".join(errors))
        return v

    @model_validator(mode="after")
    def bind_params_match_schema(self) -> Self:
        sql_params = set(extract_bind_params(self.sql_text))
        schema_params = set(self.param_schema.keys())
        undeclared = sql_params - schema_params
        unused = schema_params - sql_params
        if undeclared:
            raise ValueError(
                f"SQL references params not declared in schema: {sorted(undeclared)}"
            )
        if unused:
            raise ValueError(
                f"Schema declares params not referenced in SQL: {sorted(unused)}"
            )
        require_snapshot_defaults(self.data_strategy, self.param_schema)
        return self


class EndpointUpdate(BaseModel):
    """Payload for PUT /api/v1/admin/endpoints/{id}.

    All fields optional; omitted fields are left unchanged.
    """

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    path: str | None = Field(None, min_length=1, max_length=500)
    connection_id: uuid.UUID | None = None
    sql_text: str | None = Field(None, min_length=1)
    param_schema: dict[str, ParamDescriptor] | None = None
    column_map: dict[str, str] | None = None
    auth_method_id: uuid.UUID | None = None
    allow_unauthenticated: bool | None = Field(
        None,
        description=(
            "Legacy-named opt-in to platform-admin Bearer authentication when "
            "detaching the endpoint-specific auth method."
        ),
    )
    data_strategy: DataStrategy | None = None
    is_active: bool | None = None
    is_deprecated: bool | None = None
    deprecation_note: str | None = Field(None, max_length=1000)

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip("/").lower()
        if not _PATH_RE.match(v):
            raise ValueError(
                "Path must contain only lowercase alphanumeric, hyphens, underscores, or slashes."
            )
        return v

    @field_validator("sql_text")
    @classmethod
    def validate_sql(cls, v: str | None) -> str | None:
        if v is None:
            return v
        errors = validate_sql_safety(v)
        if errors:
            raise ValueError("; ".join(errors))
        return v

    @model_validator(mode="after")
    def bind_params_match_schema(self) -> Self:
        # Only validate when both sql_text and param_schema are supplied together.
        if self.sql_text is not None and self.param_schema is not None:
            sql_params = set(extract_bind_params(self.sql_text))
            schema_params = set(self.param_schema.keys())
            undeclared = sql_params - schema_params
            unused = schema_params - sql_params
            if undeclared:
                raise ValueError(
                    f"SQL references params not declared in schema: {sorted(undeclared)}"
                )
            if unused:
                raise ValueError(
                    f"Schema declares params not referenced in SQL: {sorted(unused)}"
                )
        return self

    @model_validator(mode="after")
    def require_auth_or_explicit_fallback(self) -> Self:
        # When this request explicitly sets both fields, reject a configuration
        # with neither a dedicated method nor the platform Bearer fallback.
        fields_set = self.model_fields_set
        if "auth_method_id" in fields_set and "allow_unauthenticated" in fields_set:
            if self.auth_method_id is None and not self.allow_unauthenticated:
                raise ValueError(PUBLIC_OPT_IN_MESSAGE)
        return self


class EndpointResponse(BaseModel):
    """Read representation for API endpoints."""

    id: uuid.UUID
    name: str
    description: str | None
    path: str
    connection_id: uuid.UUID
    sql_text: str
    param_schema: dict[str, ParamDescriptor]
    column_map: dict[str, str]
    auth_method_id: uuid.UUID | None
    allow_unauthenticated: bool
    data_strategy: DataStrategy
    version: str
    is_active: bool
    is_deprecated: bool
    deprecation_note: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SqlPreviewRequest(BaseModel):
    """Request body for SQL preview execution."""

    connection_id: uuid.UUID
    sql_text: str = Field(..., min_length=1)
    params: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    max_rows: int = Field(10, ge=1, le=100)

    @field_validator("sql_text")
    @classmethod
    def validate_sql(cls, v: str) -> str:
        errors = validate_sql_safety(v)
        if errors:
            raise ValueError("; ".join(errors))
        return v


class SqlPreviewResponse(BaseModel):
    """Response from SQL preview execution."""

    columns: list[str]
    rows: list[dict[str, object]]
    row_count: int
    bind_params: list[str]
    duration_ms: float


class DataEndpointResponse(BaseModel):
    """Response from dynamic data endpoints."""

    data: list[dict[str, object]]
    meta: dict[str, object]
