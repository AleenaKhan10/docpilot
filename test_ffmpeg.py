from services.processing import extract_audio, extract_frames
import os

# Video ka naam jo tumne folder mein rakhi hai
VIDEO_FILE = "test_video.mp4" 

# Kahan save karna hai?
OUTPUT_DIR = "temp_output"
AUDIO_FILE = os.path.join(OUTPUT_DIR, "audio.mp3")
FRAMES_DIR = os.path.join(OUTPUT_DIR, "frames")

# Directory banao
os.makedirs(OUTPUT_DIR, exist_ok=True)

print("🚀 Starting Processing...")

# 1. Audio Nikalo
print("1. Extracting Audio...")
try:
    extract_audio(VIDEO_FILE, AUDIO_FILE)
    print(f"✅ Audio Saved: {AUDIO_FILE}")
except Exception as e:
    print(f"❌ Audio Error: {e}")

# 2. Frames Nikalo
print("2. Extracting Frames...")
try:
    extract_frames(VIDEO_FILE, FRAMES_DIR, interval=2) # Har 2 second baad frame
    print(f"✅ Frames Saved in: {FRAMES_DIR}")
except Exception as e:
    print(f"❌ Frame Error: {e}")

print("🎉 DONE! Check temp_output folder.")