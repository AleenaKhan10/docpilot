import secrets
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.session import get_db
from core.config import settings
from core.logger import setup_logging
from core.supabase_admin import supabase_admin
from services.email_service import send_invite_email
from models.user import User
from models.organization import Organization
from models.membership import Membership
from models.invitation import Invitation
from api.debs import RequireRole, OrgContext, require_user
from schemas.org import (
    InviteRequest,
    InviteResponse,
    AcceptInviteRequest,
    OrgWithRoleResponse,
)

logger = setup_logging()
router = APIRouter()

INVITE_TTL_DAYS = 7


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- 1. SEND INVITE (owner only) ---
@router.post("/", response_model=InviteResponse)
def create_invitation(
    payload: InviteRequest,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(RequireRole(["owner", "admin"])),
):
    # Admin can invite anyone except an owner; owner can invite any role.
    allowed = ("admin", "editor", "viewer") if ctx.is_owner else ("editor", "viewer")
    if payload.role not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invite role must be one of: {list(allowed)}.",
        )

    email = payload.email.lower().strip()
    org = ctx.organization

    # Seat limit check (counts current members + outstanding pending invites).
    member_count = (
        db.query(Membership).filter(Membership.org_id == org.id).count()
    )
    pending_count = (
        db.query(Invitation)
        .filter(Invitation.org_id == org.id, Invitation.status == "pending")
        .count()
    )
    if member_count + pending_count >= org.max_seats:
        raise HTTPException(
            status_code=400,
            detail=f"Seat limit reached ({org.max_seats}). Remove members or pending invites first.",
        )

    # If the email is already a member of THIS org, block.
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        already = (
            db.query(Membership)
            .filter(
                Membership.user_id == existing_user.id,
                Membership.org_id == org.id,
            )
            .first()
        )
        if already:
            raise HTTPException(
                status_code=400,
                detail="That user is already a member of this organization.",
            )

    # Reuse an existing pending invite for the same email if present (resend).
    existing_invite = (
        db.query(Invitation)
        .filter(
            Invitation.org_id == org.id,
            Invitation.email == email,
            Invitation.status == "pending",
        )
        .first()
    )

    if existing_invite:
        existing_invite.expires_at = _now() + timedelta(days=INVITE_TTL_DAYS)
        existing_invite.role = payload.role
        invite = existing_invite
    else:
        invite = Invitation(
            org_id=org.id,
            invited_by=ctx.user.id,
            email=email,
            role=payload.role,
            token=_generate_token(),
            status="pending",
            expires_at=_now() + timedelta(days=INVITE_TTL_DAYS),
        )
        db.add(invite)
    db.commit()
    db.refresh(invite)

    # Send the email. Two paths:
    #   - Brand-new users: Supabase invite_user_by_email creates the auth.users
    #     row AND sends a magic-link signup email. With Supabase's SMTP now
    #     pointed at Resend, that email flows through our verified domain.
    #   - Existing users: Supabase has no built-in for this — we send the
    #     accept-invite URL through Resend directly.
    accept_url = f"{settings.APP_BASE_URL}/accept-invite/{invite.token}"
    inviter_name = (ctx.user.full_name or ctx.user.email or "").strip() or None
    try:
        if not existing_user:
            supabase_admin.auth.admin.invite_user_by_email(
                email,
                {"redirect_to": accept_url},
            )
        else:
            send_invite_email(
                to_email=email,
                organization_name=org.name,
                role=payload.role,
                inviter_name=inviter_name,
                accept_url=accept_url,
                is_existing_user=True,
            )
    except Exception as e:
        logger.warning(f"Invite email failed for {email}: {e}")
        # We don't fail the call — the invitation row exists and the URL can be
        # shared manually from the API response.

    return invite


# --- 2. LIST PENDING INVITES (owner OR admin) ---
@router.get("/", response_model=list[InviteResponse])
def list_invitations(
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(RequireRole(["owner", "admin"])),
):
    rows = (
        db.query(Invitation)
        .filter(
            Invitation.org_id == ctx.organization.id,
            Invitation.status == "pending",
        )
        .order_by(Invitation.created_at.desc())
        .all()
    )
    return rows


# --- 3. REVOKE INVITE (owner OR admin) ---
@router.delete("/{invitation_id}")
def revoke_invitation(
    invitation_id: str,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(RequireRole(["owner", "admin"])),
):
    invite = (
        db.query(Invitation)
        .filter(
            Invitation.id == invitation_id,
            Invitation.org_id == ctx.organization.id,
        )
        .first()
    )
    if not invite:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    if invite.status != "pending":
        raise HTTPException(status_code=400, detail="Invitation is not pending.")
    invite.status = "revoked"
    db.commit()
    return {"message": "Invitation revoked."}


# --- 4. PEEK AT TOKEN (public — used by the accept-invite page to render org name) ---
@router.get("/by-token/{token}")
def peek_invitation(token: str, db: Session = Depends(get_db)):
    invite = db.query(Invitation).filter(Invitation.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    if invite.status != "pending":
        raise HTTPException(status_code=410, detail=f"Invitation is {invite.status}.")
    if invite.expires_at < _now():
        invite.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="Invitation has expired.")

    org = db.query(Organization).filter(Organization.id == invite.org_id).first()
    existing_user = (
        db.query(User).filter(User.email == invite.email).first() is not None
    )
    return {
        "email": invite.email,
        "role": invite.role,
        "organization_name": org.name if org else "",
        "existing_user": existing_user,
    }


# --- 5. ACCEPT (authed: user has already signed in or just signed up) ---
@router.post("/{token}/accept", response_model=OrgWithRoleResponse)
def accept_invitation(
    token: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    invite = db.query(Invitation).filter(Invitation.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    if invite.status != "pending":
        raise HTTPException(status_code=410, detail=f"Invitation is {invite.status}.")
    if invite.expires_at < _now():
        invite.status = "expired"
        db.commit()
        raise HTTPException(status_code=410, detail="Invitation has expired.")

    # The logged-in user's email must match the invited email.
    if user.email.lower() != invite.email.lower():
        raise HTTPException(
            status_code=403,
            detail="This invitation was sent to a different email.",
        )

    # Already a member? Just mark accepted and return.
    existing_membership = (
        db.query(Membership)
        .filter(
            Membership.user_id == user.id,
            Membership.org_id == invite.org_id,
        )
        .first()
    )
    if existing_membership:
        invite.status = "accepted"
        invite.accepted_at = _now()
        db.commit()
        org = db.query(Organization).filter(Organization.id == invite.org_id).first()
        return OrgWithRoleResponse(
            id=org.id,
            name=org.name,
            slug=org.slug,
            plan=org.plan,
            max_seats=org.max_seats,
            is_active=org.is_active,
            created_at=org.created_at,
            role=existing_membership.role,
        )

    # Seat check at accept-time too (another invite might have been redeemed in
    # the meantime).
    org = db.query(Organization).filter(Organization.id == invite.org_id).first()
    if not org or not org.is_active:
        raise HTTPException(status_code=404, detail="Organization no longer exists.")
    member_count = (
        db.query(Membership).filter(Membership.org_id == org.id).count()
    )
    if member_count >= org.max_seats:
        raise HTTPException(
            status_code=400,
            detail="Organization is at its seat limit.",
        )

    membership = Membership(user_id=user.id, org_id=org.id, role=invite.role)
    db.add(membership)
    invite.status = "accepted"
    invite.accepted_at = _now()
    db.commit()
    db.refresh(membership)

    return OrgWithRoleResponse(
        id=org.id,
        name=org.name,
        slug=org.slug,
        plan=org.plan,
        max_seats=org.max_seats,
        is_active=org.is_active,
        created_at=org.created_at,
        role=membership.role,
    )
