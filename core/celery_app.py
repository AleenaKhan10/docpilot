import ssl
from celery import Celery
from celery.schedules import crontab # <--- Import for Scheduling
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
    broker=broker_url,   
    backend=broker_url,  
    include=["workers.tasks"]
)

# --- CELERY CONFIGURATION ---
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    
    # SSL Settings (KEPT AS IS)
    broker_use_ssl={'ssl_cert_reqs': ssl.CERT_NONE},
    redis_backend_use_ssl={'ssl_cert_reqs': ssl.CERT_NONE},

    # --- THE JANITOR SCHEDULE (NEW) ---
    beat_schedule={
        "run-janitor-every-hour": {
            "task": "workers.tasks.cleanup_temp_data",
            # Run every 3600 seconds (1 Hour)
            "schedule": 3600.0, 
            # "schedule": 60.0,   # Run every 1 Minute (For Quick Testing)
            # "schedule": 86400.0 # Run every 1 Day (24 Hours)
        },
    }
)