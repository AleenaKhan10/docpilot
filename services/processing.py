import os
import subprocess

def extract_audio(video_path: str, output_audio_path: str):
    """
    Audio extract karo. Agar audio nahi hai, to None return karo (Crash mat hona).
    """
    try:
        # Pehle check karo ke audio stream hai bhi ya nahi
        probe_command = [
            "ffprobe", "-i", video_path,
            "-show_streams", "-select_streams", "a", "-loglevel", "error"
        ]
        result = subprocess.run(probe_command, capture_output=True, text=True)
        
        # Agar output khali hai, matlab koi audio stream nahi hai
        if not result.stdout.strip():
            print("⚠️ No audio stream found in video.")
            return None

        # Agar audio hai, to extract karo
        command = [
            "ffmpeg", "-i", video_path,
            "-q:a", "0", "-map", "a", "-y", "-loglevel", "error",
            output_audio_path
        ]
        subprocess.run(command, check=True)
        return output_audio_path

    except Exception as e:
        print(f"❌ Error extracting audio: {e}")
        return None

def extract_frames(video_path: str, output_folder: str, interval: int = 2):
    """
    Frames extraction (Same as before)
    """
    os.makedirs(output_folder, exist_ok=True)
    output_pattern = os.path.join(output_folder, "frame_%03d.jpg")
    
    command = [
        "ffmpeg", "-i", video_path,
        "-vf", f"fps=1/{interval}", "-q:v", "2", "-y", "-loglevel", "error",
        output_pattern
    ]
    subprocess.run(command, check=True)
    
    # Return sorted list of frame paths
    frames = sorted([
        os.path.join(output_folder, f) 
        for f in os.listdir(output_folder) 
        if f.endswith(".jpg")
    ])
    return frames



# import os
# import subprocess

# def extract_audio(video_path: str, output_audio_path: str):
#     """
#     FFmpeg command: video se audio nikal kar MP3 bana do.
#     """
#     command = [
#         "ffmpeg",
#         "-i", video_path,       # Input Video
#         "-q:a", "0",            # Best Audio Quality
#         "-map", "a",            # Sirf Audio uthao
#         "-y",                   # Overwrite agar file pehle se ho
#         output_audio_path
#     ]
    
#     # Command run karo
#     subprocess.run(command, check=True)
#     return output_audio_path

# def extract_frames(video_path: str, output_folder: str, interval: int = 2):
#     """
#     FFmpeg command: Har 'interval' seconds baad ek screenshot lo.
#     """
#     # Folder banao agar nahi hai
#     os.makedirs(output_folder, exist_ok=True)
    
#     output_pattern = os.path.join(output_folder, "frame_%03d.jpg")
    
#     command = [
#         "ffmpeg",
#         "-i", video_path,       # Input Video
#         "-vf", f"fps=1/{interval}", # Filter: 1 frame every X seconds
#         "-q:v", "2",            # High Quality Jpg
#         "-y",
#         output_pattern
#     ]
    
#     subprocess.run(command, check=True)
#     return output_folder

