"""add run result extension fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run_results",
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "run_results",
        sa.Column(
            "usage",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "run_results",
        sa.Column("estimated_cost", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("run_results", "estimated_cost")
    op.drop_column("run_results", "usage")
    op.drop_column("run_results", "details")
