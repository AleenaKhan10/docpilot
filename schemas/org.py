from pydantic import BaseModel, EmailStr, Field
from typing import Optional
import uuid
from datetime import datetime


# --- Signup (creates Supabase user + org + membership in one transaction) ---
class SignupOrgRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    organization_name: str = Field(min_length=1, max_length=100)


class SignupOrgResponse(BaseModel):
    user_id: uuid.UUID
    organization_id: uuid.UUID
    email_confirmation_required: bool
    message: str


# --- Organization ---
class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    max_seats: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class OrgWithRoleResponse(OrgResponse):
    role: str  # The caller's role in this org


# --- Members ---
class MemberResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    role: str
    joined_at: datetime

    class Config:
        from_attributes = True


class ChangeRoleRequest(BaseModel):
    role: str  # owner | editor | viewer


# --- Invitations ---
class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "viewer"


class InviteResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class AcceptInviteRequest(BaseModel):
    # If invitee doesn't have a Supabase account yet, they provide these.
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    password: Optional[str] = Field(default=None, min_length=8, max_length=72)
