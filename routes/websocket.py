import asyncio
import os
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect # Imports for using Websockets
from redis import asyncio as aioredis # We need Async Redis for FastAPI

router = APIRouter()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

@router.websocket("/ws/{video_id}")
async def video_progress_socket(websocket: WebSocket, video_id: int):
    """
    WebSocket Endpoint.
    Frontend connects here: ws://localhost:8000/ws/82
    It listens to Redis Channel 'channel_video_82' and forwards messages to Frontend.
    """
    await websocket.accept()
    
    # Async Redis Client initialize
    redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    
    # Async Redis PubSub for Listening and Publishing Messages
    pubsub = redis.pubsub()
    
    # Video id (whichever we are processing)
    channel_name = f"channel_video_{video_id}"
    
    # Subscribe to Redis Channel so that it listens
    await pubsub.subscribe(channel_name)
    
    print(f"🔌 Client connected to WebSocket for Video {video_id}")

    try:
        # Loop that waits for Redis Messages
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                
                # Redis se data aya -> WebSocket par bhejo
                await websocket.send_text(data)
                
                # Agar process complete ya fail ho gaya, loop tor do
                parsed_data = json.loads(data)
                if parsed_data.get("status") in ["completed", "failed"]:
                    break
                    
    except WebSocketDisconnect:
        print(f"🔌 Client disconnected from Video {video_id}")
    except Exception as e:
        print(f"❌ WebSocket Error: {e}")
    finally:
        await pubsub.unsubscribe(channel_name)
        await redis.close()