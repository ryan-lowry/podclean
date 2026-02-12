from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PodcastType(str, Enum):
    RSS = "rss"
    YOUTUBE = "youtube"


class EpisodeStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    DETECTING_ADS = "detecting_ads"
    PROCESSING_AUDIO = "processing_audio"
    COMPLETED = "completed"
    FAILED = "failed"


class Podcast(Base):
    __tablename__ = "podcasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    url: Mapped[str] = mapped_column(Text)
    podcast_type: Mapped[PodcastType] = mapped_column(SQLEnum(PodcastType))
    enabled: Mapped[bool] = mapped_column(default=True)
    thumbnail_file: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    episodes: Mapped[list["Episode"]] = relationship(back_populates="podcast", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Podcast {self.name}>"


class Settings(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Default settings
    DEFAULTS = {
        "episodes_to_keep": ("10", "Number of episodes to keep per podcast"),
        "download_check_limit": ("5", "Number of recent episodes to check per run"),
    }

    @classmethod
    async def get(cls, db, key: str) -> str:
        """Get a setting value, returning default if not set."""
        from sqlalchemy import select
        result = await db.execute(select(cls).where(cls.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            return setting.value
        return cls.DEFAULTS.get(key, ("", ""))[0]

    @classmethod
    async def get_int(cls, db, key: str) -> int:
        """Get a setting as an integer."""
        value = await cls.get(db, key)
        try:
            return int(value)
        except (ValueError, TypeError):
            return int(cls.DEFAULTS.get(key, ("0", ""))[0])

    @classmethod
    async def set(cls, db, key: str, value: str):
        """Set a setting value."""
        from sqlalchemy import select
        result = await db.execute(select(cls).where(cls.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = value
        else:
            desc = cls.DEFAULTS.get(key, ("", ""))[1]
            db.add(cls(key=key, value=value, description=desc))
        await db.commit()


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    podcast_id: Mapped[int] = mapped_column(ForeignKey("podcasts.id"))

    # Episode metadata
    title: Mapped[str] = mapped_column(String(500))
    original_url: Mapped[str] = mapped_column(Text)
    source_id: Mapped[str] = mapped_column(String(255), index=True)  # YouTube video ID or RSS guid
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Processing state
    status: Mapped[EpisodeStatus] = mapped_column(SQLEnum(EpisodeStatus), default=EpisodeStatus.PENDING)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # File paths (relative to data directories)
    original_file: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    processed_file: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    transcript_file: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Ad detection results
    ads_removed_count: Mapped[int] = mapped_column(Integer, default=0)
    ads_removed_seconds: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    podcast: Mapped["Podcast"] = relationship(back_populates="episodes")

    def __repr__(self) -> str:
        return f"<Episode {self.title[:50]}>"
