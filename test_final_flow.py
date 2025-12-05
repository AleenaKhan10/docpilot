from services.processing import extract_audio, extract_frames
from services.gemini_service import transcribe_audio_gemini, generate_documentation_steps
import os
import json

# ==========================================
# KOI BHI VIDEO DALO (SILENT YA AUDIO WALI)
VIDEO_FILE = "tutorial_video.mp4" 
# ==========================================

OUTPUT_DIR = "final_output"
AUDIO_FILE = os.path.join(OUTPUT_DIR, "audio.mp3")
FRAMES_DIR = os.path.join(OUTPUT_DIR, "frames")

os.makedirs(OUTPUT_DIR, exist_ok=True)

print(f"🚀 Processing: {VIDEO_FILE}")

# 1. FFmpeg (Audio shayad nikle, shayad na nikle)
print("\n--- PHASE 1: Processing ---")
audio_path_result = extract_audio(VIDEO_FILE, AUDIO_FILE)
extract_frames(VIDEO_FILE, FRAMES_DIR, interval=2)

# 2. Transcription (Try karo)
transcript = []
if audio_path_result:
    print("🔊 Audio detected. Transcribing...")
    transcript = transcribe_audio_gemini(audio_path_result)
else:
    print("🔇 No Audio detected. Skipping transcription.")

# 3. Generation (Auto-Detect Mode)
print("\n--- PHASE 2: Generating Docs ---")
final_docs = generate_documentation_steps(transcript, FRAMES_DIR, interval=2)

# 4. Result Save
output_json_path = os.path.join(OUTPUT_DIR, "documentation.json")
with open(output_json_path, "w") as f:
    json.dump(final_docs, f, indent=4)

print(f"\n🎉 Done! Generated {len(final_docs)} steps.")
print(f"File: {output_json_path}")

# from services.processing import extract_audio, extract_frames
# from services.gemini_service import transcribe_audio_gemini, generate_documentation_steps
# import os
# import json

# # ==========================================
# # APNI VIDEO FILE KA NAAM YAHAN LIKHO
# VIDEO_FILE = "tutorial_video.mp4" 
# # ==========================================

# OUTPUT_DIR = "final_output"
# AUDIO_FILE = os.path.join(OUTPUT_DIR, "audio.mp3")
# FRAMES_DIR = os.path.join(OUTPUT_DIR, "frames")

# os.makedirs(OUTPUT_DIR, exist_ok=True)

# print("🚀 Starting Mode Test...")

# # 1. Processing (FFmpeg)
# print("\n--- PHASE 1: FFmpeg Processing ---")
# if not os.path.exists(AUDIO_FILE):
#     extract_audio(VIDEO_FILE, AUDIO_FILE)
#     extract_frames(VIDEO_FILE, FRAMES_DIR, interval=2) # Har 2 sec baad frame
#     print("✅ Video Splitted.")
# else:
#     print("⏩ Skipping split (Already done).")

# # 2. Transcription (Gemini Hearing)
# print("\n--- PHASE 2: Transcription ---")
# try:
#     transcript = transcribe_audio_gemini(AUDIO_FILE)
#     print(f"✅ Transcript Generated ({len(transcript)} segments).")
# except Exception as e:
#     print(f"❌ Transcription Failed: {e}")
#     exit()

# # 3. Reasoning (Gemini Vision + Logic)
# print("\n--- PHASE 3: Documentation Generation ---")
# try:
#     final_docs = generate_documentation_steps(transcript, FRAMES_DIR, interval=2)
    
#     # 4. Save Final JSON
#     output_json_path = os.path.join(OUTPUT_DIR, "documentation.json")
#     with open(output_json_path, "w") as f:
#         json.dump(final_docs, f, indent=4)

#     print("\n🎉 MISSION ACCOMPLISHED! 🎉")
#     print(f"Check result in: {output_json_path}")
    
#     # Thora preview dikhao
#     print("\nPreview:")
#     for step in final_docs[:3]: # Pehle 3 steps
#         print(f"Step {step['step_number']}: {step['title']}")
#         print(f" - {step['description']}")
#         print("---")

# except Exception as e:
#     print(f"❌ Generation Error: {e}")