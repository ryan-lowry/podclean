import logging
import os
from datetime import datetime

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Podcast, Episode, EpisodeStatus, Settings

logger = logging.getLogger(__name__)


async def cleanup_old_episodes(db: AsyncSession, podcast: Podcast) -> int:
    """
    Remove old episodes beyond the retention limit.

    Keeps the most recent N episodes (by published_at or created_at).

    Args:
        db: Database session
        podcast: Podcast to clean up

    Returns:
        Number of episodes removed
    """
    # Get all completed episodes for this podcast, ordered by date
    query = (
        select(Episode)
        .where(Episode.podcast_id == podcast.id)
        .where(Episode.status == EpisodeStatus.COMPLETED)
        .order_by(Episode.published_at.desc().nullslast(), Episode.created_at.desc())
    )
    result = await db.execute(query)
    episodes = list(result.scalars().all())

    # Get episodes to keep from database settings
    episodes_to_keep = await Settings.get_int(db, "episodes_to_keep")

    if len(episodes) <= episodes_to_keep:
        return 0

    # Episodes to remove (beyond retention limit)
    episodes_to_remove = episodes[episodes_to_keep:]
    removed_count = 0

    for episode in episodes_to_remove:
        # Delete processed file
        if episode.processed_file:
            processed_path = os.path.join(
                settings.processed_dir,
                podcast.slug,
                os.path.basename(episode.processed_file),
            )
            if os.path.exists(processed_path):
                try:
                    os.remove(processed_path)
                    logger.debug(f"Removed processed file: {processed_path}")
                except Exception as e:
                    logger.warning(f"Could not remove file {processed_path}: {e}")

        # Delete transcript file
        if episode.transcript_file:
            transcript_path = os.path.join(
                settings.transcripts_dir,
                podcast.slug,
                os.path.basename(episode.transcript_file),
            )
            if os.path.exists(transcript_path):
                try:
                    os.remove(transcript_path)
                except Exception as e:
                    logger.warning(f"Could not remove transcript {transcript_path}: {e}")

        # Delete from database
        await db.delete(episode)
        removed_count += 1
        logger.info(f"Removed old episode: {episode.title}")

    await db.commit()
    return removed_count


async def cleanup_failed_episodes(db: AsyncSession, max_age_hours: int = 24) -> int:
    """
    Remove episodes that failed processing and are older than max_age.

    This allows them to be re-downloaded on the next run.

    Args:
        db: Database session
        max_age_hours: Maximum age of failed episodes to keep

    Returns:
        Number of episodes removed
    """
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)

    query = (
        select(Episode)
        .where(Episode.status == EpisodeStatus.FAILED)
        .where(Episode.created_at < cutoff)
    )
    result = await db.execute(query)
    failed_episodes = list(result.scalars().all())

    for episode in failed_episodes:
        # Clean up any partial files
        if episode.original_file and os.path.exists(episode.original_file):
            try:
                os.remove(episode.original_file)
            except Exception:
                pass

        await db.delete(episode)

    await db.commit()

    if failed_episodes:
        logger.info(f"Cleaned up {len(failed_episodes)} old failed episodes")

    return len(failed_episodes)


async def cleanup_orphaned_files(db: AsyncSession) -> int:
    """
    Remove files that don't have corresponding database entries.

    Returns:
        Number of files removed
    """
    removed_count = 0

    # Get all known processed files from database
    query = select(Episode.processed_file).where(Episode.processed_file.isnot(None))
    result = await db.execute(query)
    known_files = {os.path.basename(f) for f in result.scalars().all() if f}

    # Walk processed directory
    for podcast_dir in os.listdir(settings.processed_dir):
        if podcast_dir == "feeds":
            continue

        podcast_path = os.path.join(settings.processed_dir, podcast_dir)
        if not os.path.isdir(podcast_path):
            continue

        for filename in os.listdir(podcast_path):
            if filename not in known_files:
                file_path = os.path.join(podcast_path, filename)
                try:
                    os.remove(file_path)
                    removed_count += 1
                    logger.debug(f"Removed orphaned file: {file_path}")
                except Exception as e:
                    logger.warning(f"Could not remove orphaned file: {e}")

    if removed_count:
        logger.info(f"Removed {removed_count} orphaned files")

    return removed_count
