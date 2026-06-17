"""
Publishes pipeline progress to Redis pub/sub so the WebSocket endpoint can
forward updates to the browser, AND refreshes the per-video worker heartbeat
so the lifespan reaper knows the job is still alive.
"""

import json
from datetime import datetime, timezone

import redis
from sqlalchemy import update

from core.config import settings
from core.logger import setup_logging
from db.session import SessionLocal
from models.video import Video

logger = setup_logging()

_redis_client = None


def _get_redis_client():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.REDIS_URL or "redis://localhost:6379/0",
            decode_responses=True,
        )
    return _redis_client


def touch_heartbeat(video_id: int) -> None:
    """Mark the video's worker as currently alive (called on every progress event)."""
    db = SessionLocal()
    try:
        db.execute(
            update(Video)
            .where(Video.id == video_id)
            .values(worker_heartbeat_at=datetime.now(timezone.utc))
        )
        db.commit()
    except Exception as e:
        logger.warning(f"Heartbeat update failed for video {video_id}: {e}")
        db.rollback()
    finally:
        db.close()


def clear_heartbeat(video_id: int) -> None:
    """Called at the end of a task to signal 'no longer in-flight'."""
    db = SessionLocal()
    try:
        db.execute(
            update(Video)
            .where(Video.id == video_id)
            .values(worker_heartbeat_at=None)
        )
        db.commit()
    except Exception as e:
        logger.warning(f"Heartbeat clear failed for video {video_id}: {e}")
        db.rollback()
    finally:
        db.close()


class ProgressNotifier:
    """Publishes progress updates to Redis. Touches heartbeat on every send."""

    def __init__(self, video_id: int):
        self.video_id = video_id
        self.channel_name = f"channel_video_{video_id}"
        self.client = _get_redis_client()

    def send_update(self, status: str, progress: int, message: str) -> None:
        data = {
            "video_id": self.video_id,
            "status": status,
            "progress": progress,
            "message": message,
        }
        try:
            self.client.publish(self.channel_name, json.dumps(data))
        except Exception as e:
            logger.warning(f"Failed to publish progress for video {self.video_id}: {e}")

        # Refresh heartbeat for the reaper. Always do this, even if publish failed.
        touch_heartbeat(self.video_id)
