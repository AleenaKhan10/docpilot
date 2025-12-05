import os
from config import Settings

settings = Settings()

redis_url = settings.REDIS_URL
print(f"Redis URL: {redis_url}")