from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class StepResponse(BaseModel):
    step_number: int
    timestamp: Optional[float] = 0.0
    title: Optional[str] = None
    description: str

    # Section / structural hints
    section_summary: Optional[str] = None

    # Inline annotations
    tip: Optional[str] = None
    note: Optional[str] = None
    explanation: Optional[str] = None
    url: Optional[str] = None
    image_url: Optional[str] = None

    class Config:
        from_attributes = True


class VideoResponse(BaseModel):
    id: int
    title: str
    status: str
    output_type: Optional[str] = "sop"
    user_context: Optional[str] = None
    pdf_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Display name of the user who uploaded this doc (full_name with
    # email fallback). Resolved server-side so the frontend can render
    # without an extra round-trip per row.
    created_by: Optional[str] = None
    # Rich editorial document from the two-pass synthesis. Frontend
    # prefers this over the flat steps when present.
    document_json: Optional[dict] = None
    steps: List[StepResponse] = []
    # The viewer's effective access on this doc. Populated by the API based
    # on org role + doc ownership + explicit grants. Drives Edit/Share
    # button visibility on the frontend.
    your_access: Optional[str] = None  # "owner" | "edit" | "view"

    class Config:
        from_attributes = True
