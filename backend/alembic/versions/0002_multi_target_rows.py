"""one processing row per (Excel row, destination platform)

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("processing_rows", schema=None) as batch_op:
        batch_op.add_column(sa.Column("target_platform", sa.String(length=16), nullable=True))
        batch_op.drop_constraint("uq_row_job_original_row", type_="unique")
        batch_op.create_unique_constraint(
            "uq_row_job_original_row", ["job_id", "original_row", "target_platform"]
        )


def downgrade() -> None:
    with op.batch_alter_table("processing_rows", schema=None) as batch_op:
        batch_op.drop_constraint("uq_row_job_original_row", type_="unique")
        batch_op.create_unique_constraint("uq_row_job_original_row", ["job_id", "original_row"])
        batch_op.drop_column("target_platform")
