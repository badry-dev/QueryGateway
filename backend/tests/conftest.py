"""pytest configuration and shared fixtures.

Database strategy
-----------------
Tests use the DATABASE_URL from environment (identical to the CI Postgres
service declared in .github/workflows/backend.yml).  The session-scoped
``engine`` fixture creates all tables before the suite runs and drops them
after — providing a clean slate without spinning up a separate test DB.

Each test gets its own session that is rolled back at teardown, so tests
are fully isolated and leave no persistent state.

Async
-----
All fixtures and tests are async (pytest-asyncio asyncio_mode = "auto").
The ASGI app is exercised through httpx.AsyncClient with ASGITransport,
which exercises the full middleware stack without a live TCP connection.
"""

import os

# Set required env vars before any app module is imported so that
# pydantic-settings can construct Settings() without a .env file.
# These values are safe for testing only — never use them in production.
os.environ.setdefault(
    "ENCRYPTION_KEY",
    # Valid Fernet key (base64-encoded 32 bytes of zeroes) for test isolation.
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
)
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-secret-key-do-not-use-in-production",
)
# Test-only admin credentials. Plaintext for ADMIN_PASSWORD_HASH is the
# string in ADMIN_TEST_PASSWORD below.  Keep the hash in sync with the
# value in .github/workflows/backend.yml.
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault(
    "ADMIN_PASSWORD_HASH",
    "$2b$12$YzgLtLngpsgS39BQBSK0We/dWJoG7/pGiGpHrYMAB.ffcru5FC84q",
)

from collections.abc import AsyncGenerator

import pytest
from app.auth.jwt_utils import create_access_token
from app.config import settings
from app.dependencies import get_db
from app.main import app
from app.models.base import Base
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Plaintext counterpart to ADMIN_PASSWORD_HASH above. Tests import this
# rather than hard-coding the password in each file.
ADMIN_TEST_PASSWORD = "admin-password-do-not-use-in-prod"


def _assert_safe_test_database(database_url: str, app_env: str) -> None:
    """Require both an explicit test environment and a test-named database."""
    if app_env != "test" or "test" not in database_url.lower():
        raise RuntimeError(
            "Refusing to run destructive test schema setup: APP_ENV must be "
            "'test' and DATABASE_URL must contain 'test'."
        )


def _mint_admin_token() -> str:
    """Mint a valid admin JWT using the test-time settings.

    Used to authenticate the default ``async_client`` so existing
    integration tests don't have to know about the new login flow.
    Negative-path tests should use ``unauth_client`` instead.
    """
    token, _ = create_access_token(
        subject=settings.admin_username,
        secret=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expire_minutes=settings.jwt_access_token_expire_minutes,
    )
    return token


@pytest.fixture()
async def engine() -> AsyncGenerator[AsyncEngine]:
    """Function-scoped engine: each test gets a fresh schema on the test's
    own event loop.

    Why function-scoped? pytest-asyncio 0.25 runs each test on its own event
    loop (controlled by an internal marker that, in auto mode, defaults to
    function scope and cannot be overridden via ini). asyncpg connections
    are loop-bound, so a session-scoped engine ends up handing connections
    from one loop into tests running on a different loop, triggering
    ``RuntimeError: Future attached to a different loop``. Recreating the
    engine per test costs a few hundred ms total across the suite but
    eliminates the entire class of cross-loop bugs and keeps tests fully
    isolated. Revisit once pytest-asyncio >= 0.26 (with
    ``asyncio_default_test_loop_scope``) is adopted.

    Lifecycle: ``drop_all`` then ``create_all`` before yield (cleans up
    leftover tables from a crashed prior run); ``drop_all`` after yield
    so the database is left empty between tests.
    """
    database_url = settings.database_url
    # Hard safety guard: both signals are mandatory. Requiring only one means
    # APP_ENV=test can accidentally target and wipe the development database.
    _assert_safe_test_database(database_url, settings.app_env)

    test_engine = create_async_engine(database_url, echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Production code that opens its own ``AsyncSessionLocal()`` (notably
    # the access-log writer in ``app.services.access_log``) bypasses the
    # request-scoped session override.  Repoint the module-level factory
    # at the test engine for the duration of the test so those writes
    # land in the same database the test reads from.
    import app.database

    real_engine = app.database.engine
    real_factory = app.database.AsyncSessionLocal
    app.database.engine = test_engine
    app.database.AsyncSessionLocal = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    try:
        yield test_engine
    finally:
        app.database.engine = real_engine
        app.database.AsyncSessionLocal = real_factory
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await test_engine.dispose()


@pytest.fixture()
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Per-test async session; rolled back after each test."""
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture()
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    """HTTP test client wired to the FastAPI app with a test DB session.

    Authenticated by default — every request carries a valid admin
    bearer token so existing admin-route integration tests keep
    working post-Phase-2.  Use ``unauth_client`` to test 401 paths
    explicitly.
    """

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {_mint_admin_token()}"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
async def unauth_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    """HTTP test client without an Authorization header.

    Use for tests that verify the 401 path on admin routes.
    """

    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
async def http_client() -> AsyncGenerator[AsyncClient]:
    """HTTP test client with no DB dependency override.

    Use this fixture for endpoints that do not touch the database (e.g.
    /live).  Safe to run without a PostgreSQL instance.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
