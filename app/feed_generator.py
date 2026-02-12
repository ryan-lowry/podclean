import logging
import os
from datetime import datetime, timezone

from feedgen.feed import FeedGenerator

from app.config import settings
from app.models import Podcast, Episode, EpisodeStatus

logger = logging.getLogger(__name__)


def generate_podcast_feed(podcast: Podcast, episodes: list[Episode]) -> str:
    """
    Generate an RSS feed for a podcast.

    Args:
        podcast: The podcast to generate a feed for
        episodes: List of completed episodes

    Returns:
        RSS XML as a string
    """
    fg = FeedGenerator()
    fg.load_extension("podcast")

    # Feed metadata
    feed_url = f"{settings.base_url}/feeds/{podcast.slug}.xml"
    fg.id(feed_url)
    fg.title(f"{podcast.name} (Ad-Free)")
    fg.description(f"Ad-free version of {podcast.name}, processed by PodClean")
    fg.link(href=feed_url, rel="self")
    fg.link(href=settings.base_url, rel="alternate")
    fg.language("en")
    fg.generator("PodClean")

    # Podcast-specific metadata
    fg.podcast.itunes_category("Technology")
    fg.podcast.itunes_explicit("no")

    # Podcast artwork/thumbnail
    if podcast.thumbnail_file:
        image_url = f"{settings.base_url}/thumbnails/{podcast.thumbnail_file}"
        fg.image(url=image_url, title=podcast.name, link=settings.base_url)
        fg.podcast.itunes_image(image_url)

    # Add episodes
    for episode in episodes:
        if episode.status != EpisodeStatus.COMPLETED:
            continue

        if not episode.processed_file:
            continue

        fe = fg.add_entry()

        # Episode ID
        fe.id(f"{settings.base_url}/episodes/{podcast.slug}/{episode.source_id}")

        # Title
        fe.title(episode.title)

        # Publication date
        if episode.published_at:
            fe.pubDate(episode.published_at.replace(tzinfo=timezone.utc))
        else:
            fe.pubDate(episode.created_at.replace(tzinfo=timezone.utc))

        # Episode URL
        episode_url = f"{settings.base_url}/episodes/{podcast.slug}/{os.path.basename(episode.processed_file)}"
        fe.link(href=episode_url)

        # Enclosure (audio file)
        file_path = os.path.join(settings.processed_dir, podcast.slug, os.path.basename(episode.processed_file))
        file_size = 0
        if os.path.exists(file_path):
            file_size = os.path.getsize(file_path)

        fe.enclosure(episode_url, str(file_size), "audio/mpeg")

        # Description
        description = f"Ad-free version of: {episode.title}"
        if episode.ads_removed_count > 0:
            description += f"\n\nRemoved {episode.ads_removed_count} ad segments ({episode.ads_removed_seconds}s total)"
        fe.description(description)

        # Duration (if available)
        if episode.duration_seconds:
            # Subtract removed ad time for accurate duration
            clean_duration = episode.duration_seconds - episode.ads_removed_seconds
            fe.podcast.itunes_duration(max(0, clean_duration))

    return fg.rss_str(pretty=True).decode("utf-8")


def save_feed(podcast: Podcast, episodes: list[Episode]) -> str:
    """
    Generate and save the RSS feed for a podcast.

    Args:
        podcast: The podcast
        episodes: List of episodes

    Returns:
        Path to the saved feed file
    """
    # Generate feed content
    feed_xml = generate_podcast_feed(podcast, episodes)

    # Ensure feeds directory exists
    feeds_dir = os.path.join(settings.processed_dir, "feeds")
    os.makedirs(feeds_dir, exist_ok=True)

    # Save feed
    feed_path = os.path.join(feeds_dir, f"{podcast.slug}.xml")
    with open(feed_path, "w", encoding="utf-8") as f:
        f.write(feed_xml)

    logger.info(f"Saved feed for {podcast.name}: {feed_path}")
    return feed_path


def generate_index_page(podcasts: list[Podcast]) -> str:
    """
    Generate an HTML index page listing all podcast feeds.

    Args:
        podcasts: List of all podcasts

    Returns:
        HTML content as a string
    """
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PodClean Feeds</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 800px; margin: 50px auto; padding: 20px; }
        h1 { color: #333; }
        .podcast { background: #f5f5f5; padding: 15px; margin: 10px 0; border-radius: 8px; }
        .podcast h2 { margin: 0 0 10px 0; font-size: 1.2em; }
        .feed-url { font-family: monospace; background: #fff; padding: 8px;
                    border: 1px solid #ddd; border-radius: 4px; word-break: break-all; }
        a { color: #0066cc; }
    </style>
</head>
<body>
    <h1>PodClean Feeds</h1>
    <p>Subscribe to these feeds in your podcast app:</p>
"""

    for podcast in podcasts:
        if not podcast.enabled:
            continue
        feed_url = f"{settings.base_url}/feeds/{podcast.slug}.xml"
        html += f"""
    <div class="podcast">
        <h2>{podcast.name}</h2>
        <div class="feed-url">
            <a href="{feed_url}">{feed_url}</a>
        </div>
    </div>
"""

    html += """
</body>
</html>
"""
    return html
