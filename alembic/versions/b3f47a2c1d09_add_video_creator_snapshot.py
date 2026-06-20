"""add video creator snapshot

When a member is removed and that was their last org membership we now
hard-delete the user account (see routes/org.py remove_member). To keep
attribution on the docs they uploaded, we snapshot their name + email
into the video row at deletion time. The video list / detail endpoints
then fall back to these columns when videos.user_id is NULL.

Revision ID: b3f47a2c1d09
Revises: 7d3b9c4e1a02
Create Date: 2026-06-21 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3f47a2c1d09"
down_revision: Union[str, Sequence[str], None] = "7d3b9c4e1a02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("created_by_name", sa.String(), nullable=True),
    )
    op.add_column(
        "videos",
        sa.Column("created_by_email", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("videos", "created_by_email")
    op.drop_column("videos", "created_by_name")
