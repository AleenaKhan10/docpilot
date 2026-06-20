from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID, JSONB
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

    # Heartbeat from the Celery worker. Refreshed at every progress broadcast.
    # The lifespan reaper only marks a video as `failed` if status=processing
    # AND this is NULL or older than HEARTBEAT_STALE_SECONDS.
    worker_heartbeat_at = Column(DateTime(timezone=True), nullable=True)

    # Editorial output from Pass 2 — a Document {title, summary, output_type,
    # sections:[{heading,intro,blocks:[...]}]} matching the frontend renderer's
    # schema. Stored verbatim; the API translates frame_id references inside
    # image blocks into signed URLs when serving. JSONB so we can index +
    # query inside the document later (e.g. filter docs by output_type).
    document_json = Column(JSONB, nullable=True)

    # Supabase Storage key for the generated PDF, if uploaded. When NULL,
    # the local `temp_data/{id}/manual.pdf` is used (legacy path).
    pdf_storage_path = Column(String, nullable=True)

    # JSON mapping {frame_id: storage_key} for frames referenced in the
    # document. NULL or missing keys fall back to the local temp_data path.
    frame_storage_paths = Column(JSONB, nullable=True)

    # User-supplied "context" from the upload form (audience, tone, anything
    # the AI should know). Optional, free-text. Passed to Pass 2.
    user_context = Column(Text, nullable=True)

    # User's chosen output type at upload time ("sop", "training", "bug_report",
    # etc.). Default "sop". Drives Pass 2 prompt branching.
    output_type = Column(
        String(32), nullable=False, default="sop", server_default="sop"
    )
    
    # --- Multi-Tenancy (Data Isolation) ---
    # Which organization owns this video?
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True, index=True)
    
    # Who uploaded it?
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))

    # Snapshot of the uploader's display info captured when their user
    # account is deleted (routes/org.py:remove_member). user_id is nulled
    # out at the same time. Read by the video list/detail endpoints to
    # render "Created by X (former member)" so attribution survives the
    # author's departure.
    created_by_name = Column(String, nullable=True)
    created_by_email = Column(String, nullable=True)
    
    # Relationships
    owner = relationship("User", back_populates="videos")
    organization = relationship("Organization", back_populates="videos")
    steps = relationship("Step", back_populates="video", cascade="all, delete-orphan")
    share = relationship(
        "VideoShare",
        back_populates="video",
        uselist=False,
        cascade="all, delete-orphan",
    )
    access_grants = relationship(
        "VideoAccess",
        back_populates="video",
        cascade="all, delete-orphan",
    )