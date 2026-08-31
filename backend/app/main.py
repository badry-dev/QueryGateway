"""QueryGateway FastAPI application factory.

Responsibilities of this module:
- Create the FastAPI instance with metadata and lifespan.
- Register middleware (ordering matters: outermost first).
- Register global exception handlers.
- Mount all versioned routers.

Keep business logic out of this file.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.exceptions import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.logging_config import configure_logging
from app.middleware import RequestLoggingMiddleware
from app.routers import (
    auth,
    auth_methods,
    connections,
    data,
    endpoints,
    health,
    schedules,
)
from app.routers import (
    settings as settings_router,
)
from app.services.scheduler import start_scheduler, stop_scheduler

log = structlog.get_logger()


def _init_oracle_client() -> None:
    """Initialize the Oracle thick-mode client once at startup.

    Previously ``oracledb.init_oracle_client`` was called per-request from
    ``_execute_sync`` whenever a thick-mode connection ran a query, which
    is both wasteful and unsafe (the function is intended to be called
    exactly once per process). Lifting it here keeps thin-mode users
    free of the dependency entirely while still supporting thick-mode
    deployments that need the Instant Client.
    """
    if not settings.oracle_client_lib_dir:
        return
    try:
        import oracledb  # noqa: PLC0415

        oracledb.init_oracle_client(lib_dir=settings.oracle_client_lib_dir)
        log.info(
            "oracle_client_initialized",
            lib_dir=settings.oracle_client_lib_dir,
        )
    except Exception as exc:  # noqa: BLE001
        # Don't crash the whole app on Oracle bootstrap failures —
        # connections will surface a clearer error on first use.
        # ``error_type`` lets operators correlate this warning with the
        # downstream "Query execution failed: ..." raised by the executor.
        log.warning(
            "oracle_client_init_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )


def _docs_urls() -> dict[str, str | None]:
    """Resolve interactive-docs URLs, disabling them in production (L3).

    Exposing the full admin API schema (``/api/docs``, ``/api/redoc``,
    ``/api/openapi.json``) in production hands an attacker a map of every
    route and payload shape. Return ``None`` for all three when
    ``APP_ENV=production`` so FastAPI does not mount them.
    """
    if settings.app_env == "production":
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {
        "docs_url": "/api/docs",
        "redoc_url": "/api/redoc",
        "openapi_url": "/api/openapi.json",
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application startup / shutdown lifecycle."""
    configure_logging(settings.log_level)
    log.info(
        "application_startup",
        env=settings.app_env,
        debug=settings.debug,
    )
    _init_oracle_client()
    await start_scheduler()
    yield
    stop_scheduler()
    log.info("application_shutdown")


_docs = _docs_urls()
app = FastAPI(
    title="QueryGateway",
    description="Secure, dynamic REST endpoints from Oracle SQL queries.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=_docs["docs_url"],
    redoc_url=_docs["redoc_url"],
    openapi_url=_docs["openapi_url"],
)

# ── Middleware (registered outermost-first; executes in reverse order) ────────

# CORSMiddleware must be registered before RequestLoggingMiddleware so CORS
# headers are applied to error responses as well.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestLoggingMiddleware)

# ── Exception handlers ────────────────────────────────────────────────────────

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(connections.router)
app.include_router(auth_methods.router)
app.include_router(endpoints.router)
app.include_router(schedules.router)
app.include_router(settings_router.router)
app.include_router(data.router)
