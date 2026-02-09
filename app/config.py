import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Base URL for feed generation (e.g., http://192.168.1.100:8080)
    base_url: str = os.getenv("BASE_URL", "http://localhost:8080")

    # Cron schedule for processing (default: 2am daily)
    schedule: str = os.getenv("SCHEDULE", "0 2 * * *")

    # Data directories
    data_dir: str = "/app/data"
    downloads_dir: str = "/app/data/downloads"
    processed_dir: str = "/app/data/processed"
    transcripts_dir: str = "/app/data/transcripts"

    # Database (4 slashes for absolute path)
    database_url: str = "sqlite+aiosqlite:////app/data/podclean.db"

    # Whisper settings
    whisper_model: str = "small"

    # Retention
    episodes_to_keep: int = 10

    # How many recent episodes to check per podcast when downloading
    download_check_limit: int = 5

    # Default ad patterns (regex, case-insensitive)
    default_ad_patterns: list[str] = [
        r"this (?:episode|podcast) is (?:brought to you|sponsored) by",
        r"thanks to .+ for sponsoring",
        r"use (?:code|promo) .+ (?:for|to get) .+ (?:off|discount)",
        r"go to .+\.com\/[a-z]+",
        r"let me tell you about",
        r"today's sponsor",
        r"this show is supported by",
        r"a]and now a word from our sponsor",
    ]

    class Config:
        env_file = ".env"


settings = Settings()
