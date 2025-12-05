from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from core.config import settings

# --- PRODUCTION GRADE CONNECTION SETTINGS ---
engine = create_engine(
    settings.DATABASE_URL,
    # 1. pool_pre_ping=True: Har query se pehle check karega connection zinda hai ya nahi
    pool_pre_ping=True, 
    # 2. pool_recycle=1800: Har 30 min baad connection refresh karega
    pool_recycle=1800,
    # 3. pool_size=10: Aik waqt mein 10 connections open rakhega
    pool_size=10,
    # 4. max_overflow=20: Load barhne par 20 extra connections bana sakega
    max_overflow=20
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()