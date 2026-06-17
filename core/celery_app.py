import ssl
from celery import Celery
from core.config import settings
from core.logger import setup_logging

logger = setup_logging()

broker_url = settings.REDIS_URL or "redis://localhost:6379/0"
use_ssl = broker_url.startswith("rediss://")

logger.info(f"Celery broker: {broker_url} (ssl={use_ssl})")

celery_app = Celery(
    "docpilot_worker",
    broker=broker_url,
    backend=broker_url,
    include=["workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_time_limit=900,  # 15 min hard kill
    task_soft_time_limit=780,  # 13 min soft warning
    beat_schedule={
        "run-janitor-every-hour": {
            "task": "workers.tasks.cleanup_temp_data",
            "schedule": 3600.0,
        },
    },
)

if use_ssl:
    celery_app.conf.broker_use_ssl = {"ssl_cert_reqs": ssl.CERT_NONE}
    celery_app.conf.redis_backend_use_ssl = {"ssl_cert_reqs": ssl.CERT_NONE}
