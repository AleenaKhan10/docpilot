import os
from dotenv import load_dotenv

# .env file load karo
load_dotenv()

class Settings:
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "VideoDocs AI")
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    SECRET_KEY: str = os.getenv("SECRET_KEY")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY")
    REDIS_URL: str = os.getenv("REDIS_URL")
    
settings = Settings()