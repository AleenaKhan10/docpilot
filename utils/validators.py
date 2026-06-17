import magic
from fastapi import UploadFile, HTTPException

from core.config import settings
from core.logger import setup_logging

logger = setup_logging()

ALLOWED_MIME_TYPES = ("video/mp4", "video/webm", "video/quicktime")


async def validate_video_file_signature(file: UploadFile) -> None:
    """Reject anything not actually a supported video format.

    Reads only the first 2048 bytes (the file header) and uses libmagic to
    detect the real MIME type. Doesn't trust file.content_type or the
    extension.
    """
    header_bytes = await file.read(2048)
    mime_type = magic.from_buffer(header_bytes, mime=True)
    await file.seek(0)

    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid file type: {mime_type}. "
                f"Only MP4, MOV and WebM are allowed."
            ),
        )


def enforce_upload_size(file: UploadFile) -> None:
    """Reject if the declared Content-Length exceeds the max upload size."""
    size = getattr(file, "size", None)
    if size is not None and size > settings.MAX_UPLOAD_BYTES:
        mb = size / (1024 * 1024)
        limit_mb = settings.MAX_UPLOAD_BYTES / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"File is {mb:.1f} MB, max upload is {limit_mb:.0f} MB.",
        )


def get_video_duration_seconds(path: str) -> float:
    """Run ffprobe and return duration in seconds. Raises HTTPException if the
    binary is missing or the file can't be parsed.
    """
    import subprocess

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        # ffprobe not on PATH — treat as a server-side config issue.
        raise HTTPException(
            status_code=500,
            detail="Server is missing ffprobe; cannot validate video duration.",
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=400, detail="Could not analyze video (probe timed out)."
        )

    if result.returncode != 0:
        raise HTTPException(
            status_code=400,
            detail="Could not read video duration. File may be corrupt.",
        )

    try:
        return float(result.stdout.strip())
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Could not parse video duration."
        )


def enforce_video_duration(path: str) -> float:
    """Probe the saved file's duration. Reject if over the configured cap.
    Returns the duration so the caller can persist / log it.
    """
    duration = get_video_duration_seconds(path)
    if duration > settings.MAX_VIDEO_DURATION_SECONDS:
        limit_min = settings.MAX_VIDEO_DURATION_SECONDS / 60
        raise HTTPException(
            status_code=413,
            detail=(
                f"Video is {duration:.0f}s, max duration is {limit_min:.0f} min."
            ),
        )
    return duration
