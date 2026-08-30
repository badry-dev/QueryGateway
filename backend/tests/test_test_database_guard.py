"""Regression coverage for the destructive test-database safety guard."""

import pytest

from tests.conftest import _assert_safe_test_database


def test_database_guard_accepts_explicit_test_database() -> None:
    _assert_safe_test_database(
        "postgresql+asyncpg://user:pass@db:5432/db2api_test", "test"
    )


@pytest.mark.parametrize(
    ("database_url", "app_env"),
    [
        ("postgresql+asyncpg://user:pass@db:5432/db2api", "test"),
        ("postgresql+asyncpg://user:pass@db:5432/db2api_test", "development"),
        ("postgresql+asyncpg://user:pass@db:5432/db2api", "development"),
    ],
)
def test_database_guard_rejects_any_non_test_signal(
    database_url: str, app_env: str
) -> None:
    with pytest.raises(RuntimeError, match="APP_ENV must be 'test'"):
        _assert_safe_test_database(database_url, app_env)
