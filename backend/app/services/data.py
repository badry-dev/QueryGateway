"""Service that backs the dynamic ``/api/v1/data/{path}`` endpoint.

Phase 4 lifts orchestration out of the router so ``data.py`` can stay
thin. Responsibilities here:

- Resolve the endpoint by path (404 / 404-when-deactivated).
- Enforce per-endpoint auth when configured (delegates to
  ``AuthMethodService``).
- Coerce request query params via the dynamic Pydantic model built from
  the endpoint's ``param_schema_json`` (replaces the hand-rolled coercion
  that used to live in ``app.routers.data``).
- Dispatch to the correct backend (cached snapshot vs. live SQL).
- Apply optional column-rename mapping.

The router is responsible only for wiring the request, the dependency,
and the access-log context manager.
"""

from __future__ import annotations

import base64
import time
import uuid
from typing import Any

import structlog
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.admin import get_current_admin
from app.middleware import resolve_request_id
from app.models.endpoint import ApiEndpoint
from app.repositories.auth_method import AuthMethodRepository
from app.repositories.connection import ConnectionRepository
from app.repositories.endpoint import EndpointRepository
from app.repositories.job_run import JobRunRepository
from app.repositories.snapshot import SnapshotRepository
from app.schemas.endpoint import SnapshotConfigurationError, require_snapshot_filter_mappings
from app.services.auth_method import AuthMethodService
from app.services.snapshot_filtering import (
    compile_snapshot_filters,
    filter_snapshot_rows,
    snapshot_covers_request,
    unavailable_snapshot_filter_columns,
    validate_snapshot_parameter_ranges,
    validate_snapshot_rows_match_resolved_parameters,
)
from app.sql.executor import SqlExecutionError, execute_query
from app.sql.param_models import build_param_model

log = structlog.get_logger()


def _apply_column_map(
    rows: list[dict[str, object]], column_map: dict[str, object]
) -> list[dict[str, object]]:
    """Rename columns in result rows based on the endpoint's column_map."""
    if not column_map:
        return rows
    mapped: list[dict[str, object]] = []
    for row in rows:
        new_row: dict[str, object] = {}
        for key, value in row.items():
            output_key = column_map.get(key)
            new_row[output_key if isinstance(output_key, str) else key] = value
        mapped.append(new_row)
    return mapped


def _deprecation_headers(endpoint: ApiEndpoint) -> dict[str, str]:
    """Build deprecation-related response headers.

    ``deprecation_note`` is a free-form string the admin enters; it is
    NOT an HTTP-date, so RFC 8594 says it doesn't belong in the
    standard ``Sunset`` header. Send it as the unofficial
    ``X-Deprecation-Note`` instead. If a real sunset date field is
    added later, that can populate ``Sunset`` separately.
    """
    if not endpoint.is_deprecated:
        return {}
    headers: dict[str, str] = {"Deprecation": "true"}
    if endpoint.deprecation_note:
        headers["X-Deprecation-Note"] = endpoint.deprecation_note
    return headers


class DataServiceResult:
    """Return shape from ``DataService.serve``: response + audit metadata."""

    __slots__ = ("response", "principal", "endpoint_id")

    def __init__(
        self,
        response: JSONResponse,
        principal: str | None,
        endpoint_id: uuid.UUID | None,
    ) -> None:
        self.response = response
        self.principal = principal
        self.endpoint_id = endpoint_id


class DataService:
    """Business-logic owner for the dynamic data endpoint."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def serve(self, path: str, request: Request) -> DataServiceResult:
        """Resolve and serve the endpoint at ``path``.

        Raises ``HTTPException`` for 401 (auth) and 404 (missing /
        inactive). Other failure modes are returned as JSONResponse with
        the appropriate status code; the caller (router + access log
        context) reads ``response.status_code`` to record outcomes.
        """
        started_at = time.perf_counter()
        endpoint = await self._resolve_endpoint(path)
        principal: str | None = None
        if endpoint.auth_method_id is not None:
            principal = await self._enforce_auth(request, endpoint.auth_method_id)
        elif not endpoint.allow_unauthenticated:
            self._log_platform_auth_denied(request, endpoint, started_at, path)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication configuration is unavailable.",
            )
        else:
            principal = await self._enforce_platform_auth(request, endpoint, started_at, path)

        if endpoint.data_strategy.value == "snapshot":
            response = await self._serve_snapshot(
                endpoint,
                request,
                path,
                principal,
                started_at,
            )
        else:
            response = await self._serve_live(endpoint, request, path, principal)

        return DataServiceResult(
            response=response,
            principal=principal,
            endpoint_id=endpoint.id,
        )

    async def _enforce_platform_auth(
        self,
        request: Request,
        endpoint: ApiEndpoint,
        started_at: float,
        path: str,
    ) -> str:
        """Require the platform admin bearer token when no endpoint auth is set."""
        authorization = request.headers.get("Authorization", "")
        credentials = None
        if authorization.lower().startswith("bearer "):
            credentials = HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=authorization[7:].strip(),
            )

        try:
            principal = await get_current_admin(credentials)
        except HTTPException:
            self._log_platform_auth_denied(request, endpoint, started_at, path)
            raise
        return principal.username

    @staticmethod
    def _log_platform_auth_denied(
        request: Request,
        endpoint: ApiEndpoint,
        started_at: float,
        path: str,
    ) -> None:
        log.warning(
            "unauthenticated_endpoint_denied",
            endpoint_id=str(endpoint.id),
            endpoint=path,
            user="anonymous",
            status=status.HTTP_401_UNAUTHORIZED,
            method=request.method,
            client_ip=request.client.host if request.client else None,
            request_id=resolve_request_id(request),
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )

    # ── Endpoint lookup ─────────────────────────────────────────────────────

    async def _resolve_endpoint(self, path: str) -> ApiEndpoint:
        endpoint = await EndpointRepository(self._db).get_by_path(path)
        if endpoint is None or not endpoint.is_active:
            # Deactivated endpoints look the same as missing ones to the
            # data plane — don't leak existence.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No endpoint registered at /api/v1/data/{path}.",
            )
        return endpoint

    # ── Auth (per-endpoint) ─────────────────────────────────────────────────

    async def _enforce_auth(self, request: Request, auth_method_id: uuid.UUID) -> str:
        svc = AuthMethodService(AuthMethodRepository(self._db))
        auth_method = await svc.get_auth_method(auth_method_id)
        if auth_method is None or not auth_method.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication configuration is unavailable.",
            )

        method_type = auth_method.method_type
        authorization = request.headers.get("Authorization", "")

        if method_type == "bearer":
            if not authorization.lower().startswith("bearer "):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Bearer token required.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            token = authorization[7:]
            principal = await svc.verify_bearer(auth_method_id, token)
            if principal is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return principal

        if method_type == "basic":
            if not authorization.lower().startswith("basic "):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Basic credentials required.",
                    headers={"WWW-Authenticate": "Basic"},
                )
            try:
                decoded = base64.b64decode(authorization[6:]).decode()
                username, _, password = decoded.partition(":")
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Malformed Basic credentials.",
                ) from exc
            ok = await svc.verify_basic(auth_method_id, username, password)
            if not ok:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid username or password.",
                    headers={"WWW-Authenticate": "Basic"},
                )
            return username

        if method_type == "api_key":
            # Header only: a key in the query string leaks via proxy/access
            # logs, browser history, and the Referer header (L1). The
            # query-param fallback was removed deliberately.
            api_key = request.headers.get("X-Api-Key", "")
            if not api_key:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="API key required (X-Api-Key header).",
                )
            ok = await svc.verify_api_key(auth_method_id, api_key)
            if not ok:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key.",
                )
            return "api_key"

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unsupported auth method type.",
        )

    # ── Snapshot mode ───────────────────────────────────────────────────────

    async def _serve_snapshot(
        self,
        endpoint: ApiEndpoint,
        request: Request,
        path: str,
        principal: str | None,
        started_at: float,
    ) -> JSONResponse:
        try:
            params = self._coerce_params(endpoint, request)
        except ValidationError as exc:
            return self._parameter_validation_response(exc)

        param_schema = endpoint.param_schema_json or {}
        try:
            require_snapshot_filter_mappings(endpoint.data_strategy, param_schema)
        except SnapshotConfigurationError:
            self._log_snapshot_rejection(
                request=request,
                endpoint=endpoint,
                path=path,
                principal=principal,
                started_at=started_at,
                event="snapshot_filter_not_configured",
            )
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={
                    "code": "snapshot_filter_not_configured",
                    "detail": ("Snapshot request filtering is not configured for every parameter."),
                },
            )
        filters = compile_snapshot_filters(param_schema)
        try:
            validate_snapshot_parameter_ranges(
                filters=filters,
                request_params=params,
            )
        except ValueError:
            self._log_snapshot_rejection(
                request=request,
                endpoint=endpoint,
                path=path,
                principal=principal,
                started_at=started_at,
                event="invalid_snapshot_parameter_range",
            )
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={
                    "code": "invalid_parameter_range",
                    "detail": "Snapshot filter lower bound must not exceed its upper bound.",
                },
            )

        snapshots = await SnapshotRepository(self._db).get_by_endpoint(endpoint.id, limit=100)
        if not snapshots:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": "No snapshot available yet. Wait for the scheduled job to run."},
            )

        snapshot = None
        integrity_failures: list[tuple[str, str]] = []
        if not param_schema:
            snapshot = snapshots[0]
        else:
            candidate_run_ids = list(
                dict.fromkeys(
                    candidate.job_run_id
                    for candidate in snapshots
                    if candidate.job_run_id is not None
                )
            )
            job_runs = await JobRunRepository(self._db).get_by_ids(candidate_run_ids)
            job_runs_by_id = {job_run.id: job_run for job_run in job_runs}
            for candidate in snapshots:
                if candidate.job_run_id is None:
                    continue
                job_run = job_runs_by_id.get(candidate.job_run_id)
                if job_run is None or not snapshot_covers_request(
                    filters=filters,
                    request_params=params,
                    resolved_params=job_run.resolved_params_json or {},
                ):
                    continue

                candidate_data: list[dict[str, object]] = (
                    candidate.data if isinstance(candidate.data, list) else []
                )
                if unavailable_snapshot_filter_columns(rows=candidate_data, filters=filters):
                    # Preserve the existing configuration-error response below. An endpoint edit
                    # can invalidate mappings even when the stored snapshot itself was valid.
                    snapshot = candidate
                    break
                try:
                    validate_snapshot_rows_match_resolved_parameters(
                        rows=candidate_data,
                        filters=filters,
                        resolved_params=job_run.resolved_params_json or {},
                    )
                except ValueError as exc:
                    integrity_failures.append((str(candidate.id), str(exc)))
                    continue
                snapshot = candidate
                break

        if snapshot is None:
            if integrity_failures:
                self._log_snapshot_rejection(
                    request=request,
                    endpoint=endpoint,
                    path=path,
                    principal=principal,
                    started_at=started_at,
                    event="snapshot_integrity_failed",
                    response_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    details={
                        "snapshot_ids": [item[0] for item in integrity_failures],
                        "integrity_errors": [item[1] for item in integrity_failures],
                    },
                )
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={
                        "code": "snapshot_integrity_failed",
                        "detail": "No retained snapshot passed integrity validation.",
                    },
                )
            self._log_snapshot_rejection(
                request=request,
                endpoint=endpoint,
                path=path,
                principal=principal,
                started_at=started_at,
                event="snapshot_out_of_coverage",
            )
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={
                    "code": "snapshot_out_of_coverage",
                    "detail": "Requested parameters are outside retained snapshot coverage.",
                },
            )

        snapshot_data: list[dict[str, object]] = (
            snapshot.data if isinstance(snapshot.data, list) else []
        )
        if unavailable_snapshot_filter_columns(
            rows=snapshot_data,
            filters=filters,
        ):
            self._log_snapshot_rejection(
                request=request,
                endpoint=endpoint,
                path=path,
                principal=principal,
                started_at=started_at,
                event="snapshot_filter_column_unavailable",
            )
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content={
                    "code": "snapshot_filter_column_unavailable",
                    "detail": "A configured snapshot filter column is unavailable.",
                },
            )
        filtered_data = filter_snapshot_rows(
            rows=snapshot_data,
            filters=filters,
            request_params=params,
        )
        return JSONResponse(
            status_code=200,
            content={
                "data": filtered_data,
                "meta": {
                    "row_count": len(filtered_data),
                    "snapshot_row_count": snapshot.row_count,
                    "endpoint": path,
                    "version": endpoint.version,
                    "data_strategy": "snapshot",
                    "snapshot_created_at": snapshot.created_at.isoformat(),
                },
            },
            headers=_deprecation_headers(endpoint),
        )

    @staticmethod
    def _log_snapshot_rejection(
        *,
        request: Request,
        endpoint: ApiEndpoint,
        path: str,
        principal: str | None,
        started_at: float,
        event: str,
        response_status: int = status.HTTP_422_UNPROCESSABLE_ENTITY,
        details: dict[str, object] | None = None,
    ) -> None:
        """Emit required request context before a snapshot rejection response."""
        log.warning(
            event,
            request_id=resolve_request_id(request),
            user=principal or "anonymous",
            endpoint=path,
            endpoint_id=str(endpoint.id),
            status=response_status,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            method=request.method,
            client_ip=request.client.host if request.client else None,
            **(details or {}),
        )

    # ── Live mode ───────────────────────────────────────────────────────────

    async def _serve_live(
        self,
        endpoint: ApiEndpoint,
        request: Request,
        path: str,
        principal: str | None,
    ) -> JSONResponse:
        try:
            params = self._coerce_params(endpoint, request)
        except ValidationError as exc:
            return self._parameter_validation_response(exc)

        connection = await ConnectionRepository(self._db).get_by_id(endpoint.connection_id)
        if connection is None or not connection.is_active:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": "Data source connection is unavailable."},
            )

        # Time the executor call locally so the failure log can report
        # duration_ms even when ``execute_query`` raises before returning
        # its own measurement.
        query_start = time.perf_counter()
        try:
            columns, rows, query_duration_ms = await execute_query(
                connection=connection,
                sql=endpoint.sql_text,
                params=params,
            )
        except SqlExecutionError as exc:
            duration_ms = round((time.perf_counter() - query_start) * 1000, 2)
            log.error(
                "data_endpoint_query_failed",
                endpoint_id=str(endpoint.id),
                endpoint=path,
                user=principal or "anonymous",
                status=500,
                request_id=resolve_request_id(request),
                method=request.method,
                client_ip=request.client.host if request.client else None,
                duration_ms=duration_ms,
                error=str(exc),
            )
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Query execution failed."},
            )

        mapped_rows = _apply_column_map(rows, endpoint.column_map_json or {})

        return JSONResponse(
            status_code=200,
            content={
                "data": mapped_rows,
                "meta": {
                    "row_count": len(mapped_rows),
                    "query_duration_ms": query_duration_ms,
                    "endpoint": path,
                    "version": endpoint.version,
                    "data_strategy": endpoint.data_strategy.value,
                },
            },
            headers=_deprecation_headers(endpoint),
        )

    @staticmethod
    def _parameter_validation_response(exc: ValidationError) -> JSONResponse:
        """Return a stable public error for typed query-parameter failures."""
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first.get("loc", ())) or "?"
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": f"Invalid value for parameter '{field}': {first.get('msg')}"},
        )

    @staticmethod
    def _coerce_params(endpoint: ApiEndpoint, request: Request) -> dict[str, Any]:
        param_schema = endpoint.param_schema_json or {}
        # Schedule-owned bindings make snapshot refreshes autonomous, but they
        # do not make required HTTP query parameters optional. Live and
        # snapshot callers must supply every descriptor marked required;
        # endpoint defaults apply only to omitted optional request fields.
        Model = build_param_model(param_schema, enforce_required=True)
        # Pull only declared params from the query string; ignore unknowns
        # so the legacy loop's behavior is preserved. Filter on
        # ``isinstance(descriptor, dict)`` so a corrupted non-dict
        # schema entry (which ``build_param_model`` skips when defining
        # fields) doesn't sneak through and force ``extra=ignore`` to
        # silently drop the value mid-request.
        declared = {
            name: request.query_params[name]
            for name, descriptor in param_schema.items()
            if isinstance(descriptor, dict) and name in request.query_params
        }
        return Model.model_validate(declared).model_dump()
