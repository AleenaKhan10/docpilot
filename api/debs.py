from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials # For Bearer Token
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from core.config import settings
from db.session import get_db
from models.user import User
import uuid

# Change 1: Use HTTPBearer instead of OAuth2PasswordBearer
# It will show simple token box in Swagger
security = HTTPBearer()

def get_current_user(
    token_obj: HTTPAuthorizationCredentials = Depends(security), # <--- CHANGED
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