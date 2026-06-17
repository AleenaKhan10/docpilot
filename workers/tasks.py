import json
import logging
import os
import shutil
import time

from core.celery_app import celery_app
from core.storage import (
    frame_key_for_video,
    pdf_key_for_video,
    upload_local_file,
)
from db.session import SessionLocal
from models.video import Video
from models.step import Step
from services.audio_service import transcribe_audio_local
from services.gemini_service import generate_structured_document
from services.pdf_service import generate_pdf_report
from services.processing import extract_audio, extract_frames
from utils.socket_manager import ProgressNotifier, clear_heartbeat

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def process_video_task(self, video_id: int, video_path: str):
    """Two-pass video → document pipeline.

    Stages (also broadcast to the WS channel):
      5%   started
     10%   splitting
     30%   splitting done
     40%   transcribing
     60%   transcription done
     65%   pass1 (per-frame observations)
     80%   pass2 (editorial synthesis → Document)
     90%   saving to DB
     95%   PDF rendering
    100%   completed
    """
    logger.info(f"Worker started: video {video_id}")
    notifier = ProgressNotifier(video_id)
    notifier.send_update("started", 5, "Worker has started processing...")

    db = SessionLocal()
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        logger.error(f"Video {video_id} not found; aborting task")
        clear_heartbeat(video_id)
        db.close()
        return "Failed"

    video.status = "processing"
    db.commit()

    base_dir = f"temp_data/{video_id}"

    try:
        os.makedirs(base_dir, exist_ok=True)
        audio_path = os.path.join(base_dir, "audio.mp3")
        frames_dir = os.path.join(base_dir, "frames")

        # --- 1. Split: audio + frames ---
        notifier.send_update("splitting", 10, "Splitting video into frames...")
        extracted_audio_path = extract_audio(video_path, audio_path)
        extract_frames(video_path, frames_dir, interval=1)
        notifier.send_update("splitting", 30, "Frames extracted.")

        # --- 2. Transcribe (Whisper, local) ---
        transcript = []
        if extracted_audio_path:
            notifier.send_update("transcribing", 40, "Transcribing audio with Whisper...")
            transcript = transcribe_audio_local(extracted_audio_path)
        notifier.send_update("transcribing", 60, "Transcription complete.")

        # --- 3. Two-pass document synthesis ---
        notifier.send_update("generating", 65, "Reading frames (pass 1)...")
        notifier.send_update("generating", 75, "Writing structured document (pass 2)...")
        document = generate_structured_document(
            transcript=transcript,
            frames_dir=frames_dir,
            user_context=video.user_context,
            output_type=video.output_type or "sop",
            interval=1,
        )

        # Persist raw output for debugging.
        with open(os.path.join(base_dir, "documentation.json"), "w", encoding="utf-8") as f:
            json.dump(document, f, indent=2, ensure_ascii=False)

        # --- 4. Save to DB ---
        notifier.send_update("saving", 90, "Saving document...")
        video.document_json = document

        # Also persist a legacy flat-step view so the existing PDF renderer
        # and the frontend's fallback mapper still work. One DB Step per
        # `step` block found in the document.
        flat_steps = _flatten_document_to_steps(document, frames_dir)
        for step_data in flat_steps:
            db.add(
                Step(
                    video_id=video_id,
                    step_number=step_data["step_number"],
                    timestamp=step_data.get("timestamp"),
                    title=step_data.get("title"),
                    description=step_data["description"],
                    tip=step_data.get("tip"),
                    note=step_data.get("note"),
                    explanation=step_data.get("explanation"),
                    section_summary=step_data.get("section_summary"),
                    url=step_data.get("url"),
                    image_url=step_data.get("image_path"),
                )
            )

        # --- 5. PDF render ---
        try:
            notifier.send_update("generating_pdf", 95, "Rendering PDF...")
            pdf_path = os.path.join(base_dir, "manual.pdf")

            class StepMock:
                def __init__(self, data):
                    self.step_number = data.get("step_number")
                    self.timestamp = data.get("timestamp")
                    self.description = data.get("description")
                    self.title = data.get("title") or "General"
                    self.tip = data.get("tip")
                    self.url = data.get("url")
                    self.explanation = data.get("explanation")
                    self.note = data.get("note")
                    self.section_summary = data.get("section_summary")

            generate_pdf_report(video, [StepMock(s) for s in flat_steps], pdf_path)
            logger.info(f"PDF written: {pdf_path}")
        except Exception as pdf_error:
            logger.error(f"PDF generation failed: {pdf_error}", exc_info=True)

        # --- 5b. Persist artifacts to Supabase Storage ---
        # Move PDF + frames that are actually referenced in the doc into
        # storage so they survive the temp_data janitor and stay accessible
        # after the local copy is cleaned up.
        try:
            notifier.send_update("generating_pdf", 97, "Uploading to storage...")
            pdf_local = os.path.join(base_dir, "manual.pdf")
            if os.path.exists(pdf_local):
                key = pdf_key_for_video(video_id)
                upload_local_file(pdf_local, key, content_type="application/pdf")
                video.pdf_storage_path = key

            # Walk document for image-block frame_id refs; upload those.
            frame_map: dict[str, str] = {}
            for section in document.get("sections", []):
                for block in section.get("blocks", []):
                    if block.get("type") == "image" and block.get("frame_id"):
                        fid = block["frame_id"]
                        if fid in frame_map:
                            continue
                        frame_local = os.path.join(frames_dir, f"{fid}.jpg")
                        if os.path.exists(frame_local):
                            key = frame_key_for_video(video_id, fid)
                            upload_local_file(frame_local, key, content_type="image/jpeg")
                            frame_map[fid] = key
            if frame_map:
                video.frame_storage_paths = frame_map
        except Exception as storage_err:
            # Storage upload failure is non-fatal — local serving + signed URLs
            # still work via the legacy temp_data path until janitor runs.
            logger.error(f"Storage upload failed for video {video_id}: {storage_err}", exc_info=True)

        video.status = "completed"
        db.commit()
        notifier.send_update("completed", 100, "Documentation ready.")
        logger.info(f"Worker finished: video {video_id}")
        return "Done"

    except Exception as e:
        logger.error(f"Worker failed for video {video_id}: {e}", exc_info=True)
        notifier.send_update("failed", 0, "Processing failed. Check server logs.")
        video.status = "failed"
        db.commit()
        return f"Error: {e}"
    finally:
        clear_heartbeat(video_id)
        db.close()


def _flatten_document_to_steps(document: dict, frames_dir: str) -> list[dict]:
    """Project a Document {sections:[{blocks:[...]}]} down to a flat list of
    Step rows for the legacy PDF renderer + fallback mapper.

    One row per `step` block. Nearby callouts/links get folded into the
    step's tip/note/url fields. Section heading becomes step.title.
    """
    flat: list[dict] = []
    step_number = 0
    for section in document.get("sections", []):
        heading = (section.get("heading") or "").strip()
        intro = (section.get("intro") or "").strip()
        section_summary_used = False

        blocks = section.get("blocks") or []
        # First pass: collect callouts and links so we can attach them
        # to the nearest preceding step.
        for i, block in enumerate(blocks):
            btype = block.get("type")
            if btype != "step":
                continue
            step_number += 1

            # Look ahead for the next non-step block (tip/note/link/image).
            tip = note = url = None
            image_path = None
            for j in range(i + 1, min(i + 4, len(blocks))):
                neighbor = blocks[j]
                ntype = neighbor.get("type")
                if ntype == "step":
                    break
                if ntype == "callout":
                    if neighbor.get("kind") == "tip":
                        tip = neighbor.get("text")
                    elif neighbor.get("kind") in ("note", "warning", "danger"):
                        note = neighbor.get("text")
                elif ntype == "link":
                    url = neighbor.get("url")
                elif ntype == "image" and neighbor.get("frame_id"):
                    image_path = os.path.join(frames_dir, f"{neighbor['frame_id']}.jpg").replace("\\", "/")

            # Use the step's own image_ref if present.
            if not image_path and block.get("frame_id"):
                image_path = os.path.join(frames_dir, f"{block['frame_id']}.jpg").replace("\\", "/")

            flat.append(
                {
                    "step_number": step_number,
                    "timestamp": block.get("timestamp_seconds"),
                    "title": heading or None,
                    "section_summary": intro if not section_summary_used else None,
                    "description": (block.get("title") or "").strip()
                    + ((". " + block["detail"]) if block.get("detail") else ""),
                    "explanation": block.get("detail") if block.get("title") else None,
                    "tip": tip,
                    "note": note,
                    "url": url,
                    "image_path": image_path,
                }
            )
            section_summary_used = True
    return flat


@celery_app.task
def cleanup_temp_data():
    """Janitor: deletes folders in temp_data older than AGE_LIMIT_SECONDS."""
    logger.info("Janitor started")
    temp_dir = "temp_data"
    AGE_LIMIT_SECONDS = 3600

    if not os.path.exists(temp_dir):
        return

    now = time.time()
    deleted = 0
    for item in os.listdir(temp_dir):
        item_path = os.path.join(temp_dir, item)
        if not os.path.isdir(item_path):
            continue
        try:
            if now - os.path.getmtime(item_path) > AGE_LIMIT_SECONDS:
                shutil.rmtree(item_path)
                deleted += 1
        except Exception as e:
            logger.error(f"Janitor could not delete {item_path}: {e}")
    logger.info(f"Janitor finished: {deleted} folder(s) cleaned")
