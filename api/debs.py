import uuid
import time
import threading
from typing import Optional
import requests
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

from sqlalchemy.orm import Session

from core.config import settings
from core.logger import setup_logging
from core.supabase_admin import supabase_admin
from db.session import get_db
from models.user import User
from models.organization import Organization
from models.membership import Membership

logger = setup_logging()
security = HTTPBearer()


# --- Supabase JWKS cache (for asymmetric ES256/RS256 token verification) ---
_jwks_cache: dict = {"data": None, "fetched_at": 0.0}
_jwks_lock = threading.Lock()
_JWKS_TTL_SECONDS = 3600


def _fetch_jwks() -> dict:
    """Fetch (and cache) the project's public JWKS used to verify asymmetric JWTs."""
    with _jwks_lock:
        now = time.time()
        if _jwks_cache["data"] is not None and now - _jwks_cache["fetched_at"] < _JWKS_TTL_SECONDS:
            return _jwks_cache["data"]
        if not settings.SUPABASE_URL:
            raise RuntimeError("SUPABASE_URL not configured.")
        url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        _jwks_cache["data"] = resp.json()
        _jwks_cache["fetched_at"] = now
        return _jwks_cache["data"]


def _decode_supabase_jwt(token: str) -> dict:
    """Verify a Supabase JWT regardless of signing scheme (HS256 legacy or ES256/RS256)."""
    header = jwt.get_unverified_header(token)
    alg = header.get("alg", "HS256")
    kid = header.get("kid")

    if alg == "HS256":
        if not settings.SUPABASE_JWT_SECRET:
            raise RuntimeError("SUPABASE_JWT_SECRET not configured for HS256 verification.")
        return jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )

    # Asymmetric (ES256 / RS256 / EdDSA) — look up the public key in JWKS by kid.
    jwks = _fetch_jwks()
    key = None
    for k in jwks.get("keys", []):
        if k.get("kid") == kid:
            key = k
            break
    if not key:
        # Refresh once in case a new key was rotated in.
        with _jwks_lock:
            _jwks_cache["fetched_at"] = 0.0
        jwks = _fetch_jwks()
        for k in jwks.get("keys", []):
            if k.get("kid") == kid:
                key = k
                break
        if not key:
            raise JWTError(f"No matching JWKS key for kid={kid}.")

    return jwt.decode(
        token,
        key,
        algorithms=[alg],
        options={"verify_aud": False},
    )


def _credentials_exception(detail: str = "Could not validate credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_user(
    token_obj: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Verify Supabase JWT (HS256 legacy or ES256/RS256 asymmetric) and return the local User row."""
    try:
        payload = _decode_supabase_jwt(token_obj.credentials)
        user_id = payload.get("sub")
        if not user_id:
            raise _credentials_exception()
    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        raise _credentials_exception()
    except Exception as e:
        logger.warning(f"JWT verification error: {e}")
        raise _credentials_exception()

    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise _credentials_exception()

    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        # auth.users exists but public.users row is missing — happens for
        # users provisioned via supabase invite_user_by_email who haven't
        # gone through signup-org. Auto-provision from JWT claims so the
        # caller can hit /accept-invite without a chicken-and-egg.
        #
        # CRITICAL: verify the auth.users row still exists in Supabase
        # before creating anything. A JWT is cryptographically valid until
        # its exp claim regardless of whether the user behind it has been
        # deleted (browser localStorage outlives server-side deletion).
        # Without this check, a removed user's stale JWT would silently
        # resurrect a ghost public.users row every time their browser
        # hit any authed endpoint.
        try:
            auth_resp = supabase_admin.auth.admin.get_user_by_id(str(user_uuid))
            auth_user = getattr(auth_resp, "user", None)
        except Exception as e:
            logger.warning(f"Supabase auth verify failed for {user_uuid}: {e}")
            raise _credentials_exception("Could not verify user account.")
        if not auth_user:
            raise _credentials_exception("User account no longer exists.")

        email = (payload.get("email") or "").lower().strip()
        if not email:
            raise HTTPException(status_code=404, detail="User profile not provisioned.")
        meta = payload.get("user_metadata") or {}
        full_name = meta.get("full_name") or meta.get("name") or None
        user = User(
            id=user_uuid,
            email=email,
            full_name=full_name,
            is_active=True,
        )
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
            logger.info(f"Auto-provisioned public.users row for {email}")
        except Exception:
            db.rollback()
            # Race: another concurrent request just created it. Re-read.
            user = db.query(User).filter(User.id == user_uuid).first()
            if not user:
                raise HTTPException(status_code=500, detail="Failed to provision user profile.")
    elif not (user.full_name or "").strip():
        # The row was auto-provisioned earlier (e.g. /orgs/mine fired on app
        # mount during the invite flow before the recipient typed their name).
        # The JWT may now carry the name they just set via supabase.auth.updateUser.
        # Backfill so the team list doesn't show an empty name forever.
        meta = payload.get("user_metadata") or {}
        new_name = (meta.get("full_name") or meta.get("name") or "").strip()
        if new_name:
            user.full_name = new_name
            try:
                db.commit()
                db.refresh(user)
            except Exception:
                db.rollback()
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User is deactivated.")
    return user


VALID_ROLES = ("owner", "admin", "member", "guest")

# Roles ordered low → high. Comparing index gives a "rank".
# - guest:  can NOT upload new docs; only sees docs shared with them
# - member: can upload new docs + sees docs shared with them
# - admin:  manages teammates, sees every doc, cannot delete others' docs
# - owner:  manages everything including billing
_ROLE_RANK = {"guest": 0, "member": 1, "admin": 2, "owner": 3}


def role_rank(role: str) -> int:
    return _ROLE_RANK.get(role, -1)


class OrgContext:
    """Carries the active org membership for a request."""

    def __init__(self, user: User, organization: Organization, membership: Membership):
        self.user = user
        self.organization = organization
        self.membership = membership

    @property
    def role(self) -> str:
        return self.membership.role

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    @property
    def is_admin_or_above(self) -> bool:
        return self.role in ("owner", "admin")

    @property
    def can_upload(self) -> bool:
        # Guest is the only org role that can't create new docs.
        return self.role in ("owner", "admin", "member")


def require_org_member(
    x_org_id: Optional[str] = Header(default=None, alias="X-Org-Id"),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> OrgContext:
    """Verify the caller has a membership in the org passed via X-Org-Id."""
    if not x_org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Org-Id header.",
        )
    try:
        org_uuid = uuid.UUID(x_org_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-Org-Id.")

    membership = (
        db.query(Membership)
        .filter(Membership.user_id == user.id, Membership.org_id == org_uuid)
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this organization.",
        )

    org = db.query(Organization).filter(Organization.id == org_uuid).first()
    if not org or not org.is_active:
        raise HTTPException(status_code=404, detail="Organization not found.")

    return OrgContext(user=user, organization=org, membership=membership)


class RequireRole:
    """Dependency factory. Usage: Depends(RequireRole(['owner']))."""

    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(
        self, ctx: OrgContext = Depends(require_org_member)
    ) -> OrgContext:
        if ctx.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of: {', '.join(self.allowed_roles)}",
            )
        return ctx
