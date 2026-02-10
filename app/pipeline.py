import logging
import os
from datetime import datetime
from typing import Optional, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Podcast, Episode, EpisodeStatus, PodcastType
from app.downloader import get_episode_list, download_episode, get_youtube_video_id
from app.transcriber import transcribe_audio, save_transcript
from app.ad_detector import detect_ads, calculate_ad_stats
from app.audio_processor import remove_segments, cleanup_original
from app.feed_generator import save_feed
from app.cleanup import cleanup_old_episodes

logger = logging.getLogger(__name__)

# Type for status callback
StatusCallback = Optional[Callable[[str], None]]


async def process_podcast(
    db: AsyncSession,
    podcast: Podcast,
    status_callback: StatusCallback = None,
) -> int:
    """
    Process a single podcast: download, transcribe, remove ads.

    Args:
        db: Database session
        podcast: Podcast to process
        status_callback: Optional callback to report status updates

    Returns:
        Number of episodes processed
    """
    def update_status(msg: str):
        if status_callback:
            status_callback(msg)

    logger.info(f"Processing podcast: {podcast.name}")
    update_status(f"Processing: {podcast.name}")
    processed_count = 0

    # Get list of available episodes
    episodes = get_episode_list(podcast, limit=settings.download_check_limit)
    logger.info(f"Found {len(episodes)} recent episodes for {podcast.name}")

    for episode_info in episodes:
        # Check if we already have this episode
        existing = await db.execute(
            select(Episode).where(
                Episode.podcast_id == podcast.id,
                Episode.source_id == episode_info.source_id,
            )
        )
        if existing.scalar_one_or_none():
            logger.debug(f"Skipping already processed: {episode_info.title}")
            continue

        # Create episode record
        episode = Episode(
            podcast_id=podcast.id,
            title=episode_info.title,
            original_url=episode_info.url,
            source_id=episode_info.source_id,
            published_at=episode_info.published_at,
            duration_seconds=episode_info.duration_seconds,
            status=EpisodeStatus.PENDING,
        )
        db.add(episode)
        await db.commit()

        try:
            # Download
            episode.status = EpisodeStatus.DOWNLOADING
            await db.commit()
            update_status(f"Downloading: {episode_info.title[:40]}...")

            downloaded_path = download_episode(podcast, episode_info)
            if not downloaded_path:
                raise Exception("Download failed")

            episode.original_file = downloaded_path

            # Transcribe
            episode.status = EpisodeStatus.TRANSCRIBING
            await db.commit()
            update_status(f"Transcribing: {episode_info.title[:40]}...")

            # Check for SponsorBlock data first (YouTube only)
            youtube_video_id = None
            if podcast.podcast_type == PodcastType.YOUTUBE:
                youtube_video_id = get_youtube_video_id(episode_info.url)

            transcript = transcribe_audio(downloaded_path)

            # Save transcript
            transcript_dir = os.path.join(settings.transcripts_dir, podcast.slug)
            os.makedirs(transcript_dir, exist_ok=True)
            transcript_path = os.path.join(transcript_dir, f"{episode_info.source_id}.json")
            save_transcript(transcript, transcript_path)
            episode.transcript_file = transcript_path

            # Update duration from transcript if not set
            if not episode.duration_seconds:
                episode.duration_seconds = int(transcript.duration)

            # Detect ads
            episode.status = EpisodeStatus.DETECTING_ADS
            await db.commit()
            update_status(f"Detecting ads: {episode_info.title[:40]}...")

            ad_segments = detect_ads(
                transcript=transcript,
                youtube_video_id=youtube_video_id,
            )

            count, seconds = calculate_ad_stats(ad_segments)
            episode.ads_removed_count = count
            episode.ads_removed_seconds = seconds

            # Process audio
            episode.status = EpisodeStatus.PROCESSING_AUDIO
            await db.commit()
            update_status(f"Processing audio: {episode_info.title[:40]}...")

            output_dir = os.path.join(settings.processed_dir, podcast.slug)
            os.makedirs(output_dir, exist_ok=True)
            output_filename = f"{episode_info.source_id}.mp3"
            output_path = os.path.join(output_dir, output_filename)

            success = remove_segments(downloaded_path, output_path, ad_segments)
            if not success:
                raise Exception("Audio processing failed")

            episode.processed_file = output_filename

            # Cleanup original download
            cleanup_original(downloaded_path)
            episode.original_file = None

            # Mark as completed
            episode.status = EpisodeStatus.COMPLETED
            episode.processed_at = datetime.utcnow()
            await db.commit()

            processed_count += 1
            logger.info(
                f"Completed: {episode.title} "
                f"(removed {count} ads, {seconds}s)"
            )
            update_status(f"Completed: {episode_info.title[:40]}")

        except Exception as e:
            logger.error(f"Error processing {episode_info.title}: {e}")
            episode.status = EpisodeStatus.FAILED
            episode.error_message = str(e)
            await db.commit()

    return processed_count


async def run_pipeline(
    db: AsyncSession,
    status_callback: StatusCallback = None,
) -> dict:
    """
    Run the full processing pipeline for all enabled podcasts.

    Args:
        db: Database session
        status_callback: Optional callback to report status updates

    Returns:
        Summary statistics
    """
    def update_status(msg: str):
        if status_callback:
            status_callback(msg)

    logger.info("Starting pipeline run")
    update_status("Starting pipeline...")
    start_time = datetime.utcnow()

    stats = {
        "podcasts_processed": 0,
        "episodes_processed": 0,
        "episodes_cleaned_up": 0,
        "errors": [],
    }

    # Get all enabled podcasts
    result = await db.execute(
        select(Podcast).where(Podcast.enabled == True)
    )
    podcasts = list(result.scalars().all())

    logger.info(f"Found {len(podcasts)} enabled podcasts")
    update_status(f"Found {len(podcasts)} podcasts")

    for podcast in podcasts:
        try:
            # Process new episodes
            processed = await process_podcast(db, podcast, status_callback)
            stats["episodes_processed"] += processed
            stats["podcasts_processed"] += 1

            # Cleanup old episodes
            cleaned = await cleanup_old_episodes(db, podcast)
            stats["episodes_cleaned_up"] += cleaned

            # Regenerate feed
            episodes_result = await db.execute(
                select(Episode)
                .where(Episode.podcast_id == podcast.id)
                .where(Episode.status == EpisodeStatus.COMPLETED)
                .order_by(Episode.published_at.desc().nullslast())
            )
            episodes = list(episodes_result.scalars().all())
            save_feed(podcast, episodes)

        except Exception as e:
            logger.error(f"Error processing podcast {podcast.name}: {e}")
            stats["errors"].append(f"{podcast.name}: {str(e)}")

    duration = (datetime.utcnow() - start_time).total_seconds()
    logger.info(
        f"Pipeline complete: {stats['episodes_processed']} episodes processed "
        f"in {duration:.1f}s"
    )

    return stats
