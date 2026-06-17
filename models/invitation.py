from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from db.session import Base


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    org_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invited_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    email = Column(String, nullable=False, index=True)
    role = Column(String(20), default="viewer", nullable=False)

    # Opaque token used in the accept-invite URL. Generated server-side, not guessable.
    token = Column(String(64), unique=True, index=True, nullable=False)

    status = Column(
        String(20), default="pending", nullable=False, index=True
    )  # pending | accepted | expired | revoked

    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    organization = relationship("Organization", back_populates="invitations")
    inviter = relationship("User", foreign_keys=[invited_by])
