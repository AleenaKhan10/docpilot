from services.processing import extract_audio
from services.gemini_service import transcribe_audio_gemini # <--- Naya Import
import os

VIDEO_FILE = "test_video.mp4" 
OUTPUT_DIR = "temp_output"
AUDIO_FILE = os.path.join(OUTPUT_DIR, "audio.mp3")

# Setup Folders
os.makedirs(OUTPUT_DIR, exist_ok=True)

print("🚀 Starting Beast Mode Test (Gemini Edition)...")

# 1. Audio Nikalo
if not os.path.exists(AUDIO_FILE):
    print("🔊 Extracting Audio...")
    extract_audio(VIDEO_FILE, AUDIO_FILE)
else:
    print("⏩ Audio already exists, skipping extraction.")

# 2. Transcribe Karo (Gemini)
print("📝 Transcribing with Gemini Flash...")
try:
    segments = transcribe_audio_gemini(AUDIO_FILE)
    
    print("\n✅ Transcription Success! Here is what Gemini heard:")
    print("-" * 40)
    for seg in segments:
        # Gemini kabhi kabhi start/end string mein deta hai, kabhi float
        start = seg.get('start')
        end = seg.get('end')
        text = seg.get('text')
        print(f"[{start}s - {end}s]: {text}")
    print("-" * 40)

except Exception as e:
    print(f"❌ Gemini Error: {e}")
    print("Check karo: .env mein GOOGLE_API_KEY sahi hai?")