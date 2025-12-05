from sqlalchemy import Column, Integer, String, Text, Float, ForeignKey
from sqlalchemy.orm import relationship
from db.session import Base

class Step(Base):
    __tablename__ = "steps"

    id = Column(Integer, primary_key=True, index=True)
    
    # Kaunsi video ka step hai?
    video_id = Column(Integer, ForeignKey("videos.id"))
    
    # Step Number (1, 2, 3...)
    step_number = Column(Integer, nullable=False)
    
    # Video mein kis time par ye step aaya (e.g., 05.4 seconds)
    timestamp = Column(Float, nullable=True)
    
    # AI ka likha hua text
    description = Column(Text, nullable=False)
    
    # Screenshot ka S3 Link
    image_url = Column(String, nullable=True)

    # Relationship
    video = relationship("Video", back_populates="steps")