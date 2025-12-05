from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from db.session import Base

# Status ke liye Enum (Dropdown options jaisa)
class ProcessingStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=True)
    video_url = Column(String, nullable=False)  # S3 URL
    
    # Status track karne ke liye (Default: Pending)
    status = Column(String, default=ProcessingStatus.PENDING)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Foreign Key: Yeh video kis user ki hai?
    user_id = Column(Integer, ForeignKey("users.id"))
    
    # Relationships
    owner = relationship("User", back_populates="videos")
    steps = relationship("Step", back_populates="video", cascade="all, delete-orphan")