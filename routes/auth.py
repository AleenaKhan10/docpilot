from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from db.session import get_db
from core.limiter import limiter
from core.logger import setup_logging
from core.supabase_admin import supabase_admin
from models.user import User
from models.organization import Organization
from models.membership import Membership
from schemas.org import SignupOrgRequest, SignupOrgResponse
from utils.slug import make_org_slug

logger = setup_logging()
router = APIRouter()


@router.post("/signup-org", response_model=SignupOrgResponse)
@limiter.limit("5/minute")
def signup_org(
    request: Request,
    payload: SignupOrgRequest,
    db: Session = Depends(get_db),
):
    """
    Create a Supabase auth user + organization + owner membership in one transaction.

    With confirm-email ON, the Supabase invite/signup email is dispatched by Supabase.
    The user must click the confirmation link before they can log in.
    """
    email = payload.email.lower().strip()

    # 1. Ensure no public.users row already (defensive — race with manual signup).
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="An account with this email already exists. Log in to create another organization.",
        )

    # 2. Create the Supabase auth user.
    # email_confirm=True skips the confirmation email entirely and marks the
    # user as confirmed at creation. Flip to False (and update the response
    # message + frontend) when Supabase email delivery is set up.
    try:
        created = supabase_admin.auth.admin.create_user(
            {
                "email": email,
                "password": payload.password,
                "email_confirm": True,
                "user_metadata": {"full_name": payload.full_name},
            }
        )
    except Exception as e:
        msg = str(e)
        logger.warning(f"Supabase admin.create_user failed: {msg}")
        if "already been registered" in msg.lower() or "already exists" in msg.lower():
            raise HTTPException(status_code=400, detail="Email is already registered.")
        raise HTTPException(status_code=502, detail="Failed to create user.")

    auth_user = getattr(created, "user", None)
    if not auth_user or not getattr(auth_user, "id", None):
        raise HTTPException(status_code=502, detail="Supabase did not return a user.")

    auth_user_id = auth_user.id

    # 3. Create org + public.users + owner membership in one commit.
    try:
        org = Organization(
            name=payload.organization_name,
            slug=make_org_slug(payload.organization_name),
            plan="free",
            max_seats=10,
        )
        user = User(
            id=auth_user_id,
            email=email,
            full_name=payload.full_name,
        )
        db.add(org)
        db.add(user)
        db.flush()  # get org.id without committing yet

        membership = Membership(user_id=user.id, org_id=org.id, role="owner")
        db.add(membership)
        db.commit()
        db.refresh(org)
        db.refresh(user)
    except Exception as e:
        db.rollback()
        # Clean up the Supabase auth user so the email isn't burnt.
        try:
            supabase_admin.auth.admin.delete_user(auth_user_id)
        except Exception as cleanup_err:
            logger.error(
                f"Failed to clean up Supabase user {auth_user_id} after DB error: {cleanup_err}"
            )
        logger.exception(f"Signup-org DB failure for {email}: {e}")
        raise HTTPException(status_code=500, detail="Failed to provision organization.")

    return SignupOrgResponse(
        user_id=user.id,
        organization_id=org.id,
        email_confirmation_required=False,
        message="Account created. Logging you in...",
    )
