import os
import json
from core.celery_app import celery_app
from db.session import SessionLocal
from models.video import Video
from models.step import Step
from services.processing import extract_audio, extract_frames
from services.gemini_service import transcribe_audio_gemini, generate_documentation_steps

@celery_app.task(bind=True)
def process_video_task(self, video_id: int, video_path: str):
    print(f"🚀 Worker Started: Processing Video ID {video_id}")
    
    db = SessionLocal()
    video = db.query(Video).filter(Video.id == video_id).first()
    
    if not video:
        print("❌ Video not found in DB")
        return "Failed"

    video.status = "processing"
    db.commit()

    try:
        # 1. Setup Folders
        base_dir = f"temp_data/{video_id}"
        os.makedirs(base_dir, exist_ok=True)
        
        audio_path = os.path.join(base_dir, "audio.mp3")
        frames_dir = os.path.join(base_dir, "frames")

        # 2. FFmpeg Processing
        print("⚙️ Splitting Video...")
        extracted_audio_path = extract_audio(video_path, audio_path)
        extract_frames(video_path, frames_dir, interval=2)

        # 3. Transcription
        transcript = []
        if extracted_audio_path:
            print("🔊 Transcribing...")
            transcript = transcribe_audio_gemini(extracted_audio_path)
        else:
            print("🔇 Silent Video detected.")

        # 4. Generate Steps
        print("🤖 Generating Documentation...")
        final_steps = generate_documentation_steps(transcript, frames_dir, interval=2)

        # --- IMPORTANT: SAVE JSON FILE FOR CHECKING ---
        json_path = os.path.join(base_dir, "documentation.json")
        with open(json_path, "w") as f:
            json.dump(final_steps, f, indent=4)
        print(f"📂 JSON Saved: {json_path}")
        # ----------------------------------------------

        # 5. Save to Database
        print(f"💾 Saving {len(final_steps)} steps to DB...")
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
        print("✅ Task Finished Successfully!")
        return "Done"

    except Exception as e:
        print(f"❌ Worker Failed: {e}")
        video.status = "failed"
        db.commit()
        return f"Error: {e}"
    finally:
        db.close()