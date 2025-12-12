import os
import time
from faster_whisper import WhisperModel

# --- CONFIGURATION ---
# Base Model is best for production (Speed vs Accuracy)
# If need too fast then 'tiny', if need too accurate then 'small'
# Agar bohot fast chahiye to 'tiny', agar bohot accurate chahiye to 'small' use karo.
MODEL_SIZE = "base"


DEVICE = "cpu"
COMPUTE_TYPE = "int8"

print(f"⏳ Loading Faster-Whisper model ({MODEL_SIZE})...")

try:
    # Loads model into the memory (Global Instance)
    # It downloads the model on first run
    model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    print("✅ Faster-Whisper model loaded successfully!")
except Exception as e:
    print(f"❌ Error loading model: {e}")
    model = None

def transcribe_audio_local(audio_path: str):
    """
    Transcribes audio using Faster-Whisper.
    """
    if not model:
        print("❌ Model not loaded, skipping transcription.")
        return []

    if not os.path.exists(audio_path):
        print(f"❌ Audio file not found: {audio_path}")
        return []

    print(f"🎧 Starting Optimized Transcription for: {audio_path}")
    start_time = time.time()
    
    try:
        # Beam Size 5 = Behtar Accuracy (multiple paths explore)
        segments, info = model.transcribe(audio_path, beam_size=5)
        
        transcript_data = []
        
        print(f"   ℹ️ Detected language: '{info.language}' (Probability: {info.language_probability:.2f})")

        # Faster-Whisper generator return karta hai, loop chalana zaroori hai
        for segment in segments:
            transcript_data.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip()
            })
            
        duration = time.time() - start_time
        print(f"✅ Transcription complete in {duration:.2f}s! Found {len(transcript_data)} segments.")
        return transcript_data

    except Exception as e:
        print(f"❌ Transcription failed: {e}")
        return []