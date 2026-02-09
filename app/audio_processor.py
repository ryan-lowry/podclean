import logging
import os
import subprocess
from typing import Optional

from app.ad_detector import AdSegment
from app.config import settings

logger = logging.getLogger(__name__)


def get_audio_duration(audio_path: str) -> Optional[float]:
    """Get the duration of an audio file in seconds."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"Error getting audio duration: {e}")
        return None


def remove_segments(
    input_path: str,
    output_path: str,
    segments_to_remove: list[AdSegment],
) -> bool:
    """
    Remove specified segments from an audio file.

    Args:
        input_path: Path to input audio file
        output_path: Path to output audio file
        segments_to_remove: List of segments to cut out

    Returns:
        True if successful, False otherwise
    """
    if not segments_to_remove:
        # No segments to remove, just convert to MP3
        return convert_to_mp3(input_path, output_path)

    # Get total duration
    duration = get_audio_duration(input_path)
    if duration is None:
        logger.error("Could not determine audio duration")
        return False

    # Build list of segments to KEEP (inverse of segments to remove)
    keep_segments = []
    current_pos = 0.0

    # Sort segments by start time
    sorted_segments = sorted(segments_to_remove, key=lambda s: s.start)

    for seg in sorted_segments:
        if seg.start > current_pos:
            # Keep the segment before this ad
            keep_segments.append((current_pos, seg.start))
        current_pos = max(current_pos, seg.end)

    # Keep the final segment after last ad
    if current_pos < duration:
        keep_segments.append((current_pos, duration))

    if not keep_segments:
        logger.warning("No segments to keep after removing ads")
        return False

    # Build ffmpeg filter
    filter_parts = []
    for i, (start, end) in enumerate(keep_segments):
        filter_parts.append(f"between(t,{start:.3f},{end:.3f})")

    # Create the aselect filter
    select_filter = "+".join(filter_parts)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", input_path,
            "-af", f"aselect='{select_filter}',asetpts=N/SR/TB",
            "-acodec", "libmp3lame",
            "-ab", "192k",
            "-ar", "44100",
            output_path,
        ]

        logger.info(f"Running ffmpeg to remove {len(segments_to_remove)} ad segments")
        logger.debug(f"Command: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info(f"Successfully processed audio: {output_path}")
            return True
        else:
            logger.error("Output file not created or empty")
            return False

    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg error: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Error processing audio: {e}")
        return False


def convert_to_mp3(input_path: str, output_path: str) -> bool:
    """
    Convert an audio file to MP3 format.

    Args:
        input_path: Path to input audio file
        output_path: Path to output MP3 file

    Returns:
        True if successful, False otherwise
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-acodec", "libmp3lame",
            "-ab", "192k",
            "-ar", "44100",
            output_path,
        ]

        subprocess.run(cmd, capture_output=True, check=True)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True
        return False

    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg conversion error: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Error converting audio: {e}")
        return False


def cleanup_original(original_path: str) -> None:
    """Remove the original downloaded file after processing."""
    try:
        if os.path.exists(original_path):
            os.remove(original_path)
            logger.debug(f"Removed original file: {original_path}")
    except Exception as e:
        logger.warning(f"Could not remove original file: {e}")
