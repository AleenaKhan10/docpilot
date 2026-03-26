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
            
            # --- PROFESSIONAL DOCUMENTATION SYSTEM PROMPT ---
            system_prompt = """
            You are a Lead Documentation Architect at a Tier-1 Enterprise SaaS company (like Stripe, Shopify, or AWS).
            Your job is to convert UI screenshots into professional Help Center documentation.

            **CRITICAL RULES:**
            1. **NO IMAGE DEPENDENCY:** The reader cannot see the image. Describe every UI element's location clearly (e.g., "Top-right corner", "Left sidebar", "Below the header").
            2. **WRITE LIKE A HELP CENTER:** Each step must feel like it belongs in official product documentation — clear, professional, and educational.
            3. **SECTION AWARENESS:** Group related actions under a logical section. Provide a section_summary that introduces what will be accomplished in this section.
            4. **EXPLANATIONS:** After each action, explain WHY the user is doing this and WHAT it achieves. Do not just repeat the action.
            5. **TIPS:** Only provide a "tip" if there is a genuine Keyboard Shortcut, Time-saving trick, or Critical Warning. Otherwise, return null.
            6. **NOTES:** If there is something important the user should be aware of (permissions required, prerequisites, data loss risk), put it in "note". Otherwise return null.
            7. **URL EXTRACTION:** If the browser Address Bar is visible, extract the URL into the "url" field.

            **OUTPUT FORMAT (JSON ONLY):**
            {
                "section": "Logical section header (e.g. 'Setting Up Your Account')",
                "section_summary": "A 1-2 sentence introduction explaining what this section covers and why it matters. Write as if introducing a chapter.",
                "action": "Clear, imperative instruction with **bold** UI element names and location context.",
                "explanation": "A 1-2 sentence explanation of what this step accomplishes and why it is important. Do NOT repeat the action.",
                "tip": "Short pro-tip with keyboard shortcut or time-saving trick, or null.",
                "note": "Important warning, prerequisite, or caveat the user must know, or null.",
                "url": "https://extracted-url.com or null"
            }
            """

            # --- PROFESSIONAL DOCUMENTATION USER PROMPT ---
            user_prompt = f"""
            Analyze the UI screenshot captured at {timestamp}s of a software tutorial video.
            Audio narration context: "{audio_text if audio_text else 'No narration — infer context from the visual UI elements.'}"

            **Your Task:**
            1. Identify the user's action in this screenshot and write a clear, professional **Action** instruction.
            2. Write a brief **Explanation** of what this step accomplishes (do NOT repeat the action text).
            3. Determine the **Section** this step belongs to — use a logical, descriptive heading.
            4. Write a **Section Summary** — a brief introduction paragraph for this section (imagine you're writing the opening paragraph of a help article).
            5. Extract **URL** if visible in the browser address bar.
            6. Add a **Tip** ONLY if genuinely helpful (keyboard shortcuts, warnings). Most steps should have null tips.
            7. Add a **Note** ONLY if there's an important prerequisite, permission requirement, or data caution.

            **Return JSON only.**
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
                temperature=0.5, # Slightly lower temp for more consistent formatting
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
                # Section = title (grouping header)
                "title": step_data.get("section", "General"), 
                "description": step_data.get("action", "Action performed."),
                "tip": step_data.get("tip", None),
                "url": step_data.get("url", None),
                # --- NEW Professional Documentation Fields ---
                "explanation": step_data.get("explanation", None),
                "note": step_data.get("note", None),
                "section_summary": step_data.get("section_summary", None),
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


