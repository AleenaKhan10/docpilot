import os
from openai import OpenAI
from core.config import settings

# OpenAI Client initialize karo
client = OpenAI(api_key=settings.OPENAI_API_KEY)

def transcribe_audio(audio_path: str):
    """
    Audio file leta hai aur text segments wapis karta hai timestamps ke sath.
    """
    print("🧠 AI Hearing: Transcribing audio...")
    
    with open(audio_path, "rb") as audio_file:
        # Whisper Model Call
        transcript = client.audio.transcriptions.create(
            model="whisper-1", 
            file=audio_file,
            response_format="verbose_json", # Humein timestamps chahiye
            timestamp_granularities=["segment"] # Segments best hain
        )
    
    # Humein sirf kaam ka data wapis bhejna hai
    segments = []
    for segment in transcript.segments:
        segments.append({
            "start": segment.start,
            "end": segment.end,
            "text": segment.text.strip()
        })
        
    return segments