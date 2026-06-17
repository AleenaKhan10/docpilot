import os
import time

from faster_whisper import WhisperModel

from core.logger import setup_logging

logger = setup_logging()

# `base` strikes a good speed/accuracy balance on CPU. Drop to `tiny` if cold
# transcription latency matters; upgrade to `small`/`medium` for higher
# accuracy on noisy or multilingual audio.
MODEL_SIZE = "base"

# Switch to "cuda" + "float16" when a GPU is available.
DEVICE = "cpu"
COMPUTE_TYPE = "int8"

logger.info(f"Loading Faster-Whisper model ({MODEL_SIZE})...")

try:
    # Module-level singleton: first import downloads the weights (~150 MB)
    # and keeps the model resident for all subsequent calls.
    model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    logger.info("Faster-Whisper model loaded.")
except Exception as e:
    logger.error(f"Faster-Whisper model failed to load: {e}")
    model = None


def transcribe_audio_local(audio_path: str):
    """Transcribe an audio file. Returns a list of {start, end, text} dicts.
    Empty list on any failure (caller must tolerate empty transcripts)."""
    if not model:
        logger.error("Whisper model not loaded; skipping transcription.")
        return []
    if not os.path.exists(audio_path):
        logger.error(f"Audio file not found: {audio_path}")
        return []

    logger.info(f"Transcribing: {audio_path}")
    start_time = time.time()

    try:
        # beam_size=5 explores multiple hypotheses for better accuracy
        # at modest extra cost. Drop to 1 for fastest-possible mode.
        segments, info = model.transcribe(audio_path, beam_size=5)

        logger.info(
            f"Detected language: '{info.language}' "
            f"(probability {info.language_probability:.2f})"
        )

        transcript_data = []
        for segment in segments:
            transcript_data.append(
                {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text.strip(),
                }
            )

        duration = time.time() - start_time
        logger.info(
            f"Transcription complete in {duration:.2f}s "
            f"({len(transcript_data)} segments)."
        )
        return transcript_data

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return []
