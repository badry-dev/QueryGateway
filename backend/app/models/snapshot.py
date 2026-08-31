"""Snapshot model — cached JSONB query result for snapshot-strategy endpoints."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class Snapshot(UUIDPrimaryKeyMixin, Base):
    """Immutable cache of a single scheduler query execution result.

    snapshot-strategy endpoints read from the latest Snapshot for their
    endpoint_id, falling back to the previous one on job failure.
    """

    __tablename__ = "snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("endpoints.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable: ad-hoc or legacy snapshots may have no associated job run.
    job_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_runs.id", ondelete="SET NULL"), nullable=True
    )

    # Full query result stored as a JSON array of row objects.
    data: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
