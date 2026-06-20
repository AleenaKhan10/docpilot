import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session
from typing import List

from core.logger import setup_logging
from core.supabase_admin import supabase_admin
from db.session import get_db
from models.user import User
from models.organization import Organization
from models.membership import Membership
from models.video import Video
from models.video_access import VideoAccess
from models.video_share import VideoShare
from models.invitation import Invitation
from api.debs import (
    require_user,
    require_org_member,
    RequireRole,
    OrgContext,
    VALID_ROLES,
    role_rank,
)

logger = setup_logging()
from schemas.org import (
    OrgCreate,
    OrgResponse,
    OrgWithRoleResponse,
    MemberResponse,
    ChangeRoleRequest,
)
from utils.slug import make_org_slug

router = APIRouter()


# --- LIST MY ORGS (no X-Org-Id needed; org switcher uses this) ---
@router.get("/mine", response_model=List[OrgWithRoleResponse])
def list_my_orgs(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    rows = (
        db.query(Membership, Organization)
        .join(Organization, Membership.org_id == Organization.id)
        .filter(Membership.user_id == user.id, Organization.is_active == True)
        .order_by(Organization.created_at.asc())
        .all()
    )
    return [
        OrgWithRoleResponse(
            id=org.id,
            name=org.name,
            slug=org.slug,
            plan=org.plan,
            max_seats=org.max_seats,
            is_active=org.is_active,
            created_at=org.created_at,
            role=m.role,
        )
        for (m, org) in rows
    ]


# --- CREATE ADDITIONAL ORG (existing user, becomes owner) ---
@router.post("/", response_model=OrgWithRoleResponse)
def create_org(
    payload: OrgCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    org = Organization(
        name=payload.name,
        slug=make_org_slug(payload.name),
        plan="free",
        max_seats=10,
    )
    db.add(org)
    db.flush()
    membership = Membership(user_id=user.id, org_id=org.id, role="owner")
    db.add(membership)
    db.commit()
    db.refresh(org)
    return OrgWithRoleResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        plan=org.plan,
        max_seats=org.max_seats,
        is_active=org.is_active,
        created_at=org.created_at,
        role="owner",
    )


# --- CURRENT ORG DETAILS ---
@router.get("/", response_model=OrgWithRoleResponse)
def get_current_org(ctx: OrgContext = Depends(require_org_member)):
    org = ctx.organization
    return OrgWithRoleResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        plan=org.plan,
        max_seats=org.max_seats,
        is_active=org.is_active,
        created_at=org.created_at,
        role=ctx.role,
    )


# --- LIST MEMBERS ---
@router.get("/members", response_model=List[MemberResponse])
def list_members(
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_member),
):
    rows = (
        db.query(Membership, User)
        .join(User, Membership.user_id == User.id)
        .filter(Membership.org_id == ctx.organization.id)
        .order_by(Membership.created_at.asc())
        .all()
    )
    return [
        MemberResponse(
            user_id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=m.role,
            joined_at=m.created_at,
        )
        for (m, u) in rows
    ]


# --- CHANGE MEMBER ROLE (owner OR admin; admin cannot touch peers/superiors) ---
@router.put("/members/{user_id}/role")
def change_member_role(
    user_id: uuid.UUID,
    payload: ChangeRoleRequest,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(RequireRole(["owner", "admin"])),
):
    if payload.role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Allowed: {list(VALID_ROLES)}.",
        )

    target = (
        db.query(Membership)
        .filter(
            Membership.org_id == ctx.organization.id,
            Membership.user_id == user_id,
        )
        .first()
    )
    if not target:
        raise HTTPException(
            status_code=404, detail="Member not found in this organization."
        )

    caller_rank = role_rank(ctx.role)
    target_rank = role_rank(target.role)
    new_rank = role_rank(payload.role)

    # Admins can only act on roles BELOW their own rank, and can't promote
    # anyone to a rank ≥ their own. Only owners can mint owners or admins.
    if not ctx.is_owner:
        if target_rank >= caller_rank:
            raise HTTPException(
                status_code=403,
                detail="You can only change roles for members below your own level.",
            )
        if new_rank >= caller_rank:
            raise HTTPException(
                status_code=403,
                detail="You cannot promote a member to your own role or higher.",
            )

    # Don't demote the last owner.
    if target.role == "owner" and payload.role != "owner":
        owner_count = (
            db.query(Membership)
            .filter(
                Membership.org_id == ctx.organization.id,
                Membership.role == "owner",
            )
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot demote the last owner. Promote someone else first.",
            )

    target.role = payload.role
    db.commit()
    return {"message": f"Role updated to {payload.role}."}


# --- REMOVE MEMBER (owner OR admin; admin can't remove peers/superiors) ---
@router.delete("/members/{user_id}")
def remove_member(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(RequireRole(["owner", "admin"])),
):
    """
    Remove a member from this organization. If this was their only
    membership, the user account is fully deleted (public.users +
    Supabase auth.users) so a future invite goes through fresh signup.

    Docs they uploaded survive — videos.user_id is nulled out so the
    org keeps the documentation; the UI then renders "Created by —".
    """
    target = (
        db.query(Membership)
        .filter(
            Membership.org_id == ctx.organization.id,
            Membership.user_id == user_id,
        )
        .first()
    )
    if not target:
        raise HTTPException(status_code=404, detail="Member not found.")

    if not ctx.is_owner and role_rank(target.role) >= role_rank(ctx.role):
        raise HTTPException(
            status_code=403,
            detail="You can only remove members below your own level.",
        )

    if target.role == "owner":
        owner_count = (
            db.query(Membership)
            .filter(
                Membership.org_id == ctx.organization.id,
                Membership.role == "owner",
            )
            .count()
        )
        if owner_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last owner.",
            )

    # Detach the removed user from any docs they uploaded in THIS org —
    # docs survive, attribution becomes "—". Done via raw UPDATE to bypass
    # the User.videos ORM relationship cascade.
    db.execute(
        update(Video)
        .where(Video.user_id == user_id, Video.org_id == ctx.organization.id)
        .values(user_id=None)
    )

    db.delete(target)
    db.flush()

    other_memberships = (
        db.query(Membership).filter(Membership.user_id == user_id).count()
    )

    if other_memberships == 0:
        # Last org — wipe the account entirely. Reassign non-nullable FKs
        # pointing at this user to the admin doing the removal so history
        # rows (sent invites, granted access) survive. video_access.user_id
        # rows TO this user cascade-delete via the FK ondelete=CASCADE.
        db.execute(
            update(Video).where(Video.user_id == user_id).values(user_id=None)
        )
        db.execute(
            update(Invitation)
            .where(Invitation.invited_by == user_id)
            .values(invited_by=ctx.user.id)
        )
        db.execute(
            update(VideoAccess)
            .where(VideoAccess.granted_by == user_id)
            .values(granted_by=ctx.user.id)
        )
        db.execute(
            update(VideoShare)
            .where(VideoShare.created_by == user_id)
            .values(created_by=ctx.user.id)
        )

        target_user = db.query(User).filter(User.id == user_id).first()
        if target_user:
            # Revoke any pending invites still addressed to this email so
            # the row is reusable without a stale invite linking to the
            # account we just nuked.
            db.query(Invitation).filter(
                Invitation.email == target_user.email,
                Invitation.status == "pending",
            ).update({Invitation.status: "revoked"})
            db.delete(target_user)

        db.commit()

        # Supabase auth delete is best-effort — if it fails the user might
        # be able to log in again, but require_user would auto-provision a
        # fresh public.users row (no memberships → they see "no
        # organization" UI). Better degraded state than a half-committed
        # transaction.
        try:
            supabase_admin.auth.admin.delete_user(str(user_id))
        except Exception as e:
            logger.warning(
                f"Removed last membership for user {user_id} but Supabase "
                f"auth delete failed: {e}"
            )

        return {"message": "Member removed and user account deleted."}

    db.commit()
    return {"message": "Member removed from organization."}
