from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from db.session import Base


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # --- Who is invited and where ---
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    invited_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    email = Column(String, nullable=False, index=True)         # Invitee's email
    role = Column(String(20), default="member", nullable=False) # Role to assign on acceptance
    
    # --- Status ---
    status = Column(String(20), default="pending", nullable=False, index=True)  # pending | accepted | expired
    
    # --- Timing ---
    expires_at = Column(DateTime(timezone=True), nullable=True)  # Auto-expire old invites
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Relationships ---
    organization = relationship("Organization", back_populates="invitations")
    inviter = relationship("User", foreign_keys=[invited_by])
