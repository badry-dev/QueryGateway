"""Preserve job runs when deleting schedules.

Revision ID: b2d18f4a6c73
Revises: a8307fb20816
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2d18f4a6c73"
down_revision: str | None = "a8307fb20816"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "job_runs_schedule_id_fkey", "job_runs", type_="foreignkey"
    )
    op.alter_column(
        "job_runs",
        "schedule_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.create_foreign_key(
        "job_runs_schedule_id_fkey",
        "job_runs",
        "schedules",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "job_runs_schedule_id_fkey", "job_runs", type_="foreignkey"
    )
    # Schedules deleted after this migration cannot be reconstructed. Remove
    # only their orphaned audit rows so the original NOT NULL contract can be
    # restored; snapshots remain and their job_run_id becomes NULL.
    op.execute("DELETE FROM job_runs WHERE schedule_id IS NULL")
    op.alter_column(
        "job_runs",
        "schedule_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
    op.create_foreign_key(
        "job_runs_schedule_id_fkey",
        "job_runs",
        "schedules",
        ["schedule_id"],
        ["id"],
        ondelete="RESTRICT",
    )
