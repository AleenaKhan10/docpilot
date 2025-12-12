import os
from config import Settings

settings = Settings()

google_url = settings.GOOGLE_API_KEY
print(f"Redis URL: {google_url}")

openrouter_api_key_check = settings.OPENROUTER_API_KEY
print(f"OpenRouter API Key: {openrouter_api_key_check}")

