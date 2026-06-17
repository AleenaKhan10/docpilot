"""
Effective per-video access resolution.

`compute_access(db, ctx, video)` returns one of:
  - "owner"  : org owner, org admin, or doc owner (uploader). Full view+edit.
  - "edit"   : explicit edit grant on this doc.
  - "view"   : explicit view grant on this doc.
  - None     : no access — the caller should 404 (don't leak existence).

Delete is a separate, more privileged check (`can_delete`). Admins
explicitly cannot delete; only the org owner or the doc owner can.
"""

from typing import Literal, Optional

from sqlalchemy.orm import Session

from api.debs import OrgContext
from models.video import Video
from models.video_access import VideoAccess

AccessLevel = Literal["owner", "edit", "view"]


def compute_access(db: Session, ctx: OrgContext, video: Video) -> Optional[AccessLevel]:
    if video.org_id != ctx.organization.id:
        return None
    # Org owners + admins have view/edit on every doc in the org.
    if ctx.is_admin_or_above:
        return "owner"
    if video.user_id == ctx.user.id:
        return "owner"
    grant = (
        db.query(VideoAccess)
        .filter(
            VideoAccess.video_id == video.id,
            VideoAccess.user_id == ctx.user.id,
        )
        .first()
    )
    if grant:
        return grant.access  # type: ignore[return-value]
    return None


def can_edit(level: Optional[AccessLevel]) -> bool:
    return level in ("owner", "edit")


def can_view(level: Optional[AccessLevel]) -> bool:
    return level in ("owner", "edit", "view")


def can_delete(ctx: OrgContext, video: Video) -> bool:
    """Delete is more privileged than edit.

    Allowed only for:
      - Org OWNER (super admin) on any doc
      - DOC owner (uploader) on their own doc

    Admins explicitly do NOT have delete by design.
    """
    return ctx.is_owner or video.user_id == ctx.user.id
