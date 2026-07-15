"""add immutable evaluation artifacts

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("sample_kind", sa.String(length=30), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_path"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_evaluation_artifacts_workspace_idempotency_key",
        ),
    )
    op.create_index(
        op.f("ix_evaluation_artifacts_workspace_id"),
        "evaluation_artifacts",
        ["workspace_id"],
        unique=False,
    )
    op.alter_column(
        "runs",
        "dataset_id",
        existing_type=sa.String(length=36),
        nullable=True,
    )
    op.add_column(
        "runs",
        sa.Column("artifact_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_runs_artifact_id_evaluation_artifacts",
        "runs",
        "evaluation_artifacts",
        ["artifact_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_runs_artifact_id"),
        "runs",
        ["artifact_id"],
        unique=True,
    )
    op.create_check_constraint(
        "ck_runs_exactly_one_source",
        "runs",
        "(dataset_id IS NOT NULL AND artifact_id IS NULL) OR "
        "(dataset_id IS NULL AND artifact_id IS NOT NULL)",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(
        sa.text("SELECT 1 FROM runs WHERE artifact_id IS NOT NULL LIMIT 1")
    ).first():
        raise RuntimeError("Cannot downgrade while artifact-backed runs exist")

    op.drop_constraint("ck_runs_exactly_one_source", "runs", type_="check")
    op.drop_index(op.f("ix_runs_artifact_id"), table_name="runs")
    op.drop_constraint(
        "fk_runs_artifact_id_evaluation_artifacts",
        "runs",
        type_="foreignkey",
    )
    op.drop_column("runs", "artifact_id")
    op.alter_column(
        "runs",
        "dataset_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
    op.drop_index(
        op.f("ix_evaluation_artifacts_workspace_id"),
        table_name="evaluation_artifacts",
    )
    op.drop_table("evaluation_artifacts")
