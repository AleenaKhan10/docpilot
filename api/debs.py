from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials # For Bearer Token
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from core.config import settings
from db.session import get_db
from models.user import User
import uuid


security = HTTPBearer()

def get_current_user(
    token_obj: HTTPAuthorizationCredentials = Depends(security), 
    db: Session = Depends(get_db)
) -> User:
    """
    Supabase Auth Guard with Simple Bearer Token Support.
    """
    
    # Extract token string from the object
    token = token_obj.credentials 
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # --- 1. VERIFY TOKEN SIGNATURE ---
        payload = jwt.decode(
            token, 
            settings.SUPABASE_JWT_SECRET, 
            algorithms=[settings.ALGORITHM],
            options={"verify_aud": False}
        )
        
        # --- 2. EXTRACT USER ID (UUID) ---
        user_id: str = payload.get("sub")
        
        if user_id is None:
            raise credentials_exception
            
    except JWTError as e:
        print(f"JWT Error: {e}")
        raise credentials_exception
    
    # --- 3. FETCH USER FROM DB ---
    try:
        user_uuid = uuid.UUID(user_id)
        user = db.query(User).filter(User.id == user_uuid).first()
    except ValueError:
        raise credentials_exception
        
    if user is None:
        raise HTTPException(status_code=404, detail="User not found (Sync Issue)")
        
    return user


# --- MULTI-TENANCY GUARDS ---

def require_org(current_user: User = Depends(get_current_user)) -> User:
    """
    Guard: Ensures the user belongs to an organization.
    Use this for routes that require org context (like uploading a video).
    """
    if not current_user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="You must belong to an organization to perform this action."
        )
    return current_user

class RequireRole:
    """
    Dependency factory for RBAC (Role-Based Access Control).
    Usage: Depends(RequireRole(["owner", "admin"]))
    """
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: User = Depends(require_org)) -> User:
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Requires one of: {', '.join(self.allowed_roles)}."
            )
        return current_user