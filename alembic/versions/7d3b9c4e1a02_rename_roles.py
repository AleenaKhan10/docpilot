"""rename_roles

Org-level role taxonomy is being renamed:
  editor -> member
  viewer -> guest

This migrates existing rows in `memberships` and `invitations` to the
new vocabulary. Per-doc share grants in `video_access` use a different
column (`edit` / `view`) and are NOT touched.

Revision ID: 7d3b9c4e1a02
Revises: a028ec6e70a2
Create Date: 2026-06-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '7d3b9c4e1a02'
down_revision: Union[str, Sequence[str], None] = 'a028ec6e70a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE memberships SET role = 'member' WHERE role = 'editor'")
    op.execute("UPDATE memberships SET role = 'guest'  WHERE role = 'viewer'")
    op.execute("UPDATE invitations SET role = 'member' WHERE role = 'editor'")
    op.execute("UPDATE invitations SET role = 'guest'  WHERE role = 'viewer'")


def downgrade() -> None:
    op.execute("UPDATE invitations SET role = 'viewer' WHERE role = 'guest'")
    op.execute("UPDATE invitations SET role = 'editor' WHERE role = 'member'")
    op.execute("UPDATE memberships SET role = 'viewer' WHERE role = 'guest'")
    op.execute("UPDATE memberships SET role = 'editor' WHERE role = 'member'")
