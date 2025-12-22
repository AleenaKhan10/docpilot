import shutil
import os
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List

# Import Internal Modules
from db.session import get_db
from models.video import Video
from models.user import User
from models.step import Step
from workers.tasks import process_video_task
from utils.validators import validate_video_file_signature
from core.limiter import limiter
from schemas.video import VideoResponse
from api.debs import get_current_user # <--- THE GUARD 👮‍♂️

router = APIRouter()

# --- 1. UPLOAD VIDEO (Protected) ---
@router.post("/", response_model=VideoResponse)
@limiter.limit("5/minute")
async def create_video(
    request: Request,
    background_tasks: BackgroundTasks, # Best practice for heavy tasks
    title: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    # --- SECURITY CHECK ---
    # User must be logged in. 'current_user' will have their ID.
    current_user: User = Depends(get_current_user)
):
    """
    Upload a video and start processing.
    Requires Authentication.
    """
    
    # A. Validate File Signature (Security)
    await validate_video_file_signature(file)

    # B. Create Initial DB Entry (Pending)
    # Status is 'pending' until file is saved
    new_video = Video(
        title=title,
        video_url="", # Will update after saving
        user_id=current_user.id, # Link to REAL user
        status="pending"
    )
    db.add(new_video)
    db.commit()
    db.refresh(new_video)

    # C. Save File to Disk (Unique Storage Logic)
    # Structure: temp_data/{video_id}/input.mp4
    # Using 'video_id' as folder name keeps things organized per job.
    upload_dir = f"temp_data/{new_video.id}"
    os.makedirs(upload_dir, exist_ok=True)
    
    # Consistent filename helps the worker know what to look for
    saved_file_path = os.path.join(upload_dir, "input.mp4")
    
    try:
        with open(saved_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Update DB with path (Optional, but good for tracking)
        new_video.video_url = saved_file_path
        db.commit()
        
    except Exception as e:
        # Rollback: Clean DB if file save fails
        db.delete(new_video)
        db.commit()
        # Clean folder if created
        if os.path.exists(upload_dir):
            shutil.rmtree(upload_dir)
        raise HTTPException(status_code=500, detail=f"Failed to save video: {str(e)}")

    # D. Trigger Worker (Async)
    # Using .delay() to send task to Redis Queue
    process_video_task.delay(new_video.id, saved_file_path)

    # Return Response immediately (Worker runs in background)
    return new_video

# --- 2. GET VIDEO DETAILS (Public/Protected logic depends on requirements) ---
# For now, we allow anyone to view details if they have the ID.
# Enterprise update: You might want to restrict this to 'current_user' too.
@router.get("/{video_id}", response_model=VideoResponse)
def get_video_details(
    video_id: int, 
    request: Request,
    db: Session = Depends(get_db),
    # Optional: Add 'current_user' here if you want to block others viewing your video
    # current_user: User = Depends(get_current_user) 
):
    """
    Get full details of a video including Steps and PDF Link.
    Converts local paths to Public URLs.
    """
    # 1. Fetch Video
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # 2. Dynamic Base URL
    base_url = str(request.base_url).rstrip("/") 
    
    # 3. Format Steps (Convert Paths to URLs)
    formatted_steps = []
    # Using 'steps' relationship directly (More Efficient)
    # Sorting ensures order 1, 2, 3...
    
    # Explicitly querying to ensure sorting
    steps = db.query(Step).filter(Step.video_id == video_id).order_by(Step.step_number).all()

    for step in steps:
        # Handling Image URL (Local to Web conversion)
        full_image_url = None
        if step.image_url:
            clean_path = step.image_url.replace("\\", "/")
            if clean_path.startswith("temp_data/"):
                public_path = clean_path.replace("temp_data/", "downloads/", 1)
                full_image_url = f"{base_url}/{public_path}"
            else:
                full_image_url = step.image_url

        formatted_steps.append({
            "step_number": step.step_number,
            "timestamp": step.timestamp if step.timestamp is not None else 0.0,
            "description": step.description,
            "image_url": full_image_url or "" # Ensure string
        })

    # 4. PDF Link Logic
    pdf_link = None
    if video.status == "completed":
        # Check if file actually exists before sending link (Safety check)
        local_pdf_path = f"temp_data/{video.id}/manual.pdf"
        if os.path.exists(local_pdf_path):
            pdf_link = f"{base_url}/downloads/{video.id}/manual.pdf"

    return {
        "id": video.id,
        "title": video.title,
        "status": video.status,
        "created_at": video.created_at,
        "pdf_url": pdf_link,
        "steps": formatted_steps
    }
    
# --- 3. GET ALL MY VIDEOS (Dashboard) ---
@router.get("/", response_model=List[VideoResponse]) # Return List
def get_my_videos(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Just Logged in User Data
):
    """
    Fetch all videos uploaded by the logged-in user.
    Sorted by newest first.
    """
    # Magic Filter: User ID match karo
    videos = db.query(Video)\
        .filter(Video.user_id == current_user.id)\
        .order_by(Video.created_at.desc())\
        .all()
        
    # Note: Pydantic (VideoResponse) automatically data format kar dega
    # URL conversion logic humein yahan bhi lagana padega agar hum list mein bhi 
    # PDF link dikhana chahte hain. 
    # (Filhal simple return karte hain, frontend detail page par PDF mangega)
    
    # Lekin humare Schema mein 'pdf_url' hai, tow humein manually loop chalana padega
    # taake URL generate ho sake.
    
    results = []
    # (Humein base_url chahiye hoga, request object pass karna padega function mein)
    # ...
    
    return videos # Simple return (URLs raw aayenge, jo theek hai dashboard ke liye)
    
