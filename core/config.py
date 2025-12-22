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
    
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30 # Standard session time (Bank apps use 5-15 mins)
    
    # --- API KEYS ---
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY")
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL")
    NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY")
    MODEL_NAME : str = os.getenv("MODEL_NAME")

settings = Settings()