import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import settings
from app.transcriber import Transcript

logger = logging.getLogger(__name__)


@dataclass
class AdSegment:
    """Represents a detected ad segment with timing."""

    start: float  # Start time in seconds
    end: float  # End time in seconds
    source: str  # "sponsorblock" or "pattern"
    pattern: Optional[str] = None  # The pattern that matched (for pattern-based)

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "source": self.source,
            "pattern": self.pattern,
        }


def get_sponsorblock_segments(video_id: str) -> list[AdSegment]:
    """
    Fetch ad segments from SponsorBlock API.

    Args:
        video_id: YouTube video ID

    Returns:
        List of AdSegment objects from SponsorBlock
    """
    url = f"https://sponsor.ajay.app/api/skipSegments"
    params = {
        "videoID": video_id,
        "categories": '["sponsor", "selfpromo", "intro", "outro", "interaction"]',
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, params=params)

            if response.status_code == 404:
                # No segments found for this video
                logger.debug(f"No SponsorBlock data for video {video_id}")
                return []

            response.raise_for_status()
            data = response.json()

            segments = []
            for item in data:
                segment = item.get("segment", [])
                if len(segment) >= 2:
                    segments.append(
                        AdSegment(
                            start=segment[0],
                            end=segment[1],
                            source="sponsorblock",
                        )
                    )

            logger.info(f"Found {len(segments)} SponsorBlock segments for video {video_id}")
            return segments

    except httpx.HTTPError as e:
        logger.warning(f"SponsorBlock API error for {video_id}: {e}")
        return []
    except Exception as e:
        logger.error(f"Error fetching SponsorBlock data: {e}")
        return []


def detect_ads_from_transcript(
    transcript: Transcript,
    patterns: Optional[list[str]] = None,
    buffer_seconds: float = 2.0,
) -> list[AdSegment]:
    """
    Detect ad segments by pattern matching on transcript text.

    Args:
        transcript: The transcript to analyze
        patterns: List of regex patterns to match (uses defaults if None)
        buffer_seconds: Extra seconds to add before/after detected ads

    Returns:
        List of AdSegment objects
    """
    if patterns is None:
        patterns = settings.default_ad_patterns

    # Compile patterns
    compiled_patterns = []
    for pattern in patterns:
        try:
            compiled_patterns.append((pattern, re.compile(pattern, re.IGNORECASE)))
        except re.error as e:
            logger.warning(f"Invalid regex pattern '{pattern}': {e}")

    detected_segments = []

    for segment in transcript.segments:
        text = segment.text.lower()

        for pattern_str, pattern_re in compiled_patterns:
            if pattern_re.search(text):
                # Found a match - mark this segment as an ad
                ad_segment = AdSegment(
                    start=max(0, segment.start - buffer_seconds),
                    end=segment.end + buffer_seconds,
                    source="pattern",
                    pattern=pattern_str,
                )
                detected_segments.append(ad_segment)
                logger.debug(
                    f"Ad detected at {segment.start:.1f}s-{segment.end:.1f}s: "
                    f"pattern='{pattern_str}'"
                )
                break  # Don't match multiple patterns for same segment

    # Merge overlapping segments
    merged = merge_segments(detected_segments)

    logger.info(f"Detected {len(merged)} ad segments from transcript patterns")
    return merged


def merge_segments(segments: list[AdSegment], gap_threshold: float = 5.0) -> list[AdSegment]:
    """
    Merge overlapping or nearby ad segments.

    Args:
        segments: List of ad segments to merge
        gap_threshold: Maximum gap (seconds) between segments to merge them

    Returns:
        List of merged segments
    """
    if not segments:
        return []

    # Sort by start time
    sorted_segments = sorted(segments, key=lambda s: s.start)

    merged = [sorted_segments[0]]

    for current in sorted_segments[1:]:
        last = merged[-1]

        # Check if current overlaps or is close to last
        if current.start <= last.end + gap_threshold:
            # Extend the last segment
            merged[-1] = AdSegment(
                start=last.start,
                end=max(last.end, current.end),
                source=last.source if last.source == current.source else "mixed",
                pattern=last.pattern,
            )
        else:
            merged.append(current)

    return merged


def detect_ads(
    transcript: Optional[Transcript] = None,
    youtube_video_id: Optional[str] = None,
    patterns: Optional[list[str]] = None,
) -> list[AdSegment]:
    """
    Detect ads using available methods.

    For YouTube videos, tries SponsorBlock first.
    Falls back to transcript pattern matching.

    Args:
        transcript: Transcript to analyze (optional if using SponsorBlock)
        youtube_video_id: YouTube video ID for SponsorBlock lookup
        patterns: Custom ad patterns (uses defaults if None)

    Returns:
        List of detected ad segments
    """
    all_segments = []

    # Try SponsorBlock first for YouTube
    if youtube_video_id:
        sponsorblock_segments = get_sponsorblock_segments(youtube_video_id)
        all_segments.extend(sponsorblock_segments)

    # Also check transcript patterns (catches things SponsorBlock might miss)
    if transcript:
        pattern_segments = detect_ads_from_transcript(transcript, patterns)
        all_segments.extend(pattern_segments)

    # Merge all detected segments
    merged = merge_segments(all_segments)

    logger.info(f"Total ad segments detected: {len(merged)}")
    return merged


def calculate_ad_stats(segments: list[AdSegment]) -> tuple[int, int]:
    """
    Calculate statistics about detected ads.

    Returns:
        Tuple of (count, total_seconds)
    """
    count = len(segments)
    total_seconds = sum(int(s.end - s.start) for s in segments)
    return count, total_seconds
