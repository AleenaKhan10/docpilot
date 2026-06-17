import os
import subprocess

import numpy as np
from PIL import Image

from core.logger import setup_logging

logger = setup_logging()


def extract_audio(video_path: str, output_path: str):
    """Extract MP3 audio track from the video via ffmpeg.
    Returns the output path on success, None if no audio was extracted."""
    command = [
        "ffmpeg", "-i", video_path, "-q:a", "0", "-map", "a", output_path, "-y"
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path if os.path.exists(output_path) else None


def extract_frames(video_path: str, output_dir: str, interval: int = 1):
    """Sample frames at 1 frame per `interval` seconds, then prune near-
    duplicates so we don't pay the VLM to describe identical screenshots."""
    os.makedirs(output_dir, exist_ok=True)
    command = [
        "ffmpeg", "-i", video_path,
        "-vf", f"fps=1/{interval}",
        f"{output_dir}/frame_%03d.jpg",
        "-y",
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Drop static frames AFTER extraction so the AI gets fewer screenshots
    # to describe — saves real money on long videos.
    _filter_static_frames(output_dir)


# MSE threshold below which two consecutive frames are treated as duplicates.
# 100x100 downsample preserves enough detail to catch text changes & cursor
# moves, while still being fast to diff. 2.0 was chosen empirically: 30 was
# too aggressive (lost typing frames); below 1 kept too many idle frames.
_MSE_DUPLICATE_THRESHOLD = 2.0
_COMPARE_SIZE = (100, 100)


def _filter_static_frames(frames_dir: str) -> None:
    """Remove near-identical consecutive frames using a small-MSE check."""
    logger.info("Smart filter: analysing frames for duplication...")

    frames = sorted(
        os.path.join(frames_dir, f)
        for f in os.listdir(frames_dir)
        if f.endswith(".jpg")
    )
    if not frames:
        return

    unique_frames = [frames[0]]
    deleted = 0
    prev_image = Image.open(frames[0]).convert("L").resize(_COMPARE_SIZE)

    for path in frames[1:]:
        try:
            curr_image = Image.open(path).convert("L").resize(_COMPARE_SIZE)
            mse = np.mean(
                (np.array(prev_image) - np.array(curr_image)) ** 2
            )
            if mse < _MSE_DUPLICATE_THRESHOLD:
                os.remove(path)
                deleted += 1
            else:
                unique_frames.append(path)
                prev_image = curr_image
        except Exception as e:
            logger.error(f"Could not filter frame {path}: {e}")

    remaining = len(unique_frames)
    logger.info(
        f"Optimization: removed {deleted} static frames; kept {remaining} "
        f"unique keyframes."
    )

    # If almost everything got removed on a long video, the threshold is
    # probably wrong for this recording. We can't restore the deleted files
    # but the log gives the operator a signal to tune.
    if remaining < 3 and len(frames) > 10:
        logger.warning(
            "Too many frames removed by dedup. Consider lowering the MSE "
            "threshold below 2.0 for this kind of content."
        )
