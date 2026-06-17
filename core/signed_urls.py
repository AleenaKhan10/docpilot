"""
Short-lived signed URLs for tenant-scoped file downloads.

Replaces the unauthenticated `/downloads/*` StaticFiles mount with
HMAC-signed URLs. Each URL embeds an expiry + signature, verified by
the file-serving route. No JWT / cookie required by the browser, so
the URLs work directly in <img> tags and window.open().

Sig payload: f"{video_id}:{path}:{exp}"  signed with HMAC-SHA256
using SUPABASE_JWT_SECRET as the key. Constant-time comparison.
"""

import hashlib
import hmac
import time
from typing import Tuple

from core.config import settings

DEFAULT_TTL_SECONDS = 3600  # 1 hour


def _key() -> bytes:
    secret = settings.SUPABASE_JWT_SECRET
    if not secret:
        raise RuntimeError("SUPABASE_JWT_SECRET is required for signed downloads.")
    return secret.encode()


def _compute_sig(video_id: int, path: str, exp: int) -> str:
    payload = f"{video_id}:{path}:{exp}".encode()
    return hmac.new(_key(), payload, hashlib.sha256).hexdigest()


def sign_download(video_id: int, path: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Tuple[int, str]:
    """Returns (exp, sig) for a path under the given video_id."""
    exp = int(time.time()) + ttl_seconds
    return exp, _compute_sig(video_id, path, exp)


def verify_download(video_id: int, path: str, exp: int, sig: str) -> None:
    """Raises ValueError if the URL is expired or the signature is invalid."""
    if int(time.time()) > exp:
        raise ValueError("Signed URL has expired.")
    expected = _compute_sig(video_id, path, exp)
    if not hmac.compare_digest(sig, expected):
        raise ValueError("Invalid signature.")
