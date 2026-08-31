"""Preserve job runs when deleting endpoints.

Revision ID: c7e91a4f2d60
Revises: b2d18f4a6c73
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e91a4f2d60"
down_revision: str | None = "b2d18f4a6c73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("job_runs_endpoint_id_fkey", "job_runs", type_="foreignkey")
    op.alter_column(
        "job_runs",
        "endpoint_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.create_foreign_key(
        "job_runs_endpoint_id_fkey",
        "job_runs",
        "endpoints",
        ["endpoint_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("job_runs_endpoint_id_fkey", "job_runs", type_="foreignkey")
    # Endpoints deleted after this migration cannot be reconstructed. Remove
    # only their orphaned audit rows so the original NOT NULL contract can be
    # restored; any surviving snapshots already reference other job runs.
    op.execute("DELETE FROM job_runs WHERE endpoint_id IS NULL")
    op.alter_column(
        "job_runs",
        "endpoint_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_foreign_key(
        "job_runs_endpoint_id_fkey",
        "job_runs",
        "endpoints",
        ["endpoint_id"],
        ["id"],
        ondelete="RESTRICT",
    )
