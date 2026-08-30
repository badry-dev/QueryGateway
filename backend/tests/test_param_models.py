"""Tests for the parameter-model builder.

These tests exist in two parts:

1. ``test_legacy_coerce_param_*`` — golden tests that pin down the
   *current* behavior of the hand-rolled ``_coerce_param`` function in
   ``app.routers.data``. Captured before extraction so the Pydantic-based
   replacement can be checked for parity.
2. ``test_build_param_model_*`` — equivalent assertions against the new
   ``build_param_model`` factory. Both test sets must agree.

Once Phase 4 lands, the legacy block is kept (with the legacy import
removed) for as long as the descriptor format stays stable, since the
descriptor JSON is what's actually persisted in the DB and any drift
in coercion would silently change request semantics.
"""

from datetime import date

import pytest
from app.sql.param_models import build_param_model
from pydantic import ValidationError

# ── Golden cases shared by both implementations ──────────────────────────────

# (descriptor, raw_value_str, expected_python_value_or_exception)
_GOLDEN_CASES: list[tuple[dict[str, object], str, object]] = [
    # string
    ({"type": "string", "required": True}, "hello", "hello"),
    ({"type": "string", "required": True, "max_length": 5}, "12345", "12345"),
    # integer
    ({"type": "integer", "required": True}, "42", 42),
    ({"type": "integer", "required": True}, "-7", -7),
    # float
    ({"type": "float", "required": True}, "3.14", 3.14),
    ({"type": "float", "required": True}, "0", 0.0),
    # boolean (case-insensitive: true/false/1/0/yes/no)
    ({"type": "boolean", "required": True}, "true", True),
    ({"type": "boolean", "required": True}, "TRUE", True),
    ({"type": "boolean", "required": True}, "1", True),
    ({"type": "boolean", "required": True}, "yes", True),
    ({"type": "boolean", "required": True}, "false", False),
    ({"type": "boolean", "required": True}, "0", False),
    ({"type": "boolean", "required": True}, "NO", False),
    # date — must be ISO format
    ({"type": "date", "required": True}, "2024-01-15", date(2024, 1, 15)),
]

_GOLDEN_FAILURES: list[tuple[dict[str, object], str]] = [
    ({"type": "integer", "required": True}, "abc"),
    ({"type": "float", "required": True}, "not-a-float"),
    ({"type": "boolean", "required": True}, "maybe"),
    ({"type": "date", "required": True}, "not-a-date"),
    ({"type": "date", "required": True}, "2024/01/15"),
    ({"type": "string", "required": True, "max_length": 3}, "this-is-too-long"),
]


# ── New Pydantic-based path ──────────────────────────────────────────────────


@pytest.mark.parametrize(("descriptor", "raw", "expected"), _GOLDEN_CASES)
def test_build_param_model_coerces_value(
    descriptor: dict[str, object], raw: str, expected: object
) -> None:
    Model = build_param_model({"p": descriptor})
    instance = Model.model_validate({"p": raw})
    assert instance.model_dump()["p"] == expected


@pytest.mark.parametrize(("descriptor", "raw"), _GOLDEN_FAILURES)
def test_build_param_model_rejects_value(
    descriptor: dict[str, object], raw: str
) -> None:
    Model = build_param_model({"p": descriptor})
    with pytest.raises(ValidationError):
        Model.model_validate({"p": raw})


def test_build_param_model_required_missing_raises() -> None:
    Model = build_param_model({"p": {"type": "string", "required": True}})
    with pytest.raises(ValidationError) as exc_info:
        Model.model_validate({})
    assert any(err["loc"] == ("p",) for err in exc_info.value.errors())


def test_build_param_model_optional_uses_default() -> None:
    Model = build_param_model(
        {"p": {"type": "integer", "required": False, "default": 10}},
    )
    instance = Model.model_validate({})
    assert instance.model_dump()["p"] == 10


def test_build_param_model_supports_multiple_params() -> None:
    Model = build_param_model(
        {
            "dept_id": {"type": "integer", "required": True},
            "active": {"type": "boolean", "required": False, "default": True},
            "name": {"type": "string", "required": False, "default": ""},
        },
    )
    instance = Model.model_validate({"dept_id": "5", "name": "alice"})
    data = instance.model_dump()
    assert data == {"dept_id": 5, "active": True, "name": "alice"}


def test_build_param_model_ignores_non_dict_descriptors() -> None:
    """The legacy ``_coerce_param`` loop skipped non-dict descriptors via
    ``if not isinstance(descriptor, dict): continue``.  Match that
    behavior so corrupted DB rows don't crash the data router."""
    Model = build_param_model({"p": {"type": "string", "required": True}, "junk": "garbage"})
    instance = Model.model_validate({"p": "hello"})
    assert instance.model_dump() == {"p": "hello"}


def test_build_param_model_empty_schema_returns_empty_model() -> None:
    Model = build_param_model({})
    instance = Model.model_validate({})
    assert instance.model_dump() == {}


def test_build_param_model_unknown_type_falls_back_to_string() -> None:
    """Legacy ``_coerce_param`` returned the raw string for unknown types.
    The new builder must keep that fallback so a corrupted ``type`` field
    doesn't 500 every request."""
    Model = build_param_model({"p": {"type": "unknown_type", "required": True}})
    instance = Model.model_validate({"p": "any-value"})
    assert instance.model_dump()["p"] == "any-value"


def test_build_param_model_boolean_default_round_trips() -> None:
    """A native bool default must survive ``_coerce_bool``'s pass-through
    and produce the same bool when the param is missing."""
    Model = build_param_model(
        {"p": {"type": "boolean", "required": False, "default": True}},
    )
    instance = Model.model_validate({})
    assert instance.model_dump()["p"] is True


def test_build_param_model_default_applies_when_required_and_missing() -> None:
    """Legacy code applied a configured ``default`` whenever the param was
    missing — regardless of the ``required`` flag. Pin that contract here
    so the Pydantic-based path doesn't 422 endpoints whose stored schema
    combined ``required=true`` with a non-null default."""
    Model = build_param_model(
        {"p": {"type": "integer", "required": True, "default": 42}},
    )
    instance = Model.model_validate({})
    assert instance.model_dump()["p"] == 42


def test_build_param_model_rejects_corrupt_default() -> None:
    """A stored descriptor whose ``default`` is incompatible with its
    ``type`` must raise at model-construction (or first validation) so a
    bad config can't slip through and hit the SQL layer as an invalid
    bind parameter. ``ConfigDict(validate_default=True)`` is what makes
    this fire."""
    Model = build_param_model(
        {"p": {"type": "integer", "required": False, "default": "abc"}},
    )
    with pytest.raises(ValidationError):
        Model.model_validate({})


def test_build_param_model_optional_without_default_returns_none() -> None:
    """An optional param with no configured default must accept the
    missing value and produce ``None``. Regression for the interaction
    between ``validate_default=True`` and a non-nullable annotation
    (e.g. ``int``) where ``None`` would otherwise fail the type check."""
    Model = build_param_model({"p": {"type": "integer", "required": False}})
    instance = Model.model_validate({})
    assert instance.model_dump()["p"] is None


def test_build_param_model_optional_without_default_accepts_value() -> None:
    """And when the param IS supplied, the optional widening to
    ``T | None`` must still coerce correctly (no Optional-related
    detour through string)."""
    Model = build_param_model({"p": {"type": "integer", "required": False}})
    instance = Model.model_validate({"p": "42"})
    assert instance.model_dump()["p"] == 42


def test_build_param_model_resolves_today_expression() -> None:
    Model = build_param_model(
        {"p": {"type": "date", "required": True, "default_expression": "today"}},
        current_date=date(2026, 8, 30),
    )
    assert Model.model_validate({}).model_dump()["p"] == date(2026, 8, 30)


def test_build_param_model_resolves_yesterday_expression() -> None:
    Model = build_param_model(
        {
            "p": {
                "type": "date",
                "required": True,
                "default_expression": "yesterday",
            }
        },
        current_date=date(2026, 8, 30),
    )
    assert Model.model_validate({}).model_dump()["p"] == date(2026, 8, 29)


def test_build_param_model_explicit_value_overrides_dynamic_default() -> None:
    Model = build_param_model(
        {"p": {"type": "date", "required": True, "default_expression": "today"}},
        current_date=date(2026, 8, 30),
    )
    assert Model.model_validate({"p": "2026-01-15"}).model_dump()["p"] == date(
        2026, 1, 15
    )
