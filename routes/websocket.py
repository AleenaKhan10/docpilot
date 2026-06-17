"""
WebSocket endpoint for streaming Celery progress updates to the frontend.

Auth model: the browser cannot attach an Authorization header to a WebSocket
upgrade, so the client passes the Supabase access token and active org_id as
query-string params:
    ws://host/ws/{video_id}?token=<JWT>&org_id=<UUID>

We verify the JWT (same path as REST: HS256 legacy OR ES256/RS256 via JWKS),
look up the user, check Membership(user, org), and confirm the video belongs
to that org BEFORE subscribing to its Redis pub/sub channel.

Cross-tenant subscription is impossible: even if a stranger guesses an integer
video_id, the membership + ownership check fails first.
"""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError
from redis import asyncio as aioredis
from sqlalchemy.orm import Session

from api.debs import _decode_supabase_jwt
from core.config import settings
from core.logger import setup_logging
from db.session import SessionLocal
from models.membership import Membership
from models.user import User
from models.video import Video

logger = setup_logging()
router = APIRouter()


def _authorize_ws_subscription(
    token: str, org_id_str: str, video_id: int
) -> tuple[User, uuid.UUID]:
    """Verify token + org membership + video ownership.

    Raises ValueError on any failure with a short reason. The caller should
    close the socket with that reason as the close_reason.
    """
    if not token:
        raise ValueError("missing token")
    if not org_id_str:
        raise ValueError("missing org_id")

    try:
        payload = _decode_supabase_jwt(token)
    except (JWTError, Exception) as e:
        logger.warning(f"WS JWT verification failed: {e}")
        raise ValueError("invalid token")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise ValueError("invalid token")

    try:
        user_id = uuid.UUID(user_id_str)
        org_id = uuid.UUID(org_id_str)
    except ValueError:
        raise ValueError("invalid identifiers")

    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            raise ValueError("user not found")

        membership = (
            db.query(Membership)
            .filter(Membership.user_id == user_id, Membership.org_id == org_id)
            .first()
        )
        if not membership:
            raise ValueError("not a member of this organization")

        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError("video not found")
        if video.org_id != org_id:
            raise ValueError("video belongs to another organization")

        return user, org_id
    finally:
        db.close()


@router.websocket("/ws/{video_id}")
async def video_progress_socket(
    websocket: WebSocket,
    video_id: int,
    token: Optional[str] = Query(default=None),
    org_id: Optional[str] = Query(default=None),
):
    """Stream Celery progress messages for `video_id` to the client.

    Requires valid Supabase JWT + active org_id (passed as query params),
    and the caller must be a member of the org that owns the video.
    """
    try:
        _authorize_ws_subscription(token or "", org_id or "", video_id)
    except ValueError as e:
        # Per RFC 6455, the server can reject the upgrade with an HTTP 4xx
        # via .close() before .accept(). Most browser clients only see the
        # generic "connection failed" but the close_reason ends up in our log.
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(e))
        return

    await websocket.accept()

    redis = aioredis.from_url(
        settings.REDIS_URL or "redis://localhost:6379/0", decode_responses=True
    )
    pubsub = redis.pubsub()
    channel_name = f"channel_video_{video_id}"
    await pubsub.subscribe(channel_name)

    logger.info(f"WS connected for video {video_id}")

    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message["data"]
            await websocket.send_text(data)
            try:
                parsed = json.loads(data)
                if parsed.get("status") in ("completed", "failed"):
                    break
            except (json.JSONDecodeError, AttributeError):
                continue
    except WebSocketDisconnect:
        logger.info(f"WS disconnected for video {video_id}")
    except Exception as e:
        logger.warning(f"WS error for video {video_id}: {e}")
    finally:
        try:
            await pubsub.unsubscribe(channel_name)
        finally:
            await redis.close()
