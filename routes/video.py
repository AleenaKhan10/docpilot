import secrets
import shutil
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import (
    APIRouter,
    Depends,
    UploadFile,
    File,
    Form,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from typing import Any, List

from db.session import get_db
from models.user import User
from models.membership import Membership
from models.video import Video
from models.video_share import VideoShare
from models.video_access import VideoAccess
from models.step import Step
from workers.tasks import process_video_task
from sqlalchemy import or_
from utils.validators import (
    enforce_upload_size,
    enforce_video_duration,
    validate_video_file_signature,
)
from core.config import settings
from core.limiter import limiter
from core.logger import setup_logging
from core.signed_urls import sign_download, verify_download
from core.storage import (
    get_signed_url as storage_signed_url,
    upload_bytes,
    upload_key_for_video,
)
from schemas.video import VideoResponse
from api.debs import require_org_member, RequireRole, OrgContext
from api.video_access import can_edit, can_view, compute_access

logger = setup_logging()

router = APIRouter()

TEMP_DATA_ROOT = Path("temp_data").resolve()


def _make_signed_url(base_url: str, video_id: int, file_path: str) -> str:
    exp, sig = sign_download(video_id, file_path)
    return f"{base_url}/api/v1/videos/{video_id}/files/{file_path}?exp={exp}&sig={sig}"


# --- 1. UPLOAD VIDEO (member, admin, owner) ---
SUPPORTED_OUTPUT_TYPES = {
    "sop", "training", "bug_report", "changelog", "audit", "client_handover"
}


@router.post("/", response_model=VideoResponse)
@limiter.limit("5/minute")
async def create_video(
    request: Request,
    title: str = Form(...),
    file: UploadFile = File(...),
    output_type: str = Form("sop"),
    description: str = Form(""),
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(RequireRole(["owner", "admin", "member"])),
):
    """Upload a video and start processing. Guest role cannot upload.

    Form fields:
      - title (required)
      - file (required)
      - output_type (optional, default "sop"). Drives Pass 2 prompt branching.
      - description (optional). Free-text "context" for the editorial AI.

    Enforcement order (cheapest checks first):
      1. Per-org daily quota
      2. Declared file size
      3. Output type whitelist
      4. MIME type via magic bytes
      5. Save to disk
      6. Real video duration via ffprobe (reject + clean up if over cap)
    """
    # (1) Daily quota per org.
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    used_today = (
        db.query(Video)
        .filter(Video.org_id == ctx.organization.id, Video.created_at >= cutoff)
        .count()
    )
    if used_today >= settings.MAX_VIDEOS_PER_ORG_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily upload limit reached "
                f"({settings.MAX_VIDEOS_PER_ORG_PER_DAY} videos / 24h)."
            ),
        )

    # (2) Declared size.
    enforce_upload_size(file)

    # (3) Output type whitelist.
    output_type = (output_type or "sop").strip().lower()
    if output_type not in SUPPORTED_OUTPUT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown output_type '{output_type}'. "
                   f"Allowed: {sorted(SUPPORTED_OUTPUT_TYPES)}.",
        )

    # (4) MIME type via magic bytes.
    await validate_video_file_signature(file)

    new_video = Video(
        title=title,
        video_url="",
        user_id=ctx.user.id,
        org_id=ctx.organization.id,
        status="pending",
        output_type=output_type,
        user_context=description.strip() or None,
    )
    db.add(new_video)
    db.commit()
    db.refresh(new_video)

    upload_dir = f"temp_data/{new_video.id}"
    os.makedirs(upload_dir, exist_ok=True)
    saved_file_path = os.path.join(upload_dir, "input.mp4")

    try:
        # (4) Save to disk.
        with open(saved_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # (5) Duration check now that we have a real file on disk.
        try:
            enforce_video_duration(saved_file_path)
        except HTTPException:
            # Clean up oversize video before re-raising.
            db.delete(new_video)
            db.commit()
            if os.path.exists(upload_dir):
                shutil.rmtree(upload_dir, ignore_errors=True)
            raise

        new_video.video_url = saved_file_path
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to save uploaded video")
        db.delete(new_video)
        db.commit()
        if os.path.exists(upload_dir):
            shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to save video: {str(e)}"
        )

    process_video_task.delay(new_video.id, saved_file_path)
    return new_video


# --- 2. GET VIDEO DETAILS ---
@router.get("/{video_id}", response_model=VideoResponse)
def get_video_details(
    video_id: int,
    request: Request,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_member),
):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or video.org_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Video not found")

    access = compute_access(db, ctx, video)
    if not can_view(access):
        # 404 rather than 403 so we don't reveal that the doc exists.
        raise HTTPException(status_code=404, detail="Video not found")

    base_url = str(request.base_url).rstrip("/")

    formatted_steps = []
    steps = (
        db.query(Step)
        .filter(Step.video_id == video_id)
        .order_by(Step.step_number)
        .all()
    )
    for step in steps:
        full_image_url = None
        if step.image_url:
            clean_path = step.image_url.replace("\\", "/")
            # Convert stored "temp_data/{id}/frames/frame_NNN.jpg" → signed URL.
            prefix = f"temp_data/{video.id}/"
            if clean_path.startswith(prefix):
                inner = clean_path[len(prefix):]
                full_image_url = _make_signed_url(base_url, video.id, inner)
            else:
                full_image_url = step.image_url

        formatted_steps.append(
            {
                "step_number": step.step_number,
                "timestamp": step.timestamp if step.timestamp is not None else 0.0,
                "title": step.title,
                "description": step.description,
                "section_summary": step.section_summary,
                "tip": step.tip,
                "note": step.note,
                "explanation": step.explanation,
                "url": step.url,
                "image_url": full_image_url,
            }
        )

    pdf_link = None
    if video.status == "completed":
        # Prefer Supabase Storage if the worker uploaded it; otherwise fall
        # back to the local signed-URL route.
        if video.pdf_storage_path:
            pdf_link = storage_signed_url(video.pdf_storage_path)
        if not pdf_link:
            local_pdf_path = TEMP_DATA_ROOT / str(video.id) / "manual.pdf"
            if local_pdf_path.exists():
                pdf_link = _make_signed_url(base_url, video.id, "manual.pdf")

    document_json = _resolve_image_refs_in_document(
        video.document_json,
        base_url,
        video.id,
        frame_storage_paths=video.frame_storage_paths or {},
    )

    creator_name = None
    if video.user_id:
        from models.user import User as UserModel
        creator = db.query(UserModel).filter(UserModel.id == video.user_id).first()
        if creator:
            creator_name = creator.full_name or creator.email

    return {
        "id": video.id,
        "title": video.title,
        "status": video.status,
        "output_type": video.output_type or "sop",
        "user_context": video.user_context,
        "created_at": video.created_at,
        "updated_at": video.updated_at,
        "created_by": creator_name,
        "pdf_url": pdf_link,
        "document_json": document_json,
        "steps": formatted_steps,
        "your_access": access,
    }


def _resolve_image_refs_in_document(
    document, base_url: str, video_id: int, frame_storage_paths: dict | None = None,
):
    """Translate `frame_id` / `storage_key` references inside image blocks
    into signed download URLs (1h TTL). Prefers Supabase Storage when the
    frame has been uploaded; otherwise falls back to the local-disk
    signed-URL route.

    Returns a copy; doesn't mutate the input. **Always recomputes the
    url** for blocks that carry a frame_id or storage_key — never trust
    the persisted url, since signed URLs expire and the host changes
    (e.g. localhost on dev → api.usedocpilot.com on prod). Only blocks
    that have a fully external url with no frame_id/storage_key are left
    untouched.
    """
    if not document or not isinstance(document, dict):
        return document
    frame_storage_paths = frame_storage_paths or {}

    out = dict(document)
    new_sections = []
    for section in out.get("sections") or []:
        if not isinstance(section, dict):
            continue
        s = dict(section)
        new_blocks = []
        for block in s.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            b = dict(block)
            if b.get("type") == "image":
                frame_id = b.get("frame_id")
                storage_key = b.get("storage_key") or frame_storage_paths.get(frame_id or "")
                # Always recompute if we have a way to. Only leave the
                # block's url alone when it's an external/user-supplied
                # link the resolver couldn't reproduce.
                if storage_key:
                    url = storage_signed_url(storage_key)
                    if url:
                        b["url"] = url
                elif frame_id:
                    inner = f"frames/{frame_id}.jpg"
                    b["url"] = _make_signed_url(base_url, video_id, inner)
            new_blocks.append(b)
        s["blocks"] = new_blocks
        new_sections.append(s)
    out["sections"] = new_sections
    return out


# --- 3. LIST VIDEOS THE CALLER CAN ACCESS ---
@router.get("/", response_model=List[VideoResponse])
def get_org_videos(
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_member),
):
    """List videos visible to the caller.

    Visibility (mirrors api.video_access.compute_access):
      • Org owner            → all videos in the org
      • Doc owner (uploader) → that video
      • Explicit grant       → that video at the grant's access level
    """
    base_q = db.query(Video).filter(Video.org_id == ctx.organization.id)

    if ctx.role == "owner":
        videos = base_q.order_by(Video.created_at.desc()).all()
        grants_by_video: dict[int, str] = {}
    else:
        granted_ids = db.query(VideoAccess.video_id).filter(
            VideoAccess.user_id == ctx.user.id
        )
        videos = (
            base_q.filter(
                or_(Video.user_id == ctx.user.id, Video.id.in_(granted_ids))
            )
            .order_by(Video.created_at.desc())
            .all()
        )
        rows = (
            db.query(VideoAccess.video_id, VideoAccess.access)
            .filter(VideoAccess.user_id == ctx.user.id)
            .all()
        )
        grants_by_video = {vid: acc for vid, acc in rows}

    # Batch-load uploader display names so the list can render the
    # "Created by" column without an N+1.
    creator_ids = {v.user_id for v in videos if v.user_id}
    creators: dict = {}
    if creator_ids:
        from models.user import User as UserModel
        for u in db.query(UserModel).filter(UserModel.id.in_(creator_ids)).all():
            creators[u.id] = u.full_name or u.email

    out = []
    for v in videos:
        if ctx.role == "owner" or v.user_id == ctx.user.id:
            level = "owner"
        else:
            level = grants_by_video.get(v.id) or "view"
        d = {col.name: getattr(v, col.name) for col in v.__table__.columns}
        d["your_access"] = level
        d["created_by"] = creators.get(v.user_id) if v.user_id else None
        out.append(d)
    return out


# --- 4. SAVE EDITED DOCUMENT (owner/editor) ---
class DocumentBlock(BaseModel):
    # Permissive shape so the editor can freely add fields. We validate at
    # the section level (heading required, blocks must be a list).
    class Config:
        extra = "allow"


class DocumentSection(BaseModel):
    heading: str
    intro: str | None = None
    blocks: List[dict] = []

    class Config:
        extra = "allow"


class DocumentPayload(BaseModel):
    title: str = ""
    summary: str = ""
    output_type: str = "sop"
    sections: List[DocumentSection] = []


@router.put("/{video_id}/document")
def save_video_document(
    video_id: int,
    payload: DocumentPayload,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_member),
):
    """Replace the rich document for a video.

    Required access on this doc: owner | edit (org-level role alone isn't
    enough — must have an edit grant or be the doc owner / org owner).
    """
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or video.org_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Video not found.")
    if not can_edit(compute_access(db, ctx, video)):
        raise HTTPException(
            status_code=403,
            detail="You need edit access on this document.",
        )

    doc = payload.model_dump()
    # Light normalisation: ensure each block has an `order` and only known
    # types pass through. Unknown types are kept (frontend may add new types).
    for s_idx, section in enumerate(doc.get("sections") or []):
        section["order"] = s_idx + 1
        for b_idx, block in enumerate(section.get("blocks") or []):
            block["order"] = b_idx + 1
    video.document_json = doc
    flag_modified(video, "document_json")
    db.commit()
    return {"ok": True}


# --- 5. UPLOAD AN IMAGE FOR THE EDITOR ---
@router.post("/{video_id}/images")
async def upload_image_for_video(
    video_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_member),
):
    """Upload an image for use inside the document editor.

    Required access on this doc: owner | edit. Validates MIME, caps at
    10 MB, stores in Supabase Storage under the video's folder, returns
    a fresh signed URL the editor can drop into an `image` block.
    """
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or video.org_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Video not found.")
    if not can_edit(compute_access(db, ctx, video)):
        raise HTTPException(
            status_code=403,
            detail="You need edit access on this document.",
        )

    # Lightweight MIME check via the uploaded file's content_type — the
    # multipart parser already sniffs headers. For paranoia we could rerun
    # libmagic here but image uploads are low-stakes compared to video.
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")

    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image is larger than 10 MB.")
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload.")

    key = upload_key_for_video(video_id, file.filename or "image")
    try:
        upload_bytes(data, key, content_type=file.content_type or "image/jpeg")
    except Exception as e:
        logger.exception("Image upload to Supabase Storage failed")
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    url = storage_signed_url(key)
    return {"storage_key": key, "url": url}


# --- 6. PUBLIC SHARE LINK MANAGEMENT ---
class ShareRequest(BaseModel):
    expires_in_days: int | None = None


class ShareResponse(BaseModel):
    token: str
    url: str
    is_active: bool
    expires_at: str | None
    created_at: str


def _can_manage_share(video: Video, ctx: OrgContext) -> bool:
    """Doc owner (uploader) OR org owner can manage the share link."""
    return video.user_id == ctx.user.id or ctx.role == "owner"


def _share_to_response(share: VideoShare) -> ShareResponse:
    return ShareResponse(
        token=share.token,
        url=f"{settings.APP_BASE_URL}/share/{share.token}",
        is_active=share.is_active,
        expires_at=share.expires_at.isoformat() if share.expires_at else None,
        created_at=share.created_at.isoformat(),
    )


@router.get("/{video_id}/share")
def get_share_link(
    video_id: int,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_member),
):
    """Return the current share link for this video, or null if none."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or video.org_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Video not found.")
    share = db.query(VideoShare).filter(VideoShare.video_id == video_id).first()
    if not share or not share.is_active:
        return None
    return _share_to_response(share)


@router.post("/{video_id}/share", response_model=ShareResponse)
def create_or_refresh_share_link(
    video_id: int,
    payload: ShareRequest,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_member),
):
    """Create a new share link or rotate the token on an existing one.

    Doc owner (uploader) or org owner can do this. Any prior token is
    invalidated by the rotation.
    """
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or video.org_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Video not found.")
    if not _can_manage_share(video, ctx):
        raise HTTPException(
            status_code=403,
            detail="Only the document owner or the org owner can manage sharing.",
        )

    expires_at = None
    if payload.expires_in_days and payload.expires_in_days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=payload.expires_in_days
        )

    token = secrets.token_urlsafe(32)
    share = db.query(VideoShare).filter(VideoShare.video_id == video_id).first()
    if share:
        share.token = token
        share.is_active = True
        share.expires_at = expires_at
        share.created_by = ctx.user.id
    else:
        share = VideoShare(
            video_id=video_id,
            token=token,
            is_active=True,
            expires_at=expires_at,
            created_by=ctx.user.id,
        )
        db.add(share)
    db.commit()
    db.refresh(share)
    return _share_to_response(share)


@router.delete("/{video_id}/share")
def disable_share_link(
    video_id: int,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_member),
):
    """Disable the share link. The token becomes useless until you POST again
    (which rotates to a fresh token)."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or video.org_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Video not found.")
    if not _can_manage_share(video, ctx):
        raise HTTPException(status_code=403, detail="Cannot manage sharing.")

    share = db.query(VideoShare).filter(VideoShare.video_id == video_id).first()
    if share:
        share.is_active = False
        db.commit()
    return {"ok": True}


# --- 6b. DELETE VIDEO (owner of doc OR org owner only — NOT admin) ---
@router.delete("/{video_id}")
def delete_video(
    video_id: int,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_member),
):
    """Permanently delete a video + its document + cascading children.

    Allowed for:
      - Org owner (super admin)
      - Doc owner (uploader)

    Admins explicitly cannot delete — that's the point of the role.
    """
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or video.org_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Video not found.")
    if not can_delete(ctx, video):
        raise HTTPException(
            status_code=403,
            detail="Only the document owner or the org owner can delete a document.",
        )

    db.delete(video)
    db.commit()
    return {"ok": True}


# --- 7. PER-DOC PEOPLE ACCESS ---
class GrantRequest(BaseModel):
    email: str
    access: str  # "edit" | "view"


class GrantedUser(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    access: str
    granted_at: str


class OwnerInfo(BaseModel):
    user_id: str
    email: str
    full_name: str | None


class AccessListResponse(BaseModel):
    owner: OwnerInfo
    grants: list[GrantedUser]


def _can_manage_access(video: Video, ctx: OrgContext) -> bool:
    """Doc owner OR org owner can manage who else has access."""
    return video.user_id == ctx.user.id or ctx.role == "owner"


@router.get("/{video_id}/access", response_model=AccessListResponse)
def list_access(
    video_id: int,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_member),
):
    """Owner + explicit grants. Visible to anyone with view access on the doc."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or video.org_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Video not found.")
    if not can_view(compute_access(db, ctx, video)):
        raise HTTPException(status_code=404, detail="Video not found.")

    uploader = db.query(User).filter(User.id == video.user_id).first()
    rows = (
        db.query(VideoAccess, User)
        .join(User, VideoAccess.user_id == User.id)
        .filter(VideoAccess.video_id == video_id)
        .order_by(VideoAccess.granted_at.asc())
        .all()
    )
    return AccessListResponse(
        owner=OwnerInfo(
            user_id=str(uploader.id) if uploader else "",
            email=uploader.email if uploader else "",
            full_name=uploader.full_name if uploader else None,
        ),
        grants=[
            GrantedUser(
                user_id=str(u.id),
                email=u.email,
                full_name=u.full_name,
                access=g.access,
                granted_at=g.granted_at.isoformat() if g.granted_at else "",
            )
            for (g, u) in rows
        ],
    )


@router.post("/{video_id}/access")
def grant_access(
    video_id: int,
    payload: GrantRequest,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_member),
):
    """Grant edit or view access to an org member by email.

    Idempotent — granting the same email twice updates the access level.
    """
    if payload.access not in ("edit", "view"):
        raise HTTPException(
            status_code=400, detail="access must be 'edit' or 'view'."
        )

    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or video.org_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Video not found.")
    if not _can_manage_access(video, ctx):
        raise HTTPException(
            status_code=403,
            detail="Only the document owner or the org owner can manage access.",
        )

    email = payload.email.strip().lower()
    target = db.query(User).filter(User.email == email).first()
    if not target:
        raise HTTPException(
            status_code=404,
            detail="No DocPilot account for that email. Invite them to the org first.",
        )

    is_member = (
        db.query(Membership)
        .filter(
            Membership.user_id == target.id,
            Membership.org_id == ctx.organization.id,
        )
        .first()
        is not None
    )
    if not is_member:
        raise HTTPException(
            status_code=400,
            detail="That user isn't a member of this organization.",
        )
    if target.id == video.user_id:
        raise HTTPException(
            status_code=400, detail="That user already owns this document."
        )

    grant = (
        db.query(VideoAccess)
        .filter(
            VideoAccess.video_id == video_id, VideoAccess.user_id == target.id
        )
        .first()
    )
    if grant:
        grant.access = payload.access
        grant.granted_by = ctx.user.id
    else:
        grant = VideoAccess(
            video_id=video_id,
            user_id=target.id,
            access=payload.access,
            granted_by=ctx.user.id,
        )
        db.add(grant)
    db.commit()
    return {"ok": True}


@router.delete("/{video_id}/access/{user_id}")
def revoke_access(
    video_id: int,
    user_id: str,
    db: Session = Depends(get_db),
    ctx: OrgContext = Depends(require_org_member),
):
    """Revoke an explicit grant. Idempotent."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or video.org_id != ctx.organization.id:
        raise HTTPException(status_code=404, detail="Video not found.")
    if not _can_manage_access(video, ctx):
        raise HTTPException(status_code=403, detail="Cannot manage access.")

    deleted = (
        db.query(VideoAccess)
        .filter(
            VideoAccess.video_id == video_id,
            VideoAccess.user_id == user_id,
        )
        .delete()
    )
    db.commit()
    return {"ok": True, "deleted": deleted}


# --- 8. SERVE VIDEO FILES (signed-URL gated, replaces /downloads/*) ---
@router.get("/{video_id}/files/{file_path:path}")
def get_video_file(
    video_id: int,
    file_path: str,
    exp: int = Query(...),
    sig: str = Query(...),
):
    """Serve a file from temp_data/{video_id}/ if the signature is valid.

    Replaces the old unauthenticated `/downloads/*` static mount.
    No JWT needed — the signature in the URL is the access proof.
    URLs expire after 1h by default and are issued only via
    `GET /api/v1/videos/{id}` (which is org-membership-gated).
    """
    try:
        verify_download(video_id, file_path, exp, sig)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    target = (TEMP_DATA_ROOT / str(video_id) / file_path).resolve()

    # Path-traversal guard: target must stay inside its video's folder.
    video_root = (TEMP_DATA_ROOT / str(video_id)).resolve()
    try:
        target.relative_to(video_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file path.")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    media_type = None
    name = target.name.lower()
    if name.endswith(".pdf"):
        media_type = "application/pdf"
    elif name.endswith((".jpg", ".jpeg")):
        media_type = "image/jpeg"
    elif name.endswith(".png"):
        media_type = "image/png"

    return FileResponse(str(target), media_type=media_type, filename=target.name)
