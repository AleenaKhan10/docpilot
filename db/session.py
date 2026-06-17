from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from core.config import settings

# Production-grade connection pool:
#   pool_pre_ping=True : test each connection before use; auto-recover from
#                        the pooler closing idle sockets.
#   pool_recycle=1800  : refresh connections every 30 minutes (Supabase
#                        Supavisor pooler trims idle ones around 1 hour).
#   pool_size=10       : default headroom for the FastAPI process.
#   max_overflow=20    : bursty traffic can open up to 30 concurrent.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=10,
    max_overflow=20,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
