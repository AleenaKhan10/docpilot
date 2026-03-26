from pydantic import BaseModel, EmailStr
from typing import Optional, List
import uuid
from datetime import datetime

# --- ORGANIZATION SCHEMAS ---
class OrgCreate(BaseModel):
    name: str

class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    is_active: bool
    created_at: datetime
    
    class Config:
        orm_mode = True
        from_attributes = True

# --- MEMBER MANAGEMENT SCHEMAS ---
class MemberResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: Optional[str]
    role: str
    
    class Config:
        orm_mode = True
        from_attributes = True

class ChangeRoleRequest(BaseModel):
    role: str # owner, admin, member, viewer

# --- INVITATION SCHEMAS ---
class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "member"

class InviteResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    status: str
    created_at: datetime
    
    class Config:
        orm_mode = True
        from_attributes = True
