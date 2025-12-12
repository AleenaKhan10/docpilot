import subprocess
import os
import shutil
import numpy as np
from PIL import Image

def extract_audio(video_path: str, output_path: str):
    """
    Extracts MP3 audio from the video file using FFmpeg.
    """
    command = [
        "ffmpeg", "-i", video_path, "-q:a", "0", "-map", "a", output_path, "-y"
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path if os.path.exists(output_path) else None

def extract_frames(video_path: str, output_dir: str, interval: int = 1):
    """
    Extracts frames every 'interval' seconds.
    Note: We extract frequently (e.g., every 1s) and then filter duplicates later.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # FFmpeg command to extract frames
    # fps=1/interval means 1 frame every X seconds
    command = [
        "ffmpeg", "-i", video_path,
        "-vf", f"fps=1/{interval}",
        f"{output_dir}/frame_%03d.jpg",
        "-y"
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # --- ENTERPRISE UPGRADE: SMART FILTERING ---
    # After extraction, we immediately remove static/duplicate frames
    # to save AI cost and processing time.
    _filter_static_frames(output_dir)

def _filter_static_frames(frames_dir: str):
    """
    Analyzes all extracted frames and deletes duplicates.
    TUNED FOR UI: High sensitivity to catch small mouse movements/typing.
    """
    print("👁️  Smart Filter: Analyzing frames for duplication...")
    
    frames = sorted([
        os.path.join(frames_dir, f) for f in os.listdir(frames_dir) if f.endswith(".jpg")
    ])
    
    if not frames:
        return

    unique_frames = [frames[0]] 
    deleted_count = 0
    
    # Increase resolution for comparison (More details visible)
    # 64x64 was too blurry. 100x100 catches text changes better.
    prev_image = Image.open(frames[0]).convert("L").resize((100, 100))
    
    for i in range(1, len(frames)):
        current_frame_path = frames[i]
        
        try:
            curr_image_raw = Image.open(current_frame_path).convert("L")
            curr_image = curr_image_raw.resize((100, 100))
            
            img1 = np.array(prev_image)
            img2 = np.array(curr_image)
            
            # Mean Squared Error (Diff nikalna)
            mse = np.mean((img1 - img2) ** 2)
            
            # --- DEBUG LOG (Isay uncomment karke dekh sakte ho values) ---
            # print(f"   Frame {i} MSE: {mse:.2f}")

            # --- THRESHOLD TUNING ---
            # Pehle 30 tha (Too aggressive).
            # Ab 2.0 kar rahe hain (Very sensitive).
            # Agar MSE 2.0 se kam hai, matlab <1% change hai -> Delete.
            # Agar MSE > 2.0 hai (Cursor bhi hila), -> Keep.
            
            if mse < 2.0: 
                # DUPLICATE
                os.remove(current_frame_path)
                deleted_count += 1
            else:
                # UNIQUE ACTION DETECTED
                unique_frames.append(current_frame_path)
                prev_image = curr_image 
                
        except Exception as e:
            print(f"❌ Error filtering frame {current_frame_path}: {e}")

    # --- SAFETY NET (Production Guard) ---
    # Agar ghalti se system ne sab ura diya (e.g. < 3 frames bache),
    # aur video lambi thi, to shyd ghalti hui hai.
    # Aisi situation mein hum kuch nahi kar sakte kyunki file delete ho chuki hai,
    # lekin hum log kar sakte hain taake threshold adjust karein.
    
    remaining = len(unique_frames)
    print(f"📉 Optimization: Removed {deleted_count} static frames. Kept {remaining} unique keyframes.")
    
    if remaining < 3 and len(frames) > 10:
        print("⚠️ WARNING: Too many frames removed! Consider lowering threshold further.")