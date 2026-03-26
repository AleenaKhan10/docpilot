import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from db.session import get_db
from models.user import User
from models.organization import Organization
from models.invitation import Invitation
from schemas.org import OrgCreate, OrgResponse, InviteRequest, InviteResponse, MemberResponse, ChangeRoleRequest
from api.debs import get_current_user, require_org, RequireRole

router = APIRouter()

# --- 1. CREATE ORGANIZATION ---
@router.post("/", response_model=OrgResponse)
def create_organization(
    org_in: OrgCreate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """
    Create a new organization. 
    The user who creates it automatically becomes the 'owner'.
    """
    if current_user.org_id:
        raise HTTPException(status_code=400, detail="User already belongs to an organization.")
        
    # Generate URL-friendly slug
    base_slug = org_in.name.lower().replace(" ", "-")
    unique_slug = f"{base_slug}-{str(uuid.uuid4())[:8]}"
    
    # 1. Create Org
    new_org = Organization(
        name=org_in.name,
        slug=unique_slug,
        plan="free"
    )
    db.add(new_org)
    db.commit()
    db.refresh(new_org)
    
    # 2. Assign User to Org as Owner
    current_user.org_id = new_org.id
    current_user.role = "owner"
    db.commit()
    
    return new_org

# --- 2. GET MY ORGANIZATION ---
@router.get("/", response_model=OrgResponse)
def get_my_organization(
    db: Session = Depends(get_db), 
    current_user: User = Depends(require_org)
):
    """Get details of the user's current organization."""
    org = db.query(Organization).filter(Organization.id == current_user.org_id).first()
    return org

# --- 3. GET MEMBERS ---
@router.get("/members", response_model=List[MemberResponse])
def get_org_members(
    db: Session = Depends(get_db), 
    current_user: User = Depends(require_org)
):
    """List all members in the organization. Any member can view this."""
    members = db.query(User).filter(User.org_id == current_user.org_id).all()
    return members

# --- 4. INVITE USER ---
@router.post("/invite", response_model=InviteResponse)
def invite_user(
    invite_in: InviteRequest,
    db: Session = Depends(get_db),
    # ONLY owner or admin can invite 👮‍♂️
    current_user: User = Depends(RequireRole(["owner", "admin"])) 
):
    """Invite a new user to the organization by email."""
    # Check if user already exists in system
    existing_user = db.query(User).filter(User.email == invite_in.email).first()
    if existing_user and existing_user.org_id:
        raise HTTPException(status_code=400, detail="User already belongs to an organization.")
        
    # Check for pending invite
    existing_invite = db.query(Invitation).filter(
        Invitation.email == invite_in.email, 
        Invitation.status == "pending"
    ).first()
    
    if existing_invite:
        raise HTTPException(status_code=400, detail="Invitation already sent to this email.")

    new_invite = Invitation(
        org_id=current_user.org_id,
        invited_by=current_user.id,
        email=invite_in.email,
        role=invite_in.role
    )
    db.add(new_invite)
    db.commit()
    db.refresh(new_invite)
    
    # TODO: Send Email using SendGrid/Postmark here
    
    return new_invite

# --- 5. CHANGE MEMBER ROLE ---
@router.put("/members/{user_id}/role")
def change_member_role(
    user_id: uuid.UUID,
    role_in: ChangeRoleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(RequireRole(["owner", "admin"]))
):
    """Change the role of an existing member."""
    if role_in.role not in ["owner", "admin", "member", "viewer"]:
        raise HTTPException(status_code=400, detail="Invalid role")
        
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # SECURITY: Ensure target user is in the same org
    if target_user.org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="User not in your organization")
        
    # SECURITY: Only owners can make someone else an owner
    if role_in.role == "owner" and current_user.role != "owner":
        raise HTTPException(status_code=403, detail="Only owners can promote to owner")
        
    # SECURITY: Cannot demote the ONLY owner
    if target_user.role == "owner" and role_in.role != "owner":
        owner_count = db.query(User).filter(
            User.org_id == current_user.org_id, 
            User.role == "owner"
        ).count()
        if owner_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot demote the last owner of the organization")
            
    target_user.role = role_in.role
    db.commit()
    
    return {"message": f"Successfully updated role to {role_in.role}"}

# --- 6. REMOVE MEMBER ---
@router.delete("/members/{user_id}")
def remove_member(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(RequireRole(["owner", "admin"]))
):
    """Remove a user from the organization."""
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if target_user.org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="User not in your organization")
        
    if target_user.role == "owner" and current_user.id != target_user.id:
         raise HTTPException(status_code=403, detail="Cannot remove an owner. They must step down first.")

    # Remove from org (Nullify org_id)
    target_user.org_id = None
    target_user.role = "member"  # Reset role
    db.commit()
    
    return {"message": "User removed from organization"}
