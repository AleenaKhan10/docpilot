from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

# 1. Base Schema (Common data)
class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    is_active: Optional[bool] = True

# 2. CREATE Request (When User Signs up)
# Requires Password
class UserCreate(UserBase):
    password: str 

# 3. LOGIN Request (When User Logs in)
class UserLogin(BaseModel):
    email: EmailStr
    password: str

# 4. RESPONSE Schema (What we will send to Frontend)
# CRITICAL: This should never have password Field!
class UserResponse(UserBase):
    id: int
    is_superuser: bool
    role: str
    created_at: datetime

    class Config:
        from_attributes = True # ORM mode for SQLAlchemy compatibility