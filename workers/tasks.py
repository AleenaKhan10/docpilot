import os
import json
import logging
from core.celery_app import celery_app
from db.session import SessionLocal
from models.video import Video
from models.step import Step
from services.processing import extract_audio, extract_frames
from services.audio_service import transcribe_audio_local
from services.openrouter_service import generate_documentation_steps

# --- LOGGER SETUP ---
logger = logging.getLogger(__name__)

@celery_app.task(bind=True)
def process_video_task(self, video_id: int, video_path: str):
    logger.info(f"🚀 Worker Started: Processing Video ID {video_id}")
    
    db = SessionLocal()
    video = db.query(Video).filter(Video.id == video_id).first()
    
    if not video:
        logger.error(f"Video ID {video_id} not found in Database")
        return "Failed"

    video.status = "processing"
    db.commit()

    base_dir = f"temp_data/{video_id}"
    
    try:
        os.makedirs(base_dir, exist_ok=True)
        audio_path = os.path.join(base_dir, "audio.mp3")
        frames_dir = os.path.join(base_dir, "frames")

        # 1. Splitting
        logger.info("⚙️ Splitting Video into Frames & Audio...")
        extracted_audio_path = extract_audio(video_path, audio_path)
        extract_frames(video_path, frames_dir, interval=1) # Extracting every 1s (Smart filter will clean it)

        # 2. Transcription
        transcript = []
        if extracted_audio_path:
            logger.info("🔊 Transcribing locally with Faster-Whisper...")
            transcript = transcribe_audio_local(extracted_audio_path)
        else:
            logger.warning("🔇 No Audio Track Found (Silent Video).")

        # 3. AI Generation
        logger.info("🤖 Generating Documentation via OpenRouter (Parallel Mode)...")
        final_steps = generate_documentation_steps(transcript, frames_dir, interval=1)

        # 4. Save Debug JSON
        json_path = os.path.join(base_dir, "documentation.json")
        with open(json_path, "w") as f:
            json.dump(final_steps, f, indent=4)
        logger.info(f"📂 Debug JSON Saved: {json_path}")

        # 5. Save to DB
        logger.info(f"💾 Saving {len(final_steps)} steps to Database...")
        for step_data in final_steps:
            new_step = Step(
                video_id=video_id,
                step_number=step_data['step_number'],
                timestamp=step_data['timestamp'],
                description=step_data['description'],
                image_url=step_data['image_path']
            )
            db.add(new_step)
        
        video.status = "completed"
        db.commit()
        
        logger.info(f"✅ Task for Video {video_id} Finished Successfully!")
        return "Done"

    except Exception as e:
        # exc_info=True saves complete error trace in log file
        logger.error(f"❌ Worker Failed for Video {video_id}: {e}", exc_info=True)
        
        video.status = "failed"
        db.commit()
        return f"Error: {e}"
    finally:
        db.close()