from sqlalchemy import Boolean, Column, String, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from db.session import Base


class User(Base):
    __tablename__ = "users"

    # UUID matches the Supabase auth.users.id (the JWT 'sub' claim)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    full_name = Column(String, index=True)
    email = Column(String, unique=True, index=True, nullable=False)

    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Multi-org: a user can be a member of many organizations via Membership
    memberships = relationship(
        "Membership", back_populates="user", cascade="all, delete-orphan"
    )
    # NOTE: no cascade delete here on purpose. When a user is removed from
    # their last org we keep their uploaded docs alive (with user_id nulled
    # out) so the org doesn't lose documentation just because the author
    # left. routes/org.py:remove_member is responsible for the nulling.
    videos = relationship("Video", back_populates="owner")
