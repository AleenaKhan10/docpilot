import os
import json
import time
import re
import google.generativeai as genai
from core.config import settings

# Configure Gemini
genai.configure(api_key=settings.GOOGLE_API_KEY)
# Flash model fast aur cost-effective hai
model_flash = genai.GenerativeModel("gemini-2.5-flash")

# --- HELPER 1: JSON CLEANER ---
def _clean_json_response(response_text: str):
    """
    Cleans the ``````` from Gemini response and returns Pure JSON.
    """
    try:
        if "```" in response_text: 
            match = re.search(r"```(?:json)?\s*(.*)\s*```", response_text, re.DOTALL)
            if match:
                return match.group(1)
        return response_text
    except Exception:
        return response_text

# --- HELPER 2: FIND AUDIO FOR FRAME ---
def _get_audio_context_for_timestamp(timestamp, transcript):
    """
    Check karta hai ke is waqt (timestamp par) user kuch bol raha hai ya nahi.
    Agar bol raha hai to text return karega, warna None.
    """
    for segment in transcript:
        start = segment.get("start", 0)
        end = segment.get("end", 0)
        text = segment.get("text", "")
        
        # Agar current timestamp segment ke andar ya qareeb hai (2 sec buffer)
        if start - 2 <= timestamp <= end + 1:
            return text
    return None

# --- MAIN TRANSCRIPTION FUNCTION ---
def transcribe_audio_gemini(audio_path: str):
    """
    Audio ko text mein badalta hai (Verbatim Mode).
    """
    if not audio_path or not os.path.exists(audio_path):
        return []

    print("✨ Uploading Audio to Gemini...")
    try:
        audio_file = genai.upload_file(path=audio_path)
        print("🧠 Gemini Hearing: Analyzing audio...")
        
        prompt = """
        Transcribe this audio VERBATIM (word-for-word).
        RULES:
        1. Do NOT summarize. Write exactly what is spoken.
        2. Break down speech into small segments with accurate timestamps.
        
        Return ONLY raw JSON: [{"start": 0.0, "end": 2.0, "text": "Hello world"}]
        """
        response = model_flash.generate_content(
            [prompt, audio_file],
            generation_config={"response_mime_type": "application/json"}
        )
        
        cleaned_text = _clean_json_response(response.text)
        data = json.loads(cleaned_text)
        
        print(f"🔍 DEBUG: Transcript contains {len(data)} segments.")
        return data
    except Exception as e:
        print(f"❌ Transcription Error: {e}")
        return []

# ======================================================
# 🔥 RASTA 1: VISUAL ONLY (Agar video bilkul silent hai)
# ======================================================
def _generate_visual_only(frames_dir, interval):
    print("🔹 Mode: Visual-Only (Complete Silent Video)")
    generated_steps = []
    
    frames_paths = sorted([
        os.path.join(frames_dir, f) for f in os.listdir(frames_dir) if f.endswith(".jpg")
    ])
    
    # Har frame check karenge
    for i, frame_path in enumerate(frames_paths):
        # Optimization: Har 2nd frame uthao taake duplicate kam ho
        if i % 2 != 0: continue
        
        timestamp = i * interval
        print(f"   -> Analyzing Frame at {timestamp}s...")
        
        # --- PROMPT: DEDUCE ACTION FROM SCREEN ---
        prompt = """
        You are a Senior Technical Writer creating an SOP.
        
        TASK:
        Analyze this UI screenshot. Deduce the user's action based on visual cues (cursors, highlighted buttons, filled fields).
        
        WRITING STANDARDS:
        1. **Title:** Action Verb + Object (e.g., "Navigate to Dashboard").
        2. **Description:** Describe the action + **UI Element** + Location.
           - Ex: "Click the **Settings** icon in the top-right header."
        3. **Static Check:** If the screen looks idle with no action, return null.

        Return JSON ONLY: { "title": "...", "description": "..." }
        """
        
        try:
            uploaded_file = genai.upload_file(frame_path)
            response = model_flash.generate_content(
                [prompt, uploaded_file],
                generation_config={"response_mime_type": "application/json"}
            )
            
            cleaned_text = _clean_json_response(response.text)
            if not cleaned_text: continue
            
            step_data = json.loads(cleaned_text)
            if not step_data: continue

            # --- DEDUPLICATION (Duplicate hatao) ---
            if generated_steps:
                last_step = generated_steps[-1]
                if last_step['title'] == step_data.get("title"):
                    continue

            generated_steps.append({
                "step_number": len(generated_steps) + 1,
                "timestamp": timestamp,
                "image_path": frame_path,
                "title": step_data.get("title", "Step"),
                "description": step_data.get("description", "Action performed.")
            })
            time.sleep(1) 
        except Exception:
            pass
            
    return generated_steps

# ======================================================
# 🔥 RASTA 2: AUDIO DRIVEN (Frames + Audio Check)
# ======================================================
def _generate_with_audio(transcript, frames_dir, interval):
    print("🔹 Mode: Hybrid Audio-Visual (Frame-First Strategy)")
    generated_steps = []
    
    # 1. Frames ki list banao
    frames_paths = sorted([
        os.path.join(frames_dir, f) for f in os.listdir(frames_dir) if f.endswith(".jpg")
    ])
    
    # 2. Frames par loop chalao (Time ke hisaab se)
    for i, frame_path in enumerate(frames_paths):
        # Optimization: Har 2nd frame check karo
        if i % 2 != 0: continue
        
        timestamp = i * interval
        
        # 3. Check karo: Kya is waqt koi Audio hai?
        audio_text = _get_audio_context_for_timestamp(timestamp, transcript)
        
        # Log: Pata chale ke audio mili ya nahi
        status_icon = "✅ Audio Found" if audio_text else "🔇 Silent Moment"
        print(f"   -> Analyzing Frame at {timestamp}s | {status_icon}")

        # 4. Prompt Logic (Dynamic)
        if audio_text:
            # --- SCENARIO A: Audio Hai (Combine Karo) ---
            prompt = f"""
            You are a Lead Technical Writer.
            INPUT:
            - **Audio Intent:** "{audio_text}"
            - **Visual:** UI Screenshot.
            
            TASK: Create a professional documentation step.
            GUIDELINES:
            1. **Title:** Action Verb + Object (e.g. "Save Configuration").
            2. **Description:** Combine the 'Why' (Audio) with the 'How' (Visual).
               - Format: [Action] + [**UI Element**] + [Location] + [Reason].
            3. **Filler Check:** If audio is "Umm", "So...", ignore audio and describe visual action only.
            
            Return JSON ONLY: {{ "title": "...", "description": "..." }}
            """
        else:
            # --- SCENARIO B: Audio Nahi Hai (Visual Only) ---
            prompt = """
            You are a Lead Technical Writer.
            INPUT: UI Screenshot only (User is silent).
            
            TASK: Identify user action from visual cues.
            GUIDELINES:
            1. **Title:** Action Verb + Object.
            2. **Description:** Describe the action + **UI Element** + Location.
            3. **Static Check:** If no action is visible, return null.
            
            Return JSON ONLY: { "title": "...", "description": "..." }
            """

        try:
            uploaded_file = genai.upload_file(frame_path)
            response = model_flash.generate_content(
                [prompt, uploaded_file],
                generation_config={"response_mime_type": "application/json"}
            )
            
            cleaned_text = _clean_json_response(response.text)
            if not cleaned_text: continue
            
            step_data = json.loads(cleaned_text)
            
            # Skip logic
            if not step_data or str(step_data.get("title")).lower() == "skip":
                continue

            # --- DEDUPLICATION ---
            if generated_steps:
                last_step = generated_steps[-1]
                if last_step['title'] == step_data.get("title"):
                    continue

            generated_steps.append({
                "step_number": len(generated_steps) + 1,
                "timestamp": timestamp,
                "image_path": frame_path,
                "title": step_data.get("title", "Step"),
                "description": step_data.get("description", audio_text or "Action performed.")
            })
            time.sleep(0.5) 
        except Exception as e:
            # print(f"❌ Step Error: {e}")
            pass
            
    return generated_steps

# --- MAIN CONTROLLER (Darwaza) ---
def generate_documentation_steps(transcript: list, frames_dir: str, interval: int = 2):
    
    # 1. Agar Transcript bilkul khali hai (Matlab video silent thi) -> Rasta 1
    if not transcript or len(transcript) == 0:
        print("⚠️ No Transcript found. Switching to Silent/Visual Mode.")
        return _generate_visual_only(frames_dir, interval)
    
    # 2. Agar Transcript hai (Matlab video mein audio hai) -> Rasta 2 (Hybrid)
    return _generate_with_audio(transcript, frames_dir, interval)


# import os
# import json
# import time
# import re
# import google.generativeai as genai
# from core.config import settings

# # Configure Gemini
# genai.configure(api_key=settings.GOOGLE_API_KEY)
# model_flash = genai.GenerativeModel("gemini-2.0-flash")

# # --- HELPER: JSON CLEANER (Production Safe) ---
# def _clean_json_response(response_text: str):
#     """
#     Gemini ke response se ```json markers hata kar pure JSON nikalta hai.
#     """
#     try:
#         if "```" in response_text:
#             match = re.search(r"```(?:json)?\s*(.*)\s*```", response_text, re.DOTALL)
#             if match:
#                 return match.group(1)
#         return response_text
#     except Exception:
#         return response_text

# def transcribe_audio_gemini(audio_path: str):
#     """
#     Audio Transcript: Strict Verbatim Mode (No Summaries).
#     """
#     if not audio_path or not os.path.exists(audio_path):
#         return []

#     print("✨ Uploading Audio to Gemini...")
#     try:
#         audio_file = genai.upload_file(path=audio_path)
#         print("🧠 Gemini Hearing: Analyzing audio...")
        
#         prompt = """
#         Transcribe this audio VERBATIM (word-for-word).
#         RULES:
#         1. Do NOT summarize. Write exactly what is spoken.
#         2. Break down speech into small segments with accurate timestamps.
        
#         Return ONLY raw JSON: [{"start": 0.0, "end": 2.0, "text": "Hello world"}]
#         """
#         response = model_flash.generate_content(
#             [prompt, audio_file],
#             generation_config={"response_mime_type": "application/json"}
#         )
        
#         cleaned_text = _clean_json_response(response.text)
#         data = json.loads(cleaned_text)
        
#         print(f"🔍 DEBUG: Transcript contains {len(data)} segments.")
#         return data
#     except Exception as e:
#         print(f"❌ Transcription Error: {e}")
#         return []

# # ======================================================
# # 🔥 MODE 1: VISUAL ONLY (Master Level - Silent) 🔥
# # ======================================================
# def _generate_visual_only(frames_dir, interval):
#     print("🔹 Mode: Visual-Only (Master Class Documentation)")
#     generated_steps = []
    
#     frames_paths = sorted([
#         os.path.join(frames_dir, f) for f in os.listdir(frames_dir) if f.endswith(".jpg")
#     ])
    
#     for i, frame_path in enumerate(frames_paths):
#         timestamp = i * interval
#         print(f"   -> Analyzing Frame at {timestamp}s...")
        
#         # --- THE MASTER VISUAL PROMPT ---
#         prompt = """
#         You are a Senior Technical Writer creating a Standard Operating Procedure (SOP).
        
#         TASK:
#         Analyze this UI screenshot. Deduce the user's action based on visual cues (highlighted buttons, open menus, cursors).
        
#         WRITING STANDARDS (Microsoft Manual of Style):
#         1. **Imperative Mood:** Start with a strong VERB (e.g., "Click", "Select", "Enter").
#         2. **Formatting:** ALWAYS bold UI element names using double asterisks (e.g., Click **Save**, Select **Profile**).
#         3. **Location Context:** Specify WHERE the element is (e.g., "in the top-right corner", "in the sidebar").
#         4. **Iconography:** If it's an icon, describe it (e.g., "Click the **Settings** icon (gear symbol)").
        
#         STATIC CHECK:
#         If the screen appears idle with no meaningful interaction, return null.

#         Example Output:
#         { "title": "Navigate to Dashboard", "description": "Click the **Dashboard** link located in the left navigation sidebar." }

#         Return JSON ONLY.
#         """
        
#         try:
#             uploaded_file = genai.upload_file(frame_path)
#             response = model_flash.generate_content(
#                 [prompt, uploaded_file],
#                 generation_config={"response_mime_type": "application/json"}
#             )
            
#             cleaned_text = _clean_json_response(response.text)
#             if not cleaned_text: continue
            
#             step_data = json.loads(cleaned_text)
#             if not step_data: continue

#             # --- SMART DEDUPLICATION ---
#             if generated_steps:
#                 last_step = generated_steps[-1]
#                 # Agar same title hai, to duplicate count hoga
#                 if last_step['title'] == step_data.get("title"):
#                     continue

#             generated_steps.append({
#                 "step_number": len(generated_steps) + 1,
#                 "timestamp": timestamp,
#                 "image_path": frame_path,
#                 "title": step_data.get("title", "Step"),
#                 "description": step_data.get("description", "Action performed.")
#             })
#             time.sleep(1) 
#         except Exception:
#             pass
            
#     return generated_steps

# # ======================================================
# # 🔥 MODE 2: AUDIO DRIVEN (Master Level - Pro) 🔥
# # ======================================================
# def _generate_with_audio(transcript, frames_dir, interval):
#     print("🔹 Mode: Audio-Driven (Master Class Documentation)")
#     generated_steps = []
    
#     for segment in transcript:
#         text = segment.get("text", "")
#         start_time = segment.get("start", 0)
        
#         if len(text) < 5: continue

#         frame_index = int(start_time / interval) + 1
#         frame_name = f"frame_{frame_index:03d}.jpg"
#         frame_path = os.path.join(frames_dir, frame_name)
        
#         if not os.path.exists(frame_path): continue
            
#         print(f"   -> Processing Step: '{text[:20]}...'")

#         # --- THE MASTER AUDIO PROMPT ---
#         prompt = f"""
#         You are a Lead Technical Writer at a top-tier SaaS company.
        
#         INPUT CONTEXT:
#         - **User Intent (Audio):** "{text}" (Why are they doing this?).
#         - **Visual Reality (Image):** UI Screenshot (How and Where?).

#         STRICT WRITING GUIDELINES (SOP Standard):
#         1. **Goal-Oriented Titles:** The title must describe the OUTCOME, not just the click.
#            - Bad: "Click Settings"
#            - Good: "Configure System Settings"
        
#         2. **Precise Description Formula:**
#            [Imperative Verb] + [**Element Name**] + [Location/Context] + [Reason from Audio].
           
#            - *Example:* "Click the **Export** button in the top-right corner to download the report as a CSV file."
        
#         3. **Formatting Rules:** - UI Labels must be **Bold** (e.g., **Submit**, **Cancel**).
#            - Do not use passive voice ("The user is..."). Use commands ("Click...", "Type...").
        
#         4. **Filter:** If the audio is conversational filler (e.g., "So yeah...", "Umm..."), return {{ "title": "skip", "description": "skip" }}

#         Return JSON ONLY: {{ "title": "Action Title", "description": "Instructional description." }}
#         """
        
#         try:
#             uploaded_file = genai.upload_file(frame_path)
#             response = model_flash.generate_content(
#                 [prompt, uploaded_file],
#                 generation_config={"response_mime_type": "application/json"}
#             )
            
#             cleaned_text = _clean_json_response(response.text)
#             step_data = json.loads(cleaned_text)
            
#             if str(step_data.get("title")).lower() == "skip":
#                 continue

#             generated_steps.append({
#                 "step_number": len(generated_steps) + 1,
#                 "timestamp": start_time,
#                 "image_path": frame_path,
#                 "title": step_data.get("title", "Step"),
#                 "description": step_data.get("description", text)
#             })
#             time.sleep(0.5) 
#         except Exception as e:
#             print(f"❌ Step Generation Error: {e}")
            
#     return generated_steps

# # --- MAIN CONTROLLER ---
# def generate_documentation_steps(transcript: list, frames_dir: str, interval: int = 2):
#     if not transcript or len(transcript) == 0:
#         print("⚠️ No Transcript found. Switching to Silent/Visual Mode.")
#         return _generate_visual_only(frames_dir, interval)
    
#     return _generate_with_audio(transcript, frames_dir, interval)