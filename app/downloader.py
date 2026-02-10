import logging
import os
import re
from datetime import datetime
from typing import Optional

import yt_dlp

from app.config import settings
from app.models import Podcast, PodcastType

logger = logging.getLogger(__name__)


class EpisodeInfo:
    """Represents metadata about a downloadable episode."""

    def __init__(
        self,
        source_id: str,
        title: str,
        url: str,
        published_at: Optional[datetime] = None,
        duration_seconds: Optional[int] = None,
    ):
        self.source_id = source_id
        self.title = title
        self.url = url
        self.published_at = published_at
        self.duration_seconds = duration_seconds


def sanitize_filename(name: str) -> str:
    """Create a safe filename from a string."""
    # Remove or replace unsafe characters
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", "_", name)
    return name[:200]  # Limit length


def normalize_youtube_url(url: str) -> str:
    """
    Normalize YouTube URLs to ensure we get video listings.

    Channel URLs without a tab specified return tabs (Videos, Live, Shorts)
    instead of actual videos. This appends /videos to channel URLs.
    """
    # Match YouTube channel URLs
    # Formats: /channel/UC..., /c/ChannelName, /@handle
    channel_patterns = [
        r"(youtube\.com/channel/[^/]+)/?$",
        r"(youtube\.com/c/[^/]+)/?$",
        r"(youtube\.com/@[^/]+)/?$",
    ]

    for pattern in channel_patterns:
        if re.search(pattern, url):
            # Remove trailing slash if present and append /videos
            url = url.rstrip("/") + "/videos"
            break

    return url


def get_episode_list(podcast: Podcast, limit: int = 5) -> list[EpisodeInfo]:
    """
    Fetch list of recent episodes from a podcast source.

    Args:
        podcast: The podcast to fetch episodes for
        limit: Maximum number of episodes to return

    Returns:
        List of EpisodeInfo objects
    """
    episodes = []

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": limit,
    }

    try:
        # Normalize YouTube channel URLs to get actual videos
        fetch_url = normalize_youtube_url(podcast.url)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(fetch_url, download=False)

            if info is None:
                logger.warning(f"No info returned for {podcast.name}")
                return []

            # Handle playlists (YouTube channels/playlists, RSS feeds)
            entries = info.get("entries", [info])
            extractor = info.get("extractor", "").lower()
            is_youtube = "youtube" in extractor

            for entry in entries:
                if entry is None:
                    continue

                # Get the video/episode ID
                source_id = entry.get("id", "")
                title = entry.get("title", "Unknown Episode")

                # For YouTube, construct proper video URL from ID
                if is_youtube and source_id:
                    # YouTube video IDs are 11 characters
                    if len(source_id) == 11:
                        url = f"https://www.youtube.com/watch?v={source_id}"
                    else:
                        # Might be a different format, try webpage_url
                        url = entry.get("webpage_url") or entry.get("url", "")
                else:
                    url = entry.get("webpage_url") or entry.get("url", "")

                # Skip if no valid URL
                if not url:
                    logger.warning(f"Skipping entry with no URL: {title}")
                    continue

                # Parse upload date if available
                published_at = None
                upload_date = entry.get("upload_date")
                if upload_date:
                    try:
                        published_at = datetime.strptime(upload_date, "%Y%m%d")
                    except ValueError:
                        pass

                duration = entry.get("duration")

                episodes.append(
                    EpisodeInfo(
                        source_id=source_id,
                        title=title,
                        url=url,
                        published_at=published_at,
                        duration_seconds=int(duration) if duration else None,
                    )
                )

            logger.info(f"Found {len(episodes)} episodes from {podcast.name} (extractor: {extractor})")

    except Exception as e:
        logger.error(f"Error fetching episodes for {podcast.name}: {e}")

    return episodes


def _make_progress_hook(episode_title: str):
    """Create a progress hook that logs download progress."""
    last_percent = [0]  # Use list to allow mutation in closure

    def hook(d):
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '?%').strip()
            speed = d.get('_speed_str', '?').strip()
            eta = d.get('_eta_str', '?').strip()

            # Only log every 10% to avoid spam
            try:
                current = int(float(percent.replace('%', '')))
                if current >= last_percent[0] + 10 or current == 100:
                    logger.info(f"Downloading {episode_title[:30]}... {percent} at {speed}, ETA: {eta}")
                    last_percent[0] = current
            except (ValueError, TypeError):
                pass

        elif d['status'] == 'finished':
            logger.info(f"Download complete: {episode_title[:40]}, converting to MP3...")

        elif d['status'] == 'error':
            logger.error(f"Download error: {episode_title}")

    return hook


def download_episode(
    podcast: Podcast,
    episode_info: EpisodeInfo,
) -> Optional[str]:
    """
    Download an episode and return the path to the downloaded file.

    Args:
        podcast: The podcast this episode belongs to
        episode_info: Information about the episode to download

    Returns:
        Path to the downloaded audio file, or None if download failed
    """
    # Create podcast-specific download directory
    podcast_dir = os.path.join(settings.downloads_dir, podcast.slug)
    os.makedirs(podcast_dir, exist_ok=True)

    # Generate output filename
    filename = sanitize_filename(f"{episode_info.source_id}_{episode_info.title}")
    output_template = os.path.join(podcast_dir, f"{filename}.%(ext)s")

    logger.info(f"Starting download: {episode_info.title}")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_make_progress_hook(episode_info.title)],
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(episode_info.url, download=True)

            if info is None:
                logger.error(f"No info returned for episode: {episode_info.title}")
                return None

            # Find the downloaded file
            # yt-dlp with postprocessor will output .mp3
            expected_path = os.path.join(podcast_dir, f"{filename}.mp3")
            if os.path.exists(expected_path):
                return expected_path

            # Fallback: look for any audio file with this base name
            for ext in [".mp3", ".m4a", ".opus", ".webm", ".wav"]:
                path = os.path.join(podcast_dir, f"{filename}{ext}")
                if os.path.exists(path):
                    return path

            logger.error(f"Downloaded file not found for: {episode_info.title}")
            return None

    except Exception as e:
        logger.error(f"Error downloading episode {episode_info.title}: {e}")
        return None


def get_youtube_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from a URL."""
    patterns = [
        r"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})",
        r"youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None
