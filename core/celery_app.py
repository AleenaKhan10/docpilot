import ssl
from celery import Celery
from core.config import settings

# --- SAFETY LOCK: Force 'rediss://' for Upstash ---
broker_url = settings.REDIS_URL
if broker_url and broker_url.startswith("redis://"):
    print("⚠️ WARNING: Fixing URL scheme from 'redis://' to 'rediss://' for SSL")
    broker_url = broker_url.replace("redis://", "rediss://", 1)
# --------------------------------------------------

print(f"🔗 Celery Connecting to: {broker_url}")

celery_app = Celery(
    "video_docs_worker",
    broker=broker_url,   # Use the fixed variable
    backend=broker_url,  # Use the fixed variable
    include=["workers.tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    
    # SSL Settings
    broker_use_ssl={'ssl_cert_reqs': ssl.CERT_NONE},
    redis_backend_use_ssl={'ssl_cert_reqs': ssl.CERT_NONE}
)

