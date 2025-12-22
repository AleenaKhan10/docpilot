from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# 1. Step design (Inside List)
class StepResponse(BaseModel):
    step_number: int
    timestamp: float  # <--- float
    description: str
    image_url: str  # Public URL

    class Config:
        from_attributes = True

# 2. Video Design (Main packet)
class VideoResponse(BaseModel):
    id: int
    title: str
    status: str
    pdf_url: Optional[str] = None # PDF link (Optional, Not in Start)
    created_at: datetime
    steps: List[StepResponse] = [] # List of steps

    class Config:
        from_attributes = True