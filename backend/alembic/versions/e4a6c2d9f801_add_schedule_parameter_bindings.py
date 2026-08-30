"""Add schedule-owned parameter bindings and logical run audit context.

Revision ID: e4a6c2d9f801
Revises: c7e91a4f2d60
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e4a6c2d9f801"
down_revision: str | None = "c7e91a4f2d60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "schedules",
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
    )
    op.add_column(
        "schedules",
        sa.Column(
            "parameter_bindings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "schedules",
        sa.Column(
            "window_config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # Preserve the behavior of existing schedules by copying endpoint defaults
    # into explicit schedule-owned bindings. Any legacy parameter without a
    # resolvable default remains absent and will be reported when the schedule
    # is edited, previewed, or executed rather than silently inventing a value.
    op.execute(
        """
        UPDATE schedules AS schedule
        SET parameter_bindings_json = COALESCE(migrated.bindings, '{}'::jsonb)
        FROM (
            SELECT
                endpoint.id AS endpoint_id,
                jsonb_object_agg(
                    parameter.name,
                    CASE
                        WHEN parameter.descriptor->>'default_expression' = 'today'
                            THEN jsonb_build_object('source', 'run_date')
                        WHEN parameter.descriptor->>'default_expression' = 'yesterday'
                            THEN jsonb_build_object(
                                'source', 'relative_date', 'offset_days', -1
                            )
                        WHEN COALESCE(
                            (parameter.descriptor->>'default_is_null')::boolean,
                            false
                        )
                            THEN jsonb_build_object('source', 'null')
                        WHEN parameter.descriptor ? 'default'
                             AND parameter.descriptor->'default' <> 'null'::jsonb
                            THEN jsonb_build_object(
                                'source', 'literal',
                                'value', parameter.descriptor->'default'
                            )
                        ELSE NULL
                    END
                ) FILTER (
                    WHERE parameter.descriptor->>'default_expression' IN ('today', 'yesterday')
                       OR COALESCE(
                            (parameter.descriptor->>'default_is_null')::boolean,
                            false
                       )
                       OR (
                            parameter.descriptor ? 'default'
                            AND parameter.descriptor->'default' <> 'null'::jsonb
                       )
                ) AS bindings
            FROM endpoints AS endpoint
            CROSS JOIN LATERAL jsonb_each(
                COALESCE(endpoint.param_schema_json, '{}'::jsonb)
            ) AS parameter(name, descriptor)
            GROUP BY endpoint.id
        ) AS migrated
        WHERE schedule.endpoint_id = migrated.endpoint_id
        """
    )

    op.add_column(
        "job_runs",
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("job_runs", sa.Column("logical_date", sa.Date(), nullable=True))
    op.add_column("job_runs", sa.Column("window_start", sa.Date(), nullable=True))
    op.add_column("job_runs", sa.Column("window_end", sa.Date(), nullable=True))
    op.add_column(
        "job_runs",
        sa.Column(
            "resolved_params_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column("job_runs", sa.Column("trigger_source", sa.String(length=20), nullable=True))
    op.add_column("job_runs", sa.Column("binding_hash", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        "uq_job_runs_schedule_scheduled_for",
        "job_runs",
        ["schedule_id", "scheduled_for"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_job_runs_schedule_scheduled_for", "job_runs", type_="unique")
    op.drop_column("job_runs", "binding_hash")
    op.drop_column("job_runs", "trigger_source")
    op.drop_column("job_runs", "resolved_params_json")
    op.drop_column("job_runs", "window_end")
    op.drop_column("job_runs", "window_start")
    op.drop_column("job_runs", "logical_date")
    op.drop_column("job_runs", "scheduled_for")
    op.drop_column("schedules", "window_config_json")
    op.drop_column("schedules", "parameter_bindings_json")
    op.drop_column("schedules", "timezone")
