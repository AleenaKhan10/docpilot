"""
Supabase Storage helpers.

Replaces the local `temp_data/{video_id}/...` file lifecycle for assets that
need to persist (generated PDFs, frames referenced in the rich document).
Frames that are NOT referenced in the final document stay on local disk and
get janitor-cleaned after an hour.

Bucket layout:
    {bucket}/videos/{video_id}/manual.pdf
    {bucket}/videos/{video_id}/frames/{frame_id}.jpg
    {bucket}/videos/{video_id}/uploads/{nanoid}-{filename}   <- editor uploads
"""

import logging
import os
import uuid
from typing import Optional

from core.config import settings
from core.supabase_admin import supabase_admin

logger = logging.getLogger(__name__)

BUCKET = "docpilot-files"
DEFAULT_SIGNED_URL_TTL = 60 * 60  # 1 h

_bucket_ready = False


def _ensure_bucket() -> None:
    """Create the bucket on first use. Idempotent — silently succeeds if it
    already exists. Bucket is created as PRIVATE so reads require a signed URL.
    """
    global _bucket_ready
    if _bucket_ready:
        return
    try:
        existing = supabase_admin.storage.list_buckets()
        names = {b.name if hasattr(b, "name") else b.get("name") for b in existing}
        if BUCKET not in names:
            supabase_admin.storage.create_bucket(
                BUCKET, options={"public": False}
            )
            logger.info(f"Created Supabase Storage bucket: {BUCKET}")
        _bucket_ready = True
    except Exception as e:
        # We log + continue. The first upload attempt will fail loudly if the
        # bucket truly doesn't exist, with a clearer error than the list call.
        logger.warning(f"Bucket check failed (may already exist): {e}")
        _bucket_ready = True


def _key_for(video_id: int, *parts: str) -> str:
    """Build a forward-slash storage key under a video folder."""
    return "/".join(["videos", str(video_id), *parts])


def upload_local_file(local_path: str, storage_key: str, content_type: Optional[str] = None) -> str:
    """Upload a file from disk to the bucket at `storage_key`. Returns the key."""
    _ensure_bucket()
    if not os.path.exists(local_path):
        raise FileNotFoundError(local_path)

    with open(local_path, "rb") as f:
        data = f.read()

    options = {"upsert": "true"}
    if content_type:
        options["content-type"] = content_type

    try:
        supabase_admin.storage.from_(BUCKET).upload(
            path=storage_key, file=data, file_options=options
        )
    except Exception as e:
        msg = str(e)
        # The python SDK throws on duplicate even with upsert in some versions —
        # retry once via update().
        if "exists" in msg.lower() or "duplicate" in msg.lower():
            supabase_admin.storage.from_(BUCKET).update(
                path=storage_key, file=data, file_options=options
            )
        else:
            raise
    logger.info(f"Uploaded {local_path} → storage:{storage_key} ({len(data)} bytes)")
    return storage_key


def upload_bytes(data: bytes, storage_key: str, content_type: Optional[str] = None) -> str:
    """Upload raw bytes to the bucket at `storage_key`. Returns the key."""
    _ensure_bucket()
    options = {"upsert": "true"}
    if content_type:
        options["content-type"] = content_type
    try:
        supabase_admin.storage.from_(BUCKET).upload(
            path=storage_key, file=data, file_options=options
        )
    except Exception as e:
        if "exists" in str(e).lower() or "duplicate" in str(e).lower():
            supabase_admin.storage.from_(BUCKET).update(
                path=storage_key, file=data, file_options=options
            )
        else:
            raise
    return storage_key


def get_signed_url(storage_key: str, ttl_seconds: int = DEFAULT_SIGNED_URL_TTL) -> Optional[str]:
    """Return a fresh signed URL for the given storage key. None on failure."""
    _ensure_bucket()
    try:
        res = supabase_admin.storage.from_(BUCKET).create_signed_url(
            path=storage_key, expires_in=ttl_seconds
        )
        # supabase-py returns a dict-ish with 'signedURL' or 'signed_url' depending
        # on version. Be defensive.
        if isinstance(res, dict):
            return res.get("signedURL") or res.get("signed_url") or res.get("signedUrl")
        return getattr(res, "signed_url", None) or getattr(res, "signedURL", None)
    except Exception as e:
        logger.warning(f"Signed URL failed for {storage_key}: {e}")
        return None


def delete_object(storage_key: str) -> None:
    """Best-effort delete; logs and continues on failure."""
    try:
        supabase_admin.storage.from_(BUCKET).remove([storage_key])
    except Exception as e:
        logger.warning(f"Delete failed for {storage_key}: {e}")


# --- Convenience builders --------------------------------------------------
def pdf_key_for_video(video_id: int) -> str:
    return _key_for(video_id, "manual.pdf")


def frame_key_for_video(video_id: int, frame_id: str) -> str:
    return _key_for(video_id, "frames", f"{frame_id}.jpg")


def upload_key_for_video(video_id: int, filename: str) -> str:
    safe = filename.replace("/", "_").replace("\\", "_")
    return _key_for(video_id, "uploads", f"{uuid.uuid4().hex[:8]}-{safe}")


__all__ = [
    "BUCKET",
    "upload_local_file",
    "upload_bytes",
    "get_signed_url",
    "delete_object",
    "pdf_key_for_video",
    "frame_key_for_video",
    "upload_key_for_video",
    "settings",  # for re-export convenience
]
