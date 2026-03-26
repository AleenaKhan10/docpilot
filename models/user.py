from sqlalchemy import Boolean, Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID  # SPECIAL IMPORT FOR SUPABASE
import uuid
from db.session import Base

class User(Base):
    __tablename__ = "users"

    # 1. ID ab UUID hai (Supabase se match karne ke liye)
    # Now ID is UUID (For Matching with Supabase, Supabase doesn't allow ID.)
    # UUID=TRUE means python will treat is an object
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    full_name = Column(String, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    
    # 2. PASSWORD REMOVED (Supabase handles security) ❌
    
    # --- Multi-Tenancy ---
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True, index=True)
    
    # --- Enterprise Access Control ---
    is_active = Column(Boolean, default=True) 
    is_superuser = Column(Boolean, default=False)  # Platform admin (developer)
    role = Column(String, default="member")        # Org role: owner, admin, member, viewer
    
    # --- Audit Fields ---
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # --- Relationships ---
    organization = relationship("Organization", back_populates="members")
    videos = relationship("Video", back_populates="owner", cascade="all, delete-orphan")