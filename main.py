from fastapi import FastAPI
from routes import video
from db.session import engine
from models import video as video_model
from core.logger import setup_logging  # <--- NEW IMPORT

# 1. Setup Logging (First)
logger = setup_logging()
logger.info("🚀 System Startup: Logger Initialized Successfully!")

# Create Tables
video_model.Base.metadata.create_all(bind=engine)

app = FastAPI(title="VideoDocs AI")

app.include_router(video.router, prefix="/api/v1/videos", tags=["videos"])

@app.get("/")
def read_root():
    logger.info("Health check endpoint accessed.")
    return {"message": "VideoDocs AI Backend is Running!"}