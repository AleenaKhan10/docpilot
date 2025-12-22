from contextlib import asynccontextmanager
from fastapi import FastAPI 
from db.session import SessionLocal # DB Sessions
from models.video import Video # Database Model
from core.logger import logging # Logger

# Setup Logger
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application Lifecycle Manager.
    Handles startup (cleanup zombies) and shutdown events.
    """
    
    # --- STARTUP LOGIC ---
    logger.info("🔄 System Startup: Checking for interrupted tasks...")
    
    db = SessionLocal()
    try:
        # 1. Find videos that were stuck in 'processing' state
        zombie_videos = db.query(Video).filter(Video.status == "processing").all()
        
        if zombie_videos:
            count = len(zombie_videos)
            logger.warning(f"⚠️ Found {count} interrupted (zombie) tasks. Marking them as Failed.")
            
            # 2. Mark them as failed so users don't see infinite spinner
            for video in zombie_videos:
                video.status = "failed"
            
            db.commit()
            logger.info("✅ Cleanup Complete: Zombies eliminated.")
        else:
            logger.info("✅ System Clean: No interrupted tasks found.")
            
    except Exception as e:
        logger.error(f"❌ Startup Cleanup Failed: {e}")
    finally:
        db.close()
    
    # --- APP RUNS HERE ---
    yield 
    
    # --- SHUTDOWN LOGIC ---
    logger.info("🛑 System Shutdown: Closing connections...")