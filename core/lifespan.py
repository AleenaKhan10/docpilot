"""
Application lifecycle hooks.

Startup task: heartbeat-based zombie reaper. Only marks a `processing`
video as failed if its worker hasn't checked in for HEARTBEAT_STALE_SECONDS.
A worker still alive on its heartbeat keeps its in-flight job intact even
through a rolling API restart.

Schema migrations are now owned by Alembic (`alembic upgrade head`); the
old self-applying ALTER TABLE shim is gone.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI

from core.logger import setup_logging
from db.session import SessionLocal
from models.video import Video

logger = setup_logging()

HEARTBEAT_STALE_SECONDS = 5 * 60  # 5 min — well above any single VLM call


def _reap_stale_zombies() -> None:
    db = SessionLocal()
    try:
        stale_cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=HEARTBEAT_STALE_SECONDS
        )
        zombies = (
            db.query(Video)
            .filter(
                Video.status == "processing",
                (Video.worker_heartbeat_at.is_(None))
                | (Video.worker_heartbeat_at < stale_cutoff),
            )
            .all()
        )
        if not zombies:
            logger.info("Lifespan reaper: no stale in-flight videos.")
            return

        ids = [v.id for v in zombies]
        for v in zombies:
            v.status = "failed"
        db.commit()
        logger.warning(
            f"Lifespan reaper: marked {len(zombies)} stale-heartbeat videos as failed "
            f"(ids={ids})"
        )
    except Exception as e:
        logger.error(f"Lifespan reaper failed: {e}")
        db.rollback()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Startup: reaping stale tasks…")
    _reap_stale_zombies()
    logger.info("Startup complete.")
    yield
    logger.info("Shutdown: closing connections.")
