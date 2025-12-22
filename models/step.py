from sqlalchemy import Column, Integer, String, Text, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db.session import Base

class Step(Base):
    __tablename__ = "steps"

    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign Key matches Video.id (Integer)
    video_id = Column(Integer, ForeignKey("videos.id"), index=True)
    
    # --- Content ---
    step_number = Column(Integer, nullable=False)
    timestamp = Column(Float, nullable=True)
    
    title = Column(String, nullable=True)       # Section Header
    description = Column(Text, nullable=False)  # Action Text
    
    # --- Enterprise Metadata ---
    tip = Column(Text, nullable=True)           # Pro Tip
    url = Column(String, nullable=True)         # Extracted URL
    image_url = Column(String, nullable=True)   # S3 Link / Local Link
    
    # --- Audit ---
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship
    video = relationship("Video", back_populates="steps")