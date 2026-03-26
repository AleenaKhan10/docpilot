import os
import json
import logging
import time 
import shutil
from core.celery_app import celery_app
from db.session import SessionLocal
from models.video import Video
from models.step import Step
from services.processing import extract_audio, extract_frames
from services.audio_service import transcribe_audio_local
from services.openrouter_service import generate_documentation_steps
from services.pdf_service import generate_pdf_report
from utils.socket_manager import ProgressNotifier 

# --- LOGGER SETUP ---
logger = logging.getLogger(__name__)

@celery_app.task(bind=True)
def process_video_task(self, video_id: int, video_path: str):
    logger.info(f"🚀 Worker Started: Processing Video ID {video_id}")
    
    # --- 1. NOTIFIER INITIALIZE ---
    notifier = ProgressNotifier(video_id)
    notifier.send_update("started", 5, "Worker has started processing...")
    # ------------------------------

    db = SessionLocal()
    
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        return "Failed"

    video.status = "processing"
    db.commit()

    base_dir = f"temp_data/{video_id}"
    
    try:
        os.makedirs(base_dir, exist_ok=True)
        audio_path = os.path.join(base_dir, "audio.mp3")
        frames_dir = os.path.join(base_dir, "frames")

        # --- UPDATE: SPLITTING ---
        logger.info("⚙️ Splitting Video...")
        notifier.send_update("splitting", 10, "Splitting video into frames...")
        
        extracted_audio_path = extract_audio(video_path, audio_path)
        extract_frames(video_path, frames_dir, interval=1)
        
        notifier.send_update("splitting", 30, "Splitting complete. Analyzing...")

        # --- UPDATE: TRANSCRIPTION ---
        transcript = []
        if extracted_audio_path:
            logger.info("🔊 Transcribing...")
            notifier.send_update("transcribing", 40, "Transcribing audio with Whisper AI...")
            transcript = transcribe_audio_local(extracted_audio_path)
        
        notifier.send_update("transcribing", 60, "Transcription complete.")

        # --- UPDATE: AI GENERATION ---
        logger.info("🤖 Generating Documentation...")
        notifier.send_update("generating", 70, "AI is writing documentation...")
        final_steps = generate_documentation_steps(transcript, frames_dir, interval=1)

        # Save Debug JSON
        json_path = os.path.join(base_dir, "documentation.json")
        with open(json_path, "w") as f:
            json.dump(final_steps, f, indent=4)

        # Save to DB
        logger.info(f"💾 Saving to DB...")
        notifier.send_update("saving", 90, "Saving steps to database...")
        
        for step_data in final_steps:
            new_step = Step(
                video_id=video_id,
                step_number=step_data['step_number'],
                timestamp=step_data['timestamp'],
                title=step_data.get('title', 'General'),
                description=step_data['description'],
                tip=step_data.get('tip'),
                url=step_data.get('url'),
                image_url=step_data.get('image_path'),
                # --- Professional Documentation Fields ---
                explanation=step_data.get('explanation'),
                note=step_data.get('note'),
                section_summary=step_data.get('section_summary'),
            )
            db.add(new_step)
        
        # --- PDF GENERATION ---
        try:
            logger.info("🎨 Designing Professional PDF Report...")
            notifier.send_update("generating_pdf", 95, "Designing PDF Manual...")
            
            pdf_path = os.path.join(base_dir, "manual.pdf")
            
            # Helper Class to convert Dict to Object (Compatible with Jinja2 Template)
            class StepMock:
                def __init__(self, data):
                    self.step_number = data.get('step_number')
                    self.timestamp = data.get('timestamp')
                    self.description = data.get('description')
                    self.title = data.get('title', 'General')
                    self.tip = data.get('tip', None)
                    self.url = data.get('url', None)
                    # --- Professional Documentation Fields ---
                    self.explanation = data.get('explanation', None)
                    self.note = data.get('note', None)
                    self.section_summary = data.get('section_summary', None)
                    
            # Convert dict list to object list
            step_objects = [StepMock(s) for s in final_steps]
            
            # Generate PDF
            generate_pdf_report(video, step_objects, pdf_path)
            logger.info(f"✅ PDF Saved Successfully: {pdf_path}")
            
        except Exception as pdf_error:
            
            logger.error(f"⚠️ PDF Generation Failed: {pdf_error}")
        # ---------------------------------------

        video.status = "completed"
        db.commit()
        
        logger.info("✅ Task Finished!")
        # --- FINAL UPDATE ---
        notifier.send_update("completed", 100, "Documentation & PDF Ready!")
        return "Done"

    except Exception as e:
        logger.error(f"❌ Worker Failed: {e}", exc_info=True)
        notifier.send_update("failed", 0, f"Error: {str(e)}") # <--- Fail Update
        video.status = "failed"
        db.commit()
        return f"Error: {e}"
    finally:
        db.close()
        
# Cleaning TASK 
@celery_app.task
def cleanup_temp_data():
    """
    Periodic Janitor Task:
    Scans the 'temp_data' directory and deletes folders older than a specific time limit.
    This prevents the server disk from getting full.
    """
    logger.info("🧹 Janitor Started: Scanning for old files to clean...")
    
    temp_dir = "temp_data"
    
    # --- TIME LIMIT CONFIGURATION ---
    AGE_LIMIT_SECONDS = 3600 
    
    if not os.path.exists(temp_dir):
        logger.info("✅ Temp directory does not exist. Nothing to clean.")
        return

    current_time = time.time()
    deleted_count = 0

    # Iterate through folders in temp_data
    for item in os.listdir(temp_dir):
        item_path = os.path.join(temp_dir, item)
        
        # Only check directories (e.g., temp_data/82/)
        if os.path.isdir(item_path):
            try:
                # Check last modification time
                folder_mtime = os.path.getmtime(item_path)
                
                # If folder is older than limit, delete it
                if current_time - folder_mtime > AGE_LIMIT_SECONDS:
                    logger.info(f"🗑️ Found old junk: {item_path}. Deleting...")
                    shutil.rmtree(item_path) # Recursive delete
                    deleted_count += 1
            except Exception as e:
                logger.error(f"❌ Could not delete {item_path}: {e}")

    logger.info(f"✅ Janitor Finished: Cleaned up {deleted_count} old folders.")

# import os
# import json
# import logging
# import time 
# import shutil
# from core.celery_app import celery_app
# from db.session import SessionLocal
# from models.video import Video
# from models.step import Step
# from services.processing import extract_audio, extract_frames
# from services.audio_service import transcribe_audio_local
# from services.openrouter_service import generate_documentation_steps
# from utils.socket_manager import ProgressNotifier 

# # --- LOGGER SETUP ---
# logger = logging.getLogger(__name__)

# @celery_app.task(bind=True)
# def process_video_task(self, video_id: int, video_path: str):
#     logger.info(f"🚀 Worker Started: Processing Video ID {video_id}")
    
#     # --- 1. NOTIFIER INITIALIZE ---
#     notifier = ProgressNotifier(video_id)
#     notifier.send_update("started", 5, "Worker has started processing...")
#     # ------------------------------

#     db = SessionLocal()
    
#     video = db.query(Video).filter(Video.id == video_id).first()
#     if not video:
#         return "Failed"

#     video.status = "processing"
#     db.commit()

#     base_dir = f"temp_data/{video_id}"
    
#     try:
#         os.makedirs(base_dir, exist_ok=True)
#         audio_path = os.path.join(base_dir, "audio.mp3")
#         frames_dir = os.path.join(base_dir, "frames")

#         # --- UPDATE: SPLITTING ---
#         logger.info("⚙️ Splitting Video...")
#         notifier.send_update("splitting", 10, "Splitting video into frames...")
        
#         extracted_audio_path = extract_audio(video_path, audio_path)
#         extract_frames(video_path, frames_dir, interval=1)
        
#         notifier.send_update("splitting", 30, "Splitting complete. Analyzing...")

#         # --- UPDATE: TRANSCRIPTION ---
#         transcript = []
#         if extracted_audio_path:
#             logger.info("🔊 Transcribing...")
#             notifier.send_update("transcribing", 40, "Transcribing audio with Whisper AI...")
#             transcript = transcribe_audio_local(extracted_audio_path)
        
#         notifier.send_update("transcribing", 60, "Transcription complete.")

#         # --- UPDATE: AI GENERATION ---
#         logger.info("🤖 Generating Documentation...")
#         notifier.send_update("generating", 70, "AI is writing documentation...")
#         final_steps = generate_documentation_steps(transcript, frames_dir, interval=1)

#         # Save Debug JSON
#         json_path = os.path.join(base_dir, "documentation.json")
#         with open(json_path, "w") as f:
#             json.dump(final_steps, f, indent=4)

#         # Save to DB
#         logger.info(f"💾 Saving to DB...")
#         notifier.send_update("saving", 90, "Saving steps to database...")
        
#         for step_data in final_steps:
#             new_step = Step(
#                 video_id=video_id,
#                 step_number=step_data['step_number'],
#                 timestamp=step_data['timestamp'],
#                 description=step_data['description'],
#                 image_url=step_data['image_path']
#             )
#             db.add(new_step)
        
#         video.status = "completed"
#         db.commit()
        
#         logger.info("✅ Task Finished!")
#         # --- FINAL UPDATE ---
#         notifier.send_update("completed", 100, "Documentation Ready!")
#         return "Done"

#     except Exception as e:
#         logger.error(f"❌ Worker Failed: {e}", exc_info=True)
#         notifier.send_update("failed", 0, f"Error: {str(e)}") # <--- Fail Update
#         video.status = "failed"
#         db.commit()
#         return f"Error: {e}"
#     finally:
#         db.close()
        
# # Cleaning TASK 
# @celery_app.task
# def cleanup_temp_data():
#     """
#     Periodic Janitor Task:
#     Scans the 'temp_data' directory and deletes folders older than a specific time limit.
#     This prevents the server disk from getting full.
#     """
#     logger.info("🧹 Janitor Started: Scanning for old files to clean...")
    
#     temp_dir = "temp_data"
    
#     # --- TIME LIMIT CONFIGURATION ---
#     # Files older than this (in seconds) will be deleted.
#     # 3600 seconds = 1 Hour
#     # "schedule": 60.0,   # Run every 1 Minute (For Quick Testing)
#     # "schedule": 86400.0 # Run every 1 Day (24 Hours)
#     AGE_LIMIT_SECONDS = 3600 
    
#     if not os.path.exists(temp_dir):
#         logger.info("✅ Temp directory does not exist. Nothing to clean.")
#         return

#     current_time = time.time()
#     deleted_count = 0

#     # Iterate through folders in temp_data
#     for item in os.listdir(temp_dir):
#         item_path = os.path.join(temp_dir, item)
        
#         # Only check directories (e.g., temp_data/82/)
#         if os.path.isdir(item_path):
#             try:
#                 # Check last modification time
#                 folder_mtime = os.path.getmtime(item_path)
                
#                 # If folder is older than limit, delete it
#                 if current_time - folder_mtime > AGE_LIMIT_SECONDS:
#                     logger.info(f"🗑️ Found old junk: {item_path}. Deleting...")
#                     shutil.rmtree(item_path) # Recursive delete
#                     deleted_count += 1
#             except Exception as e:
#                 logger.error(f"❌ Could not delete {item_path}: {e}")

#     logger.info(f"✅ Janitor Finished: Cleaned up {deleted_count} old folders.")