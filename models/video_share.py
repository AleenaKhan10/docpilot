"""
VideoShare: a single public share link per video.

Anyone with the token can view the doc read-only, no auth required. The
doc owner (uploader) or the org owner can create, refresh, or revoke the
link. We keep one row per video (uq constraint on video_id) so refreshing
generates a new token but a video can never have two competing share URLs.
"""

import uuid
from sqlalchemy import (
    Boolean,
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


class VideoShare(Base):
    __tablename__ = "video_shares"
    __table_args__ = (UniqueConstraint("video_id", name="uq_video_share_video"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    video_id = Column(
        Integer,
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Opaque URL-safe token (32 random bytes → 43-char base64url). Indexed
    # for the public lookup route.
    token = Column(String(64), unique=True, index=True, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    video = relationship("Video", back_populates="share")
    creator = relationship("User", foreign_keys=[created_by])
