import os
from pathlib import Path
from dotenv import load_dotenv

# 1. Base Directory Setup (Backend Folder ka raasta)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv()

class Settings:
    # --- SYSTEM PATHS ---
    BASE_DIR: str = str(BASE_DIR)  # Yeh Logger use karega
    
    # --- PROJECT SETTINGS ---
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "VideoDocs AI")
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    SECRET_KEY: str = os.getenv("SECRET_KEY")
    REDIS_URL: str = os.getenv("REDIS_URL")

    # --- API KEYS ---
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY")
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL")
    NVIDIA_API_KEY:str = os.getenv("NVIDIA_API_KEY")
    NVIDIA_MODEL_NAME:str = os.getenv("NVIDIA_MODEL_NAME")

settings = Settings()