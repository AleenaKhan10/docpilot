from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from db.session import get_db
from models.video import Video
from models.user import User
from pydantic import BaseModel
from workers.tasks import process_video_task # 

router = APIRouter()

class VideoCreate(BaseModel):
    title: str
    video_url: str = "tutorial_video.mp4"
    user_id: int


@router.post("/")
def create_video(video_in: VideoCreate, db: Session = Depends(get_db)):
    # --- OLD LOGIC (BUGGY) ---
    # user = db.query(User).filter(User.id == video_in.user_id).first()
    # if not user:
    #    create new user... (ERROR: Duplicate Email)

    # --- NEW LOGIC (SMART) ---
    # 1. Pehle check karo kya 'test@example.com' wala user exist karta hai?
    # (Real app mein hum token se user nikalenge, abhi hardcode kar rahe hain)
    
    HARDCODED_EMAIL = "test@example.com"
    
    user = db.query(User).filter(User.email == HARDCODED_EMAIL).first()
    
    if not user:
        # Agar bilkul pehli baar aye ho to user banao
        user = User(email=HARDCODED_EMAIL, full_name="Test User")
        db.add(user)
        db.commit()
        db.refresh(user)
        

    # 2. Save Video
    new_video = Video(
        title=video_in.title,
        video_url=video_in.video_url,
        user_id=user.id, # Yahan hum database wala asli ID use karenge
        status="pending"
    )
    db.add(new_video)
    db.commit()
    db.refresh(new_video)
    
    # 3. Trigger Celery Task
    process_video_task.delay(new_video.id, video_in.video_url) 
    
    return {"message": "Video processing started", "video_id": new_video.id}


