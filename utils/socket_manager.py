import redis
import json
import os
from core.config import settings
# Redis Connection for Publishing Messages (Sync for Celery)
redis_url = settings.REDIS_URL

# Safety fix for SSL (Upstash support)
if redis_url.startswith("redis://"):
    pass 

class ProgressNotifier:
    """
    Helper class to publish real-time updates to Redis.
    FastAPI will listen to these messages and forward them to the User via WebSockets.
    """
    def __init__(self, video_id):
        self.video_id = video_id
        # We will create a separate channel for each video
        self.channel_name = f"channel_video_{video_id}"
        
        # Establishing Redis Connection
        self.redis_client = redis.from_url(redis_url, decode_responses=True)

    def send_update(self, status: str, progress: int, message: str):
        """
        Publishes an update to Redis.
        Format: JSON string
        """
        data = {
            "video_id": self.video_id,
            "status": status,      # e.g., "processing", "transcribing"
            "progress": progress,  # e.g., 10, 50, 100
            "message": message     # e.g., "Transcription Complete"
        }
        
        # Publish on Redis Channel
        try:
            self.redis_client.publish(self.channel_name, json.dumps(data))
            print(f"📡 Broadcast to {self.channel_name}: {message}")
        except Exception as e:
            print(f"❌ Failed to broadcast update: {e}")