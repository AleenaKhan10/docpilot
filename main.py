from fastapi import FastAPI
from core.config import settings
from db.session import engine, Base
import models 

# Humara naya simple route import
from routes import video 

# Tables check/create
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.PROJECT_NAME)

# --- Routes Register Karna ---
# Yahan hum prefix laga rahe hain, taake URL banay: /api/v1/videos
app.include_router(video.router, prefix="/api/v1/videos", tags=["Videos"])

@app.get("/")
def health_check():
    return {"status": "Welcome to VideoDocs AI"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)