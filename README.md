# PodClean

A self-hosted podcast processor that automatically downloads podcasts from RSS feeds or YouTube, removes ads/sponsors using AI, and serves clean episodes via RSS for your podcast app.

## Features

- **Multi-source support**: Download from RSS feeds or YouTube channels/playlists
- **AI-powered ad detection**: Uses local LLM (Ollama) to intelligently identify ad segments
- **SponsorBlock integration**: For YouTube videos, checks SponsorBlock first for community-submitted ad segments
- **Whisper transcription**: Transcribes audio for ad detection using faster-whisper
- **Web UI**: Simple interface to manage podcasts, view processing status, and configure settings
- **RSS feed generation**: Each podcast gets its own RSS feed compatible with podcast apps like Pocket Casts
- **Scheduled processing**: Runs automatically on a cron schedule (default: 2am daily)
- **Retention management**: Automatically keeps only the last N episodes per podcast (configurable via UI)

## Requirements

- Docker and Docker Compose
- ~8GB RAM (4GB for Whisper + 4GB for Ollama LLM)
- Storage for downloaded/processed episodes
- CPU with good single-thread performance (LLM runs on CPU)

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

3. Pull the LLM model (one-time, ~2GB download):
   ```bash
   docker exec ollama ollama pull llama3.2:3b
   ```

### Manual Docker Setup

```bash
git clone https://github.com/ryan-lowry/podclean.git
cd podclean
cp .env.example .env
# Edit .env with your settings
docker compose up -d --build

# Pull the LLM model
docker exec ollama ollama pull llama3.2:3b
```

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Description | Default |
|----------|-------------|---------|
| `BASE_URL` | URL where PodClean is accessible (for RSS feeds) | `http://localhost:8080` |
| `SCHEDULE` | Cron schedule for processing | `0 2 * * *` (2am daily) |
| `TZ` | Timezone | `America/New_York` |
| `OLLAMA_URL` | Ollama service URL | `http://ollama:11434` |
| `OLLAMA_MODEL` | LLM model for ad detection | `llama3.2:3b` |
| `USE_LLM_DETECTION` | Enable LLM-based ad detection | `true` |

### Recommended Ollama Models

| Model | Size | Speed | Accuracy | Best For |
|-------|------|-------|----------|----------|
| `llama3.2:1b` | ~1.3GB | Fastest | Good | Low-power CPUs |
| `llama3.2:3b` | ~2GB | Fast | Better | **Recommended for most setups** |
| `mistral:7b` | ~4GB | Slower | Best | High-end CPUs with 16GB+ RAM |

## Usage

1. Open the web UI at `http://<your-ip>:8080`
2. Click **Add Podcast** and enter:
   - Name: Display name for the podcast
   - URL: RSS feed URL or YouTube channel/playlist URL
   - Type: RSS or YouTube
3. Click **Run Now** to process immediately, or wait for the scheduled run
4. Copy the feed URL and add it to your podcast app

### Settings

Click **Settings** in the web UI to configure:
- **Episodes to keep**: Number of episodes to retain per podcast
- **Download check limit**: Number of recent episodes to check per run

### Supported YouTube URL formats

- Channel: `https://www.youtube.com/channel/UC...`
- Channel handle: `https://www.youtube.com/@handle`
- Playlist: `https://www.youtube.com/playlist?list=...`

## How Ad Detection Works

PodClean uses a multi-layered approach to detect ads:

1. **SponsorBlock** (YouTube only): Checks for community-submitted sponsor segments first
2. **Whisper transcription**: Transcribes the audio using faster-whisper (runs locally)
3. **LLM analysis**: Sends transcript to Ollama LLM which intelligently identifies:
   - Sponsor mentions and product pitches
   - Ad transition phrases ("quick break", "word from our sponsor")
   - Return phrases ("back to the show", "anyway")
   - Complete ad segment boundaries (start and end times)
4. **Pattern matching** (fallback): If LLM is unavailable, uses regex patterns
5. **Audio processing**: Uses ffmpeg to remove detected ad segments

### Why LLM-based detection?

Pattern matching only finds trigger phrases but misses full ad boundaries. The LLM understands context and can identify where an ad starts and ends, even without explicit trigger phrases.

## Architecture

```
┌─────────────────────────────────────────┐
│  Docker Compose                          │
├─────────────────────────────────────────┤
│  podclean (FastAPI)                      │
│  ├── Web UI (:8080)                     │
│  ├── Add/manage podcasts                │
│  ├── View logs & settings               │
│  └── Serve RSS feeds & audio files      │
├─────────────────────────────────────────┤
│  Processing Pipeline                     │
│  ├── yt-dlp (download)                  │
│  ├── faster-whisper (transcription)     │
│  ├── Ollama LLM (ad detection)          │
│  └── ffmpeg (audio processing)          │
├─────────────────────────────────────────┤
│  ollama                                  │
│  └── Local LLM inference (llama3.2:3b)  │
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

Ollama models are stored in a Docker volume (`ollama_data`).

## Troubleshooting

**First run is slow**: Both the Whisper model (~500MB) and LLM model (~2GB) download on first use.

**LLM detection not working**: Ensure the model is pulled:
```bash
docker exec ollama ollama pull llama3.2:3b
docker exec ollama ollama list  # Verify model is available
```

**High memory usage**: The LLM requires ~4GB RAM. If memory is tight:
- Use a smaller model: `OLLAMA_MODEL=llama3.2:1b`
- Or disable LLM detection: `USE_LLM_DETECTION=false`

**High CPU usage**: Both transcription and LLM inference are CPU-intensive. Consider using `base` Whisper model for faster processing (edit `app/config.py`).

**Episodes not appearing**: Check the web UI logs page, or view Docker logs:
```bash
docker compose logs -f podclean
```

**Ads not being removed**: Check the logs for "LLM detected X ad segments". If 0 segments detected:
- The LLM may not have recognized the ad format
- Try a larger model like `mistral:7b`
- Check transcript in `data/transcripts/` to verify ad phrases exist

## License

MIT
