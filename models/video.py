from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID # <--- Imported UUID
import enum
from db.session import Base

class ProcessingStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class Video(Base):
    __tablename__ = "videos"

    # Video ID Integer  (URL Friendly)
    id = Column(Integer, primary_key=True, index=True)
    
    title = Column(String, index=True, nullable=True)
    video_url = Column(String, nullable=False)  # S3 URL
    status = Column(String, default=ProcessingStatus.PENDING.value, index=True)
    
    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # --- CRITICAL CHANGE ---
    # User ID must match User.id type (UUID)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id")) 
    
    # Relationships
    owner = relationship("User", back_populates="videos")
    steps = relationship("Step", back_populates="video", cascade="all, delete-orphan")