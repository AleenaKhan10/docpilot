"""baseline — captures the schema state at Alembic adoption time

Revision ID: cfd712450e51
Revises:
Create Date: 2026-06-17 00:21:16

The DB already contains every table we need at this point (created via
`Base.metadata.create_all` + the lifespan schema shims that added
worker_heartbeat_at, document_json, user_context, output_type). This
migration is intentionally empty — it exists as a checkpoint so future
revisions chain from a known revision id.

To bring an existing DB up to this point:
    alembic stamp head

Future schema changes:
    1. Edit the SQLAlchemy model
    2. alembic revision --autogenerate -m "describe the change"
    3. Review the generated migration
    4. alembic upgrade head
"""

from typing import Sequence, Union

revision: str = "cfd712450e51"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
