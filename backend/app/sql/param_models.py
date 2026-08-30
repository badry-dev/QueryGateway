"""Build a Pydantic model from a stored ``param_schema_json`` descriptor.

This replaces the hand-rolled ``_coerce_param`` loop that lived in
``app.routers.data``. Using ``pydantic.create_model`` gives us:

- Declarative validation (Pydantic surfaces the field name and reason).
- Free coercion for ints / floats / dates from request strings.
- Consistent error shape with the rest of the API.

The descriptor format mirrors ``app.schemas.endpoint.ParamDescriptor`` —
``{"type": "string|integer|float|boolean|date", "required": bool,
"default": <value>, "default_is_null": bool,
"default_expression": "today|yesterday",
"max_length": int | None}``.
"""

from datetime import date, timedelta
from typing import Annotated, Any, Literal, get_args

import structlog
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, create_model

log = structlog.get_logger()

ParamType = Literal["string", "integer", "float", "boolean", "date"]
_VALID_PARAM_TYPES = set(get_args(ParamType))

# Match the exact set the legacy ``_coerce_param`` accepted — Pydantic's
# default bool coercion is permissive about other forms (``y``, ``on``,
# truthy ints, etc.) which would silently broaden the contract.
_BOOL_TRUE = {"true", "1", "yes"}
_BOOL_FALSE = {"false", "0", "no"}


def _coerce_bool(value: object) -> object:
    """Pre-validator: accept exactly the same strings the legacy loop did.

    Pass through booleans (so a default of ``True`` round-trips) and let
    everything else fall through to Pydantic, which will raise a clear
    type error.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.lower()
        if normalized in _BOOL_TRUE:
            return True
        if normalized in _BOOL_FALSE:
            return False
        raise ValueError(f"expected true/false/1/0/yes/no, got '{value}'")
    return value


def resolve_default_expression(expression: str, *, current_date: date | None = None) -> date:
    """Resolve a supported dynamic date default using the server's local date."""
    resolved_date = current_date or date.today()
    if expression == "today":
        return resolved_date
    if expression == "yesterday":
        return resolved_date - timedelta(days=1)
    raise ValueError(f"Unsupported default expression: {expression}")


def _build_field(
    descriptor: dict[str, Any],
    *,
    current_date: date | None = None,
) -> tuple[type, Any]:
    """Map one descriptor to a ``(annotation, default)`` pair for ``create_model``."""
    raw_type = descriptor.get("type", "string")
    if raw_type not in _VALID_PARAM_TYPES:
        # Unknown type — treat as string. Matches the legacy fallback at
        # the bottom of ``_coerce_param``.
        raw_type = "string"

    required = bool(descriptor.get("required", True))
    default = descriptor.get("default")
    default_is_null = bool(descriptor.get("default_is_null", False))
    default_expression = descriptor.get("default_expression")
    if default_expression is not None:
        if raw_type != "date":
            raise ValueError("Dynamic defaults are supported only for date parameters.")
        if default is not None:
            raise ValueError("Declare either default or default_expression, not both.")
        default = resolve_default_expression(str(default_expression), current_date=current_date)
    max_length = descriptor.get("max_length")

    annotation: type
    if raw_type == "integer":
        annotation = int
    elif raw_type == "float":
        annotation = float
    elif raw_type == "boolean":
        annotation = Annotated[bool, BeforeValidator(_coerce_bool)]  # type: ignore[assignment]
    elif raw_type == "date":
        annotation = date
    else:  # "string"
        annotation = str
        if isinstance(max_length, int) and max_length >= 1:
            annotation = Annotated[str, Field(max_length=max_length)]  # type: ignore[assignment]

    if default_is_null:
        annotation = annotation | None  # type: ignore[assignment]
        field_default = None
    elif default is not None:
        field_default = default
    elif required:
        field_default = ...
    else:
        # Optional with no configured default: the field accepts a
        # missing value by defaulting to None.  ``validate_default=True``
        # would reject ``None`` as a default for a non-nullable
        # annotation (``int``, ``date``, etc.), so widen the annotation
        # to ``T | None`` here.  This path matches legacy behavior:
        # ``_coerce_param`` skipped optional params entirely when they
        # weren't supplied.
        annotation = annotation | None  # type: ignore[assignment]
        field_default = None

    return annotation, field_default


def build_param_model(
    param_schema: dict[str, Any],
    *,
    current_date: date | None = None,
) -> type[BaseModel]:
    """Construct a Pydantic model that validates ``param_schema`` payloads.

    Non-dict values in ``param_schema`` are ignored to match the legacy
    ``_coerce_param`` loop, which skipped them defensively. A warning is
    emitted so operators can spot a corrupted schema.

    The model uses ``extra="ignore"``: callers (notably ``DataService.
    _coerce_params``) pre-filter the request to only include parameters
    declared in the schema, so unknown keys never reach the model.
    Choosing ``ignore`` over ``forbid`` makes that contract explicit.
    """
    fields: dict[str, tuple[type, Any]] = {}
    for name, descriptor in param_schema.items():
        if not isinstance(descriptor, dict):
            log.warning(
                "param_schema_invalid_descriptor",
                param_name=name,
                descriptor_type=type(descriptor).__name__,
            )
            continue
        fields[name] = _build_field(descriptor, current_date=current_date)

    model: type[BaseModel] = create_model(
        "EndpointParams",
        # ``validate_default=True`` makes Pydantic coerce/validate the
        # ``default`` we feed each field. Without it, a corrupted stored
        # descriptor (e.g. ``{"type": "integer", "default": "abc"}``)
        # would silently bypass validation and surface as an invalid
        # bind parameter at SQL execution time.
        __config__=ConfigDict(extra="ignore", validate_default=True),
        **fields,  # type: ignore[call-overload]
    )
    return model
