# Imports
from fastapi import FastAPI
from routes import video
from db.session import engine
from models import video as video_model
from core.logger import setup_logging  # To setup logger, we need to import it
from fastapi.middleware.cors import CORSMiddleware # Importing CORMiddleware from fastapi.middlewares.cors 
from routes import websocket as websocket_router # Importing WebSocket Router to setup WebSockets
from slowapi import _rate_limit_exceeded_handler # 
from slowapi.errors import RateLimitExceeded     # Exception when a rate limit is exceeded
from core.limiter import limiter                 # The One we setup in the limiter.py
from core.lifespan import lifespan
from fastapi.staticfiles import StaticFiles


# Setup Logging (First)
logger = setup_logging()
logger.info("🚀 System Startup: Logger Initialized Successfully!")

# Create Tables
video_model.Base.metadata.create_all(bind=engine)

# FastAPI App and Name
app = FastAPI(title="VideoDocs AI", lifespan=lifespan)

# RATE LIMITER SETUP ---
app.state.limiter = limiter 

# If the limit is crosses, this handler will be called
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Static Files Serving
app.mount("/downloads", StaticFiles(directory="temp_data"), name="downloads")

# Registered Routes
app.include_router(video.router, prefix="/api/v1/videos", tags=["videos"])
app.include_router(websocket_router.router, tags=["websockets"]) 

# CORS Configuration
origins = [
    "http://localhost:3000",  # React/Next.js default port
    "http://localhost:5173",  # Vite default port
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,      # Sirf in domains ko allow karo
    allow_credentials=True,     # Cookies/Tokens allow karo
    allow_methods=["*"],        # GET, POST, PUT, DELETE sab allow karo
    allow_headers=["*"],        # Saare headers allow karo
)

@app.get("/")
def read_root():
    logger.info("Health check endpoint accessed.")
    return {"message": "VideoDocs AI Backend is Running!"}