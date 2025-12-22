import os
import json
import time
import re
import base64
import asyncio
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from core.config import settings

# OpenAI Async Client
client = AsyncOpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=settings.NVIDIA_API_KEY,
)
MODEL_NAME = settings.MODEL_NAME

# --- HELPERS ---
def encode_image(image_path):
    """Encodes an image to Base64 for the API."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def _clean_json_response(response_text: str):
    """Cleans Markdown formatting from JSON response."""
    try:
        if "```" in response_text:
            match = re.search(r"```(?:json)?\s*(.*)\s*```", response_text, re.DOTALL)
            if match:
                return match.group(1)
        return response_text
    except Exception:
        return response_text

def _get_audio_context_for_timestamp(timestamp, transcript):
    """Finds relevant audio text for a specific timestamp (with buffer)."""
    if not transcript:
        return None
    context_text = []
    for segment in transcript:
        start = segment.get("start", 0)
        end = segment.get("end", 0)
        text = segment.get("text", "")
        # Buffer: 2 seconds before and after
        if (start - 2.0 <= timestamp <= end + 2.0):
            context_text.append(text)
    return " ".join(context_text) if context_text else None

# --- SAFETY WRAPPER: RETRY MECHANISM ---
@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(Exception)
)
async def _call_api_with_retry(model, messages, temperature):
    return await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature
    )

# --- ASYNC WORKER: PROCESS SINGLE FRAME ---
async def process_single_frame(semaphore, i, total_frames, frame_path, timestamp, audio_text):
    async with semaphore:
        print(f"   -> 🚀 Sending Frame {i+1}/{total_frames} at {timestamp}s...")
        
        try:
            base64_image = encode_image(frame_path)
            
            # --- UPDATED SYSTEM PROMPT FOR SOP STYLE ---
            system_prompt = """
            
            You are an expert Technical Writer for Enterprise Software.
            Convert the UI screenshot into a structured Help Center guide.

            **CRITICAL RULES:**
            1. **NO IMAGE DEPENDENCY:** The user cannot see the image. Describe the location clearly (e.g., "Top-right corner", "Left sidebar").
            2. **LESS IS MORE (TIPS):** Only provide a "tip" if there is a specific Keyboard Shortcut (e.g. Ctrl+C) or a Critical Warning. Otherwise, return null. Do NOT state the obvious.
            3. **URL EXTRACTION:** If the browser Address Bar is visible in the screenshot, or the context implies a specific URL (e.g. "Go to google.com"), extract it into the "url" field.

            **OUTPUT FORMAT (JSON ONLY):**
            {
                "section": "Logical header (e.g. 'Account Setup')",
                "action": "Direct instruction (e.g. 'Click the **Settings** gear.').",
                "tip": "Short pro-tip or null.",
                "url": "https://valid-url.com or null"
            }
            """

            # --- UPDATED USER PROMPT ---
            user_prompt = f"""
            Analyze screenshot at {timestamp}s.
            Audio: "{audio_text if audio_text else 'Silence'}"

            **Task:**
            1. Write a clear **Action** step.
            2. Extract **URL** if visible in the address bar.
            3. Add a **Tip** ONLY if it adds high value (Shortcuts/Warnings). Most steps should have null tips.

            **JSON:**
            """

            # API Call
            response = await _call_api_with_retry(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                temperature=0.7, # Slightly lower temp for more consistent formatting
            )

            raw_content = response.choices[0].message.content
            cleaned_text = _clean_json_response(raw_content)
            
            if not cleaned_text: return None
            step_data = json.loads(cleaned_text)

            # Skip logic update
            if not step_data or str(step_data.get("section")).lower() == "skip" or str(step_data.get("action")).lower() == "skip":
                return None

            print(f"      ✅ Received: {step_data.get('action')[:30]}...")
            
            # Mapping API response to our Internal Data Structure
            return {
                "step_number": 0, 
                "timestamp": timestamp,
                "image_path": frame_path,
                # Mapping 'section' to 'title' so DB saves it correctly as the grouping header
                "title": step_data.get("section", "General"), 
                # Mapping 'action' to 'description'
                "description": step_data.get("action", "Action performed."),
                # Passing 'tip' along (Ensure your PDF generator uses this!)
                "tip": step_data.get("tip", None),
                "url" : step_data.get("url", None)
                
            }

        except Exception as e:
            print(f"❌ Frame {i+1} Failed (Final): {e}")
            return None

# --- RUNNER ---
async def _run_parallel_generation(frames_paths, transcript, interval):
    semaphore = asyncio.Semaphore(10) 
    tasks = []
    total_frames = len(frames_paths)
    
    for i, frame_path in enumerate(frames_paths):
        timestamp = i * interval
        audio_text = _get_audio_context_for_timestamp(timestamp, transcript)
        tasks.append(
            process_single_frame(semaphore, i, total_frames, frame_path, timestamp, audio_text)
        )
    
    print(f"⚡ Starting Parallel Processing of {total_frames} frames...")
    results = await asyncio.gather(*tasks)
    return results

# --- ENTRY POINT ---
def generate_documentation_steps(transcript: list, frames_dir: str, interval: int = 2):
    print(f"🔹 Mode: Enterprise SOP Flow (Model: {MODEL_NAME})")
    
    frames_paths = sorted([
        os.path.join(frames_dir, f) for f in os.listdir(frames_dir) if f.endswith(".jpg")
    ])
    
    if not frames_paths:
        return []

    try:
        if os.name == 'nt':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        raw_results = asyncio.run(_run_parallel_generation(frames_paths, transcript, interval))
    except Exception as e:
        print(f"CRITICAL ASYNC ERROR: {e}")
        return []
    
    valid_steps = [r for r in raw_results if r is not None]
    valid_steps.sort(key=lambda x: x['timestamp'])
    
    final_steps = []
    for step in valid_steps:
        if final_steps:
            last_step = final_steps[-1]
            # De-duplication Logic:
            # Agar Description same hai, tow skip karo. 
            # (Note: Title/Section same ho sakta hai, uspar skip mat karna)
            if last_step['description'][:20] == step['description'][:20]:
                 continue
        
        step['step_number'] = len(final_steps) + 1
        final_steps.append(step)

    print(f"✅ Parallel Processing Complete. Generated {len(final_steps)} SOP steps.")
    return final_steps


# import os
# import json
# import time
# import re
# import base64
# import asyncio
# from openai import AsyncOpenAI
# from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
# from core.config import settings

# # OpenAI Async Client
# client = AsyncOpenAI(
#     base_url="https://integrate.api.nvidia.com/v1",
#     api_key="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",
# )
# MODEL_NAME = "meta/llama-4-maverick-17b-128e-instruct"

# # --- HELPERS ---
# def encode_image(image_path):
#     """Encodes an image to Base64 for the API."""
#     with open(image_path, "rb") as image_file:
#         return base64.b64encode(image_file.read()).decode('utf-8')

# def _clean_json_response(response_text: str):
#     """Cleans Markdown formatting from JSON response."""
#     try:
#         if "```" in response_text:
#             match = re.search(r"```(?:json)?\s*(.*)\s*```", response_text, re.DOTALL)
#             if match:
#                 return match.group(1)
#         return response_text
#     except Exception:
#         return response_text

# def _get_audio_context_for_timestamp(timestamp, transcript):
#     """Finds relevant audio text for a specific timestamp (with buffer)."""
#     if not transcript:
#         return None
#     context_text = []
#     for segment in transcript:
#         start = segment.get("start", 0)
#         end = segment.get("end", 0)
#         text = segment.get("text", "")
#         # Buffer: 2 seconds before and after
#         if (start - 2.0 <= timestamp <= end + 2.0):
#             context_text.append(text)
#     return " ".join(context_text) if context_text else None

# # --- SAFETY WRAPPER: RETRY MECHANISM ---
# @retry(
#     stop=stop_after_attempt(5),
#     wait=wait_exponential(multiplier=1, min=2, max=10),
#     retry=retry_if_exception_type(Exception)
# )
# async def _call_api_with_retry(model, messages, temperature):
#     return await client.chat.completions.create(
#         model=model,
#         messages=messages,
#         temperature=temperature
#     )

# # --- ASYNC WORKER: PROCESS SINGLE FRAME ---
# async def process_single_frame(semaphore, i, total_frames, frame_path, timestamp, audio_text):
#     async with semaphore:
#         print(f"   -> 🚀 Sending Frame {i+1}/{total_frames} at {timestamp}s...")
        
#         try:
#             base64_image = encode_image(frame_path)
            
#             system_prompt = """
#             You are a Lead Documentation Architect for a Tier-1 Enterprise SaaS (like Stripe, AWS, or Atlassian).
#             Your goal is to write rich, detailed, pixel-perfect, explanatory, long, context-aware, and highly professional SOP steps.

#             **OUTPUT FORMAT (JSON ONLY):**
#             {
#                 "title": "Action-Oriented Header",
#                 "description": "Detailed, Explanatory, Clear, Accurate, Pixel Perfect, Precise and Complete Detailed Orienter instructions with inferred technical context."
#             }
#             """

#             user_prompt = f"""
#             Analyze the UI screenshot at timestamp {timestamp}s.
#             **AUDIO CONTEXT:** "{audio_text if audio_text else 'NO AUDIO - INFER CONTEXT FROM VISUALS'}"

#             ---
#             ### 🚀 THE "ENTERPRISE QUALITY" STANDARD:
            
#             **1. AVOID TAUTOLOGY (Don't repeat the name in the outcome):**
#                - ❌ Bad: "Click the **Save** button to save."
#                - ✅ Good: "Click the **Save** button to persist your configuration changes to the database."

#             **2. INFER THE "WHY" (Even if audio is silent):**
#                - If user clicks 'Pencil Icon' -> Context is "Modification" or "Editing".
#                - If user clicks 'Trash Icon' -> Context is "Removal" or "Data Cleanup".
#                - If user clicks 'Gear Icon' -> Context is "System Configuration".
            
#             **3. RICH VOCABULARY:**
#                - Use professional verbs: *Initialize, Configure, Navigate, Execute, Modify, Validate, Deploy.*
            
#             **4. SENTENCE STRUCTURE:**
#                - [Imperative Action] + [**Bold Element**] + [Location] + [Professional Outcome].

#             ---
#             ### ✅ EXAMPLES: (Make it them a bit more detailed)
#             - **Translator:** "Select the **Translator** icon in the top-right header to open the localization panel and adjust language preferences."
#             - **Settings:** "Navigate to the **Settings** tab on the left sidebar to access global account configurations."
#             - **Input:** "Enter the customer's full legal name into the **Client Name** field to initialize the record creation process."

#             **5. STATIC CHECK:**
#                If the screen is idle, blurry, or shows no meaningful interaction, return:
#                {{ "title": "skip", "description": "skip" }}

#             **GENERATE THE SOP STEP NOW:**
#             """

#             # API Call
#             response = await _call_api_with_retry(
#                 model=MODEL_NAME,
#                 messages=[
#                     {"role": "system", "content": system_prompt},
#                     {
#                         "role": "user",
#                         "content": [
#                             {"type": "text", "text": user_prompt},
#                             {
#                                 "type": "image_url",
#                                 "image_url": {
#                                     "url": f"data:image/jpeg;base64,{base64_image}"
#                                 }
#                             }
#                         ]
#                     }
#                 ],
#                 temperature=0.9, # Creative Freedom
#             )

#             raw_content = response.choices[0].message.content
#             cleaned_text = _clean_json_response(raw_content)
            
#             if not cleaned_text: return None
#             step_data = json.loads(cleaned_text)

#             if not step_data or str(step_data.get("title")).lower() == "skip":
#                 return None

#             print(f"      ✅ Received: {step_data.get('title')}")
            
#             return {
#                 "step_number": 0, 
#                 "timestamp": timestamp,
#                 "image_path": frame_path,
#                 "title": step_data.get("title", "Step"),
#                 "description": step_data.get("description", "Action performed.")
#             }

#         except Exception as e:
#             print(f"❌ Frame {i+1} Failed (Final): {e}")
#             return None

# # --- RUNNER ---
# async def _run_parallel_generation(frames_paths, transcript, interval):
#     semaphore = asyncio.Semaphore(10) 
#     tasks = []
#     total_frames = len(frames_paths)
    
#     for i, frame_path in enumerate(frames_paths):
#         timestamp = i * interval
#         audio_text = _get_audio_context_for_timestamp(timestamp, transcript)
#         tasks.append(
#             process_single_frame(semaphore, i, total_frames, frame_path, timestamp, audio_text)
#         )
    
#     print(f"⚡ Starting Parallel Processing of {total_frames} frames...")
#     results = await asyncio.gather(*tasks)
#     return results

# # --- ENTRY POINT ---
# def generate_documentation_steps(transcript: list, frames_dir: str, interval: int = 2):
#     print(f"🔹 Mode: Enterprise SOP Flow (Model: {MODEL_NAME})")
    
#     frames_paths = sorted([
#         os.path.join(frames_dir, f) for f in os.listdir(frames_dir) if f.endswith(".jpg")
#     ])
    
#     if not frames_paths:
#         return []

#     try:
#         if os.name == 'nt':
#             asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
#         raw_results = asyncio.run(_run_parallel_generation(frames_paths, transcript, interval))
#     except Exception as e:
#         print(f"CRITICAL ASYNC ERROR: {e}")
#         return []
    
#     valid_steps = [r for r in raw_results if r is not None]
#     valid_steps.sort(key=lambda x: x['timestamp'])
    
#     final_steps = []
#     for step in valid_steps:
#         if final_steps:
#             last_step = final_steps[-1]
#             if last_step['title'] == step['title']:
#                  if last_step['description'][:15] == step['description'][:15]:
#                     continue
#         step['step_number'] = len(final_steps) + 1
#         final_steps.append(step)

#     print(f"✅ Parallel Processing Complete. Generated {len(final_steps)} SOP steps.")
#     return final_steps