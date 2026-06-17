"""
VideoAccess: per-document Edit / View grants.

Layered on top of the org-level roles:
  - Org owner always has full access (super admin).
  - Doc owner (uploader) always has full access.
  - Anyone else needs an explicit row here.

One (video_id, user_id) pair = one row. Upserting on a duplicate key
replaces the access level. Both granted_by and granted_at are kept for
audit even though we don't expose them in the UI yet.
"""

import uuid
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db.session import Base


class VideoAccess(Base):
    __tablename__ = "video_access"
    __table_args__ = (
        UniqueConstraint("video_id", "user_id", name="uq_video_access_user"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    video_id = Column(
        Integer,
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # "edit" or "view". Editors can also view.
    access = Column(String(8), nullable=False)

    granted_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    granted_at = Column(DateTime(timezone=True), server_default=func.now())

    video = relationship("Video", back_populates="access_grants")
    user = relationship("User", foreign_keys=[user_id])
    granter = relationship("User", foreign_keys=[granted_by])
