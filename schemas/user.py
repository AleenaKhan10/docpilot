from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
import uuid


class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    is_active: Optional[bool] = True


class UserResponse(UserBase):
    id: uuid.UUID
    is_superuser: bool
    created_at: datetime

    class Config:
        from_attributes = True
