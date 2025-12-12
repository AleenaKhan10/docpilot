import logging
import os
from logging.handlers import TimedRotatingFileHandler
from core.config import settings

def setup_logging():
    """
    Configures Time-Based Logging.
    - Active Log: 'app.log'
    - Rotated Logs: 'app.log.DD-MM-YYYY' (e.g., app.log.13-12-2025)
    - Retention: Keeps last 7 days only.
    """
    
    log_dir = os.path.join(settings.BASE_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    log_file_path = os.path.join(log_dir, "app.log")

    # --- FORMAT UPDATE: DD-MM-YYYY ---
    log_formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%d-%m-%Y %H:%M:%S"
    )

    # --- HANDLER SETUP ---
    file_handler = TimedRotatingFileHandler(
        filename=log_file_path,
        when="midnight",    # Every Night at 12 am
        interval=1,         # Every Day
        backupCount=7,      # 7 days old file delete
        encoding="utf-8"
    )
    
    # --- SUFFIX UPDATE: File name format change ---
    file_handler.suffix = "%d-%m-%Y" 
    
    file_handler.setFormatter(log_formatter)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    if not root_logger.hasHandlers():
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
    
    logging.getLogger("uvicorn.access").handlers = [console_handler, file_handler]
    logging.getLogger("celery").handlers = [console_handler, file_handler]

    return root_logger