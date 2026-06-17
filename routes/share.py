"""
Public share routes.

The single public endpoint, GET /api/v1/share/{token}, lets anyone with the
token view a doc read-only. No JWT required.

Management of share links (create, get, disable) lives under the authed
route in routes/video.py.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from core.signed_urls import sign_download
from core.storage import get_signed_url as storage_signed_url
from db.session import get_db
from models.video import Video
from models.video_share import VideoShare

router = APIRouter()

TEMP_DATA_ROOT = Path("temp_data").resolve()


def _make_signed_url(base_url: str, video_id: int, file_path: str) -> str:
    exp, sig = sign_download(video_id, file_path)
    return f"{base_url}/api/v1/videos/{video_id}/files/{file_path}?exp={exp}&sig={sig}"


def _resolve_image_refs(
    document: Any,
    base_url: str,
    video_id: int,
    frame_storage_paths: dict | None = None,
):
    """Copy of the same translation used by the authed route, kept here so
    the public route never needs to import auth/internal stuff."""
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
            if b.get("type") == "image" and not b.get("url"):
                frame_id = b.get("frame_id")
                storage_key = b.get("storage_key") or frame_storage_paths.get(
                    frame_id or ""
                )
                if storage_key:
                    url = storage_signed_url(storage_key)
                    if url:
                        b["url"] = url
                if not b.get("url") and frame_id:
                    inner = f"frames/{frame_id}.jpg"
                    b["url"] = _make_signed_url(base_url, video_id, inner)
            new_blocks.append(b)
        s["blocks"] = new_blocks
        new_sections.append(s)
    out["sections"] = new_sections
    return out


@router.get("/share/{token}")
def get_shared_document(token: str, request: Request, db: Session = Depends(get_db)):
    """Public read-only view of a shared document. No auth required."""
    share = (
        db.query(VideoShare)
        .filter(VideoShare.token == token, VideoShare.is_active == True)
        .first()
    )
    if not share:
        raise HTTPException(status_code=404, detail="Share link not found or revoked.")
    if share.expires_at and share.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Share link has expired.")

    video = db.query(Video).filter(Video.id == share.video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Document no longer exists.")
    if video.status != "completed":
        raise HTTPException(
            status_code=409, detail="This document hasn't finished processing yet."
        )

    base_url = str(request.base_url).rstrip("/")

    document_json = _resolve_image_refs(
        video.document_json,
        base_url,
        video.id,
        frame_storage_paths=video.frame_storage_paths or {},
    )

    pdf_url = None
    if video.pdf_storage_path:
        pdf_url = storage_signed_url(video.pdf_storage_path)
    if not pdf_url:
        local_pdf_path = TEMP_DATA_ROOT / str(video.id) / "manual.pdf"
        if local_pdf_path.exists():
            pdf_url = _make_signed_url(base_url, video.id, "manual.pdf")

    return {
        "id": video.id,
        "title": video.title,
        "output_type": video.output_type or "sop",
        "pdf_url": pdf_url,
        "document_json": document_json,
        "shared_at": share.created_at.isoformat() if share.created_at else None,
    }
