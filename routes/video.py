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
from api.debs import get_current_user, require_org # <--- MULTI-TENANCY GUARDS 👮‍♂️

router = APIRouter()

# --- 1. UPLOAD VIDEO (Protected, Org-Level) ---
@router.post("/", response_model=VideoResponse)
@limiter.limit("5/minute")
async def create_video(
    request: Request,
    background_tasks: BackgroundTasks,
    title: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    # --- SECURITY CHECK ---
    # User must belong to an organization to upload
    current_user: User = Depends(require_org)
):
    """
    Upload a video and start processing.
    Requires Authentication + Organization Membership.
    """
    
    # A. Validate File Signature
    await validate_video_file_signature(file)

    # B. Create Initial DB Entry (Pending)
    new_video = Video(
        title=title,
        video_url="", 
        user_id=current_user.id,        # Who uploaded
        org_id=current_user.org_id,     # --- MULTI-TENANCY ISOLATION ---
        status="pending"
    )
    db.add(new_video)
    db.commit()
    db.refresh(new_video)

    # C. Save File to Disk
    upload_dir = f"temp_data/{new_video.id}"
    os.makedirs(upload_dir, exist_ok=True)
    saved_file_path = os.path.join(upload_dir, "input.mp4")
    
    try:
        with open(saved_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        new_video.video_url = saved_file_path
        db.commit()
        
    except Exception as e:
        db.delete(new_video)
        db.commit()
        if os.path.exists(upload_dir):
            shutil.rmtree(upload_dir)
        raise HTTPException(status_code=500, detail=f"Failed to save video: {str(e)}")

    # D. Trigger Worker (Async)
    process_video_task.delay(new_video.id, saved_file_path)

    return new_video

# --- 2. GET VIDEO DETAILS (Protected, Org-Level) ---
@router.get("/{video_id}", response_model=VideoResponse)
def get_video_details(
    video_id: int, 
    request: Request,
    db: Session = Depends(get_db),
    # --- SECURITY CHECK ---
    # User must belong to an organization
    current_user: User = Depends(require_org) 
):
    """
    Get full details of a video including Steps and PDF Link.
    Protected: User can only view videos from their own organization.
    """
    # 1. Fetch Video
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # --- MULTI-TENANCY DATA ISOLATION GUARD ---
    if video.org_id != current_user.org_id:
        raise HTTPException(status_code=403, detail="Access denied. Video belongs to another organization.")

    # 2. Dynamic Base URL
    base_url = str(request.base_url).rstrip("/") 
    
    # 3. Format Steps
    formatted_steps = []
    steps = db.query(Step).filter(Step.video_id == video_id).order_by(Step.step_number).all()

    for step in steps:
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
            "image_url": full_image_url or ""
        })

    # 4. PDF Link Logic
    pdf_link = None
    if video.status == "completed":
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
    
# --- 3. GET ALL ORGANIZATION VIDEOS (Dashboard) ---
@router.get("/", response_model=List[VideoResponse])
def get_org_videos(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_org) # Must belong to an org
):
    """
    Fetch all videos belonging to the user's organization.
    Sorted by newest first.
    """
    # --- MULTI-TENANCY ISOLATION ---
    # Query by org_id instead of user_id, so team members can see org videos
    videos = db.query(Video)\
        .filter(Video.org_id == current_user.org_id)\
        .order_by(Video.created_at.desc())\
        .all()
        
    return videos
    
