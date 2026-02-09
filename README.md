# PodClean

A self-hosted podcast processor that automatically downloads podcasts from RSS feeds or YouTube, removes ads/sponsors, and serves clean episodes via RSS for your podcast app.

## Features

- **Multi-source support**: Download from RSS feeds or YouTube channels/playlists
- **Ad removal**: Uses Whisper transcription + pattern matching to detect and remove ads
- **SponsorBlock integration**: For YouTube videos, checks SponsorBlock first for community-submitted ad segments
- **Web UI**: Simple interface to manage podcasts and view processing status
- **RSS feed generation**: Each podcast gets its own RSS feed compatible with podcast apps like Pocket Casts
- **Scheduled processing**: Runs automatically on a cron schedule (default: 2am daily)
- **Retention management**: Automatically keeps only the last N episodes per podcast

## Requirements

- Docker and Docker Compose
- ~4GB RAM (for Whisper transcription)
- Storage for downloaded/processed episodes

## Quick Start

### Using Proxmox Community Scripts

1. Create a Docker LXC on your Proxmox server:
   ```bash
   bash -c "$(wget -qLO - https://github.com/community-scripts/ProxmoxVE/raw/main/ct/docker.sh)"
   ```

2. SSH into the container and deploy:
   ```bash
   cd /opt
   git clone https://github.com/ryan-lowry/podclean.git
   cd podclean
   cp .env.example .env
   nano .env  # Set BASE_URL to your container's IP
   docker compose up -d --build
   ```

### Manual Docker Setup

```bash
git clone https://github.com/ryan-lowry/podclean.git
cd podclean
cp .env.example .env
# Edit .env with your settings
docker compose up -d --build
```

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Description | Default |
|----------|-------------|---------|
| `BASE_URL` | URL where PodClean is accessible (for RSS feeds) | `http://localhost:8080` |
| `SCHEDULE` | Cron schedule for processing | `0 2 * * *` (2am daily) |
| `TZ` | Timezone | `America/New_York` |

## Usage

1. Open the web UI at `http://<your-ip>:8080`
2. Click **Add Podcast** and enter:
   - Name: Display name for the podcast
   - URL: RSS feed URL or YouTube channel/playlist URL
   - Type: RSS or YouTube
3. Click **Run Now** to process immediately, or wait for the scheduled run
4. Copy the feed URL and add it to your podcast app

### Supported YouTube URL formats

- Channel: `https://www.youtube.com/channel/UC...`
- Channel handle: `https://www.youtube.com/@handle`
- Playlist: `https://www.youtube.com/playlist?list=...`

## How Ad Detection Works

1. **SponsorBlock** (YouTube only): Checks for community-submitted sponsor segments
2. **Whisper transcription**: Transcribes the audio using faster-whisper
3. **Pattern matching**: Scans transcript for common ad phrases:
   - "This episode is brought to you by..."
   - "Use code X for Y% off..."
   - "Thanks to [sponsor] for sponsoring..."
   - And more configurable patterns

4. **Audio processing**: Uses ffmpeg to remove detected ad segments

## Architecture

```
┌─────────────────────────────────────────┐
│  Docker Container                        │
├─────────────────────────────────────────┤
│  FastAPI Web UI (:8080)                 │
│  ├── Add/manage podcasts                │
│  ├── View processing status             │
│  └── Serve RSS feeds & audio files      │
├─────────────────────────────────────────┤
│  Processing Pipeline                     │
│  ├── yt-dlp (download)                  │
│  ├── faster-whisper (transcription)     │
│  ├── Pattern matching (ad detection)    │
│  └── ffmpeg (audio processing)          │
├─────────────────────────────────────────┤
│  APScheduler (cron scheduling)          │
└─────────────────────────────────────────┘
```

## Data Storage

All data is stored in the `./data` directory:

```
data/
├── podclean.db      # SQLite database
├── downloads/       # Temporary download location
├── processed/       # Clean MP3 files (served via RSS)
│   ├── <podcast>/   # Per-podcast directories
│   └── feeds/       # RSS XML files
└── transcripts/     # Whisper transcripts (JSON)
```

## Troubleshooting

**First run is slow**: The Whisper model (~500MB) downloads on first transcription.

**High CPU usage**: Transcription is CPU-intensive. Consider using `base` model instead of `small` for faster processing (edit `app/config.py`).

**Episodes not appearing**: Check the web UI for error messages, or view logs:
```bash
docker compose logs -f
```

## License

MIT
