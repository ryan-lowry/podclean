import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from faster_whisper import WhisperModel

from app.config import settings

logger = logging.getLogger(__name__)

# Global model instance (loaded once)
_model: Optional[WhisperModel] = None


@dataclass
class TranscriptSegment:
    """A segment of transcribed text with timing information."""

    start: float  # Start time in seconds
    end: float  # End time in seconds
    text: str

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
        }


@dataclass
class Transcript:
    """Full transcript with segments."""

    segments: list[TranscriptSegment]
    language: str
    duration: float

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "duration": self.duration,
            "segments": [s.to_dict() for s in self.segments],
        }

    def get_full_text(self) -> str:
        """Get the full transcript as a single string."""
        return " ".join(s.text for s in self.segments)


def get_model() -> WhisperModel:
    """Get or initialize the Whisper model."""
    global _model
    if _model is None:
        logger.info(f"Loading Whisper model: {settings.whisper_model}")
        _model = WhisperModel(
            settings.whisper_model,
            device="cpu",
            compute_type="int8",  # Use int8 for faster CPU inference
        )
        logger.info("Whisper model loaded")
    return _model


def transcribe_audio(audio_path: str) -> Transcript:
    """
    Transcribe an audio file using faster-whisper.

    Args:
        audio_path: Path to the audio file

    Returns:
        Transcript object with segments and timing

    Raises:
        Exception: If transcription fails
    """
    model = get_model()

    # Get audio duration for progress tracking
    audio_filename = os.path.basename(audio_path)
    logger.info(f"Starting transcription: {audio_filename}")

    segments_result, info = model.transcribe(
        audio_path,
        beam_size=5,
        language=None,  # Auto-detect language
        vad_filter=True,  # Filter out silence/non-speech
        vad_parameters=dict(
            min_silence_duration_ms=500,
        ),
    )

    segments = []
    last_logged_minute = 0
    for segment in segments_result:
        # Log progress every minute of audio processed
        current_minute = int(segment.end // 60)
        if current_minute > last_logged_minute and current_minute % 2 == 0:
            logger.info(f"Transcribing... {current_minute} minutes processed")
            last_logged_minute = current_minute

        segments.append(
            TranscriptSegment(
                start=segment.start,
                end=segment.end,
                text=segment.text.strip(),
            )
        )

    duration = segments[-1].end if segments else 0.0

    logger.info(
        f"Transcription complete: {len(segments)} segments, "
        f"{duration:.1f}s duration, language={info.language}"
    )

    return Transcript(
        segments=segments,
        language=info.language,
        duration=duration,
    )


def save_transcript(transcript: Transcript, output_path: str) -> None:
    """Save transcript to a JSON file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(transcript.to_dict(), f, indent=2, ensure_ascii=False)


def load_transcript(path: str) -> Optional[Transcript]:
    """Load transcript from a JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        segments = [
            TranscriptSegment(
                start=s["start"],
                end=s["end"],
                text=s["text"],
            )
            for s in data["segments"]
        ]

        return Transcript(
            segments=segments,
            language=data["language"],
            duration=data["duration"],
        )
    except Exception as e:
        logger.error(f"Error loading transcript from {path}: {e}")
        return None
