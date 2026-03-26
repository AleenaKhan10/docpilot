from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from db.session import Base


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # --- Identity ---
    name = Column(String(100), nullable=False)                  # "LexumSoft"
    slug = Column(String(100), unique=True, index=True, nullable=False)  # "lexumsoft" (URL-friendly)
    
    # --- Plan & Status ---
    plan = Column(String(20), default="free", nullable=False)   # free | pro | enterprise
    is_active = Column(Boolean, default=True)
    
    # --- Audit ---
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- Relationships ---
    members = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    videos = relationship("Video", back_populates="organization", cascade="all, delete-orphan")
    invitations = relationship("Invitation", back_populates="organization", cascade="all, delete-orphan")
