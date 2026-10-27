"""the current channel name a user typed in the sheet's renamed_to column

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("processing_rows", schema=None) as batch_op:
        batch_op.add_column(sa.Column("renamed_to", sa.String(length=512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("processing_rows", schema=None) as batch_op:
        batch_op.drop_column("renamed_to")
