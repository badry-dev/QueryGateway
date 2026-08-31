"""ApiEndpoint model — dynamic REST endpoint definitions.

An endpoint binds a parameterized Oracle SQL query to a public URL path and
controls which auth method and data strategy (live vs. snapshot) applies.

sql_text MUST use named bind variables (:param_name).  String-concatenated
SQL is rejected at the service layer before persistence.
"""

import uuid
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, String, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DataStrategy(StrEnum):
    live = "live"
    snapshot = "snapshot"


class ApiEndpoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Published or draft endpoint mapping a SQL query to a URL path."""

    __tablename__ = "endpoints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Path segment after /api/v1/data/ — must be unique across all endpoints.
    path: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connections.id", ondelete="RESTRICT"), nullable=False
    )
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON schema for bind parameters: {param_name: {type, required, default?}}.
    param_schema_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    # Optional output column rename/filter map: {source_col: output_col}.
    column_map_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    auth_method_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth_methods.id", ondelete="SET NULL"), nullable=True
    )
    # Legacy-named compatibility flag. When no endpoint-specific auth method is
    # attached, True opts into platform-admin Bearer authentication. The data
    # plane never serves anonymous requests.
    allow_unauthenticated: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    data_strategy: Mapped[DataStrategy] = mapped_column(
        SAEnum(DataStrategy, name="data_strategy"),
        default=DataStrategy.live,
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String(10), default="v1", nullable=False)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default=text("true")
    )
    is_deprecated: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    deprecation_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
