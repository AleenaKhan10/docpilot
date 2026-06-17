"""
Two-pass video-to-document synthesis with Gemini.

PASS 1 — Frame observation (per-frame, cheap, parallel-safe)
    For every kept frame, we ask the cheap Flash model for terse FACTS only:
    URL bar contents, page/app title, the dominant UI element, and any
    obvious action (click target, what's typed). No interpretation, no
    "section", no documentation prose. Output ~50-100 tokens per frame.

PASS 2 — Editorial synthesis (one big call, smarter model)
    A single call to the same Flash-tier model receives ALL observations,
    the full Whisper transcript, the user-provided context, and the
    output_type. The prompt explicitly asks the model to be a WRITER, not
    a transcriber: drop setup noise, group related actions, place
    screenshots strategically (one or two, at meaningful moments), extract
    reference links, and adapt depth to the available signal.

The result is a Document {title, summary, output_type, sections:[...]}
matching the frontend's Section/Block schema. The worker stores it on
`videos.document_json`; the API translates any `frame_id` references into
signed download URLs at read time.
"""

import asyncio
import json
import os
import re
from typing import Optional

import google.generativeai as genai
from PIL import Image
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from core.config import settings
from core.logger import setup_logging

logger = setup_logging()

# --- Lazy configuration -------------------------------------------------------
_configured = False


def _ensure_configured() -> None:
    global _configured
    if _configured:
        return
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    genai.configure(api_key=settings.GEMINI_API_KEY)
    _configured = True


def _get_model(name: Optional[str] = None) -> genai.GenerativeModel:
    _ensure_configured()
    return genai.GenerativeModel(name or settings.GEMINI_MODEL or "gemini-flash-latest")


# --- Helpers ------------------------------------------------------------------
def _clean_json(text: str) -> str:
    """Strip markdown code fences."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


# Paced caller: spaces consecutive Gemini calls 4.5 s apart. On the paid tier
# this is overkill — at flash-latest paid you can run ~1000 RPM — but keeping
# it conservative until we observe throughput in production.
MIN_INTERVAL_S = 4.5
_last_call_at = 0.0
_call_lock = asyncio.Lock()


async def _wait_for_slot() -> None:
    global _last_call_at
    async with _call_lock:
        now = asyncio.get_event_loop().time()
        wait = MIN_INTERVAL_S - (now - _last_call_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_at = asyncio.get_event_loop().time()


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=3, min=8, max=45),
    retry=retry_if_exception_type(Exception),
)
async def _call_model(model: genai.GenerativeModel, parts) -> str:
    await _wait_for_slot()
    response = await model.generate_content_async(parts)
    return (response.text or "").strip()


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=3, min=8, max=45),
    retry=retry_if_exception_type(Exception),
)
def _call_model_sync(model: genai.GenerativeModel, prompt: str) -> str:
    """Sync variant. Used for Pass 2 to dodge the async grpc client-state
    bug in google.generativeai when asyncio.run is called more than once."""
    response = model.generate_content(prompt)
    return (response.text or "").strip()


# --- PASS 1: per-frame observations ------------------------------------------
PASS1_PROMPT = """You are a screen-recording analyst. Look at this single frame.

Return ONLY a JSON object with these fields. Be terse and FACTUAL — no documentation prose, no "section names", no interpretation about what the user is "trying to accomplish".

{
  "page_title": "<browser tab title or window title if visible, else empty string>",
  "url": "<full URL from address bar if visible, else empty string>",
  "app": "<application or website name visible (e.g. 'YouTube', 'Social Blade', 'VS Code'). Empty string if generic.>",
  "visible_state": "<one sentence describing the dominant UI on screen — what page/screen the user is on>",
  "action_hint": "<if a click target / hover / focused input / typed text is visible, say what (one short phrase). Empty string otherwise.>",
  "typed_text": "<actual text being typed in an input, if visible. Empty string otherwise.>"
}

Output nothing but the JSON. No markdown, no commentary."""


async def _pass1_one_frame(
    semaphore: asyncio.Semaphore,
    model: genai.GenerativeModel,
    frame_id: str,
    frame_path: str,
    timestamp: float,
) -> Optional[dict]:
    async with semaphore:
        try:
            with Image.open(frame_path) as img:
                img.load()
                raw = await _call_model(model, [PASS1_PROMPT, img])
            data = json.loads(_clean_json(raw))
            return {
                "frame_id": frame_id,
                "timestamp": round(timestamp, 1),
                "page_title": data.get("page_title", "") or "",
                "url": data.get("url", "") or "",
                "app": data.get("app", "") or "",
                "visible_state": data.get("visible_state", "") or "",
                "action_hint": data.get("action_hint", "") or "",
                "typed_text": data.get("typed_text", "") or "",
            }
        except Exception as e:
            logger.warning(f"Pass 1 frame {frame_id} failed: {e}")
            return None


# --- PASS 2: editorial synthesis ---------------------------------------------
OUTPUT_TYPE_GUIDANCE = {
    "sop": (
        "Write a Standard Operating Procedure: instructions someone else can "
        "follow tomorrow to reproduce the same outcome."
    ),
    "training": (
        "Write a Training Module: explain the concept, then the steps, then "
        "summarize what the learner should now be able to do. Include short "
        "comprehension checks as `decision` blocks where appropriate."
    ),
    "bug_report": (
        "Write a Bug Report: capture exact reproduction steps, expected vs "
        "actual behaviour, the environment shown on screen, and severity if "
        "you can infer it."
    ),
    "changelog": (
        "Write a Changelog entry: list what was added, changed, fixed, or "
        "removed using `step` blocks under a single section per change "
        "category."
    ),
    "audit": (
        "Write an Audit Trail: timestamped actor → action log, categorised "
        "by area. Use `table` blocks if a tabular structure fits."
    ),
    "client_handover": (
        "Write a Client Handover: project status, deliverables checklist, "
        "next steps, references."
    ),
}


def _build_pass2_prompt(
    output_type: str, user_context: Optional[str], transcript_text: str,
    observations_json: str, duration_seconds: float,
) -> str:
    guidance = OUTPUT_TYPE_GUIDANCE.get(output_type, OUTPUT_TYPE_GUIDANCE["sop"])
    user_ctx_block = (
        f'User-provided context: "{user_context.strip()}"\n'
        if user_context and user_context.strip()
        else "User-provided context: (none)\n"
    )
    return f"""You are a senior technical writer. You are NOT a transcriber.

A user recorded a {duration_seconds:.0f}-second screen video. Your job: produce CLEAN, MINIMAL documentation a reader can actually follow.

{user_ctx_block}
Target document type: **{output_type}**
{guidance}

═══════════════════════════════════════════════════════════════
AUDIO TRANSCRIPT (verbatim, may be partial or empty):
{transcript_text or "(no audio)"}

═══════════════════════════════════════════════════════════════
PER-FRAME OBSERVATIONS (Pass 1 output — facts only, ordered by timestamp):
{observations_json}

═══════════════════════════════════════════════════════════════
EDITORIAL RULES — read these carefully:

1. **BE A WRITER, NOT A STENOGRAPHER.** A bad doc has 29 numbered steps that
   mirror every click. A good doc collapses related clicks into one
   meaningful step. Aim for the doc a human technical writer would produce.

2. **DROP NOISE.** Skip: "Open Chrome", "open a new tab", "click address bar",
   "scroll down to find X", going-back-and-forth, hesitation. The reader
   doesn't need it.

3. **GROUP RELATED ACTIONS.** Three clicks to reach a page → ONE step:
   "Navigate to the channel's page". A long typed phrase → one step.

4. **ADAPT DEPTH TO SIGNAL.**
   • If the audio explained the *why*, keep steps tight — don't repeat
     what the speaker said.
   • If the audio is silent or unrelated, you must infer purpose from
     frames and may need slightly more detail to compensate.
   • If the same task could be done many ways, focus on what THIS recording
     actually demonstrates.

5. **SCREENSHOTS — STRATEGIC, NOT PER-STEP.**
   • Include AT MOST 1-2 image blocks total for a short / simple doc.
   • Always include one screenshot of the END RESULT (the destination page,
     the success state, the final form).
   • Optionally one at the top showing a distinctive starting state.
   • Use `frame_id` from observations to reference specific frames.
   • Do NOT put a screenshot next to every step. That is Scribe. We are
     not Scribe.

6. **REFERENCES.** If a specific external tool / domain / site appears
   (e.g. "socialblade.com", a docs URL, a third-party service), include
   a `References` section at the end with `link` blocks. ALSO inline a
   `link` block when a step explicitly says "open <url>".

7. **STRUCTURE SIZE.** Simple tasks → 1 section, 3-5 steps. Medium
   tasks → 2-3 sections. Complex tasks → 4-8 sections with intros.

8. **TONE.** Instructional, second-person, concise. NO "the user clicks".
   NO "as shown in the screenshot". Active voice, short sentences.

═══════════════════════════════════════════════════════════════
OUTPUT — return ONLY this JSON. No markdown fences, no commentary outside the JSON.

{{
  "title": "<the one-line headline. Eg 'Look up YouTube channel earnings on Social Blade'.>",
  "summary": "<2-3 sentences. What this doc accomplishes + the prerequisites.>",
  "output_type": "{output_type}",
  "sections": [
    {{
      "heading": "<section title>",
      "intro": "<optional one-sentence intro. Omit for short docs.>",
      "blocks": [
        {{ "type": "paragraph", "text": "..." }},
        {{ "type": "step", "number": 1, "title": "<imperative one-liner>", "detail": "<optional 1-2 sentence elaboration>", "timestamp_seconds": <float or null> }},
        {{ "type": "callout", "kind": "tip"|"note"|"warning", "title": "<optional>", "text": "..." }},
        {{ "type": "image", "frame_id": "<frame_NNN from observations>", "caption": "<one short sentence>" }},
        {{ "type": "link", "url": "https://...", "label": "<short name>", "description": "<optional one phrase>" }},
        {{ "type": "list", "ordered": false, "intro": "<optional>", "items": ["...", "..."] }},
        {{ "type": "decision", "question": "...", "branches": [{{"label": "...", "outcome": "..."}}] }}
      ]
    }}
  ]
}}

Block types you may use: paragraph, step, callout, image, link, list, decision, code, table.
For STEP blocks, `number` should be the sequence WITHIN that section's steps (1, 2, 3...).
The `frame_id` on image blocks MUST match a frame_id from the observations above.

Now produce the JSON."""


def _build_transcript_text(transcript: list) -> str:
    if not transcript:
        return ""
    lines = []
    for seg in transcript:
        start = seg.get("start", 0)
        text = (seg.get("text") or "").strip()
        if text:
            lines.append(f"[{start:6.1f}s] {text}")
    return "\n".join(lines)


def _compact_observations(observations: list[dict]) -> str:
    """Pretty-but-compact JSON for Pass 2 to read."""
    return json.dumps(observations, indent=2, ensure_ascii=False)


# --- Public entry -------------------------------------------------------------
def generate_structured_document(
    transcript: list,
    frames_dir: str,
    user_context: Optional[str] = None,
    output_type: str = "sop",
    interval: int = 1,
) -> dict:
    """Two-pass pipeline. Returns a Document dict.

    Document shape matches the frontend renderer:
        {
          "title": str,
          "summary": str,
          "output_type": str,
          "sections": [
            {
              "heading": str,
              "intro": str | None,
              "blocks": [ {type: ..., ...}, ... ],
            },
          ],
        }
    """
    frame_paths = sorted(
        os.path.join(frames_dir, f)
        for f in os.listdir(frames_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )
    if not frame_paths:
        return _empty_document(output_type, "Empty recording")

    model = _get_model()
    logger.info(
        f"Pipeline start: {len(frame_paths)} frames, output_type={output_type}, "
        f"audio_segments={len(transcript or [])}"
    )

    # ─── PASS 1 ──────────────────────────────────────────────────────────────
    semaphore = asyncio.Semaphore(1)

    async def run_pass1():
        tasks = []
        for i, path in enumerate(frame_paths):
            # frame files are named frame_001.jpg, frame_002.jpg, etc.
            frame_id = os.path.splitext(os.path.basename(path))[0]
            ts = i * interval
            tasks.append(_pass1_one_frame(semaphore, model, frame_id, path, ts))
        return await asyncio.gather(*tasks)

    pass1_raw = asyncio.run(run_pass1())
    observations = [o for o in pass1_raw if o is not None]
    logger.info(f"Pass 1: {len(observations)}/{len(frame_paths)} frames produced observations")

    if not observations:
        return _empty_document(output_type, "Could not analyse frames")

    # ─── PASS 2 ──────────────────────────────────────────────────────────────
    duration_estimate = (
        max(o["timestamp"] for o in observations) if observations else 0.0
    )
    prompt = _build_pass2_prompt(
        output_type=output_type,
        user_context=user_context,
        transcript_text=_build_transcript_text(transcript),
        observations_json=_compact_observations(observations),
        duration_seconds=duration_estimate,
    )

    # Pass 2 = single sync call. We deliberately avoid asyncio.run() here:
    # the google.generativeai SDK's grpc client state from Pass 1's event loop
    # corrupts when a second loop is opened in the same process. The sync
    # path doesn't trigger the bug, and one call doesn't need parallelism.
    try:
        pass2_raw = _call_model_sync(model, prompt)
    except Exception as e:
        logger.error(f"Pass 2 failed completely: {e}")
        return _empty_document(output_type, "AI synthesis failed")

    try:
        document = json.loads(_clean_json(pass2_raw))
    except json.JSONDecodeError as e:
        logger.error(f"Pass 2 JSON parse failed: {e}; raw head: {pass2_raw[:300]!r}")
        return _empty_document(output_type, "AI returned malformed output")

    document = _normalise_document(document, output_type)
    logger.info(
        f"Pass 2: produced {len(document['sections'])} section(s), "
        f"{sum(len(s.get('blocks', [])) for s in document['sections'])} block(s)"
    )
    return document


def _empty_document(output_type: str, title: str) -> dict:
    return {
        "title": title,
        "summary": "We weren't able to produce a meaningful document from this recording.",
        "output_type": output_type,
        "sections": [],
    }


def _normalise_document(doc: dict, output_type: str) -> dict:
    """Trust-but-verify the Pass 2 JSON. Drop unknown block types, coerce
    missing fields, ensure block ordering is contiguous."""
    valid_block_types = {
        "paragraph", "step", "callout", "image", "link",
        "list", "decision", "code", "table",
    }
    valid_callout_kinds = {"tip", "note", "warning", "danger"}

    sections = []
    for s_idx, section in enumerate(doc.get("sections") or []):
        if not isinstance(section, dict):
            continue
        heading = (section.get("heading") or "").strip()
        if not heading:
            continue
        clean_blocks = []
        order = 1
        for block in section.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype not in valid_block_types:
                continue
            if btype == "callout" and block.get("kind") not in valid_callout_kinds:
                block["kind"] = "note"
            block["order"] = order
            order += 1
            clean_blocks.append(block)
        sections.append(
            {
                "id": f"s{s_idx + 1}",
                "order": s_idx + 1,
                "heading": heading,
                "intro": (section.get("intro") or "").strip() or None,
                "blocks": clean_blocks,
            }
        )

    return {
        "title": (doc.get("title") or "Untitled document").strip(),
        "summary": (doc.get("summary") or "").strip(),
        "output_type": (doc.get("output_type") or output_type).strip(),
        "sections": sections,
    }


# --- Legacy single-pass entry (kept for back-compat with old imports) --------
def generate_documentation_steps(transcript, frames_dir, interval=1):
    """Compatibility shim: returns a flat-step list mirroring the previous
    output shape, derived from the new two-pass document.

    Used only if some old caller hasn't been migrated. New callers should
    use generate_structured_document directly.
    """
    document = generate_structured_document(
        transcript=transcript,
        frames_dir=frames_dir,
        user_context=None,
        output_type="sop",
        interval=interval,
    )
    flat: list[dict] = []
    step_n = 0
    for section in document.get("sections", []):
        heading = section.get("heading") or "General"
        intro = section.get("intro") or None
        intro_used = False
        for block in section.get("blocks") or []:
            if block.get("type") != "step":
                continue
            step_n += 1
            flat.append(
                {
                    "step_number": step_n,
                    "timestamp": block.get("timestamp_seconds") or 0.0,
                    "title": heading,
                    "section_summary": intro if not intro_used else None,
                    "description": (block.get("title") or "").strip(),
                    "explanation": block.get("detail"),
                    "tip": None,
                    "note": None,
                    "url": None,
                    "image_path": None,
                }
            )
            intro_used = True
    return flat
