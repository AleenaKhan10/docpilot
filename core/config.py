import os
from pathlib import Path
from dotenv import load_dotenv

# 1. Base Directory Setup (Backend Folder ka raasta)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv()

class Settings:
    # --- SYSTEM PATHS ---
    BASE_DIR: str = str(BASE_DIR)  # Logger Will Use This
    
    # --- PROJECT SETTINGS ---
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "VideoDocs AI")
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    REDIS_URL: str = os.getenv("REDIS_URL")

    ALGORITHM: str = "HS256" # Standard JWT algorithm
    SUPABASE_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET", "")
    SUPABASE_URL: str = os.getenv("SUPABASE_URL")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:5173")
    
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30 # Standard session time (Bank apps use 5-15 mins)
    
    # --- API KEYS ---
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY")
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL")
    NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY")
    MODEL_NAME : str = os.getenv("MODEL_NAME")

    # Google Gemini (active VLM)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    # Upload limits (P0)
    MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_UPLOAD_BYTES", 500 * 1024 * 1024))  # 500 MB
    MAX_VIDEO_DURATION_SECONDS: int = int(os.getenv("MAX_VIDEO_DURATION_SECONDS", 30 * 60))  # 30 min
    MAX_VIDEOS_PER_ORG_PER_DAY: int = int(os.getenv("MAX_VIDEOS_PER_ORG_PER_DAY", 20))

settings = Settings()