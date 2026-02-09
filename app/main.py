import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import init_db, get_db, async_session
from app.models import Podcast, Episode, PodcastType, EpisodeStatus
from app.pipeline import run_pipeline
from app.feed_generator import generate_index_page

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Scheduler
scheduler = AsyncIOScheduler()


async def scheduled_pipeline_run():
    """Run the pipeline on schedule."""
    logger.info("Scheduled pipeline run starting")
    async with async_session() as db:
        await run_pipeline(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    await init_db()
    logger.info("Database initialized")

    # Parse cron schedule
    cron_parts = settings.schedule.split()
    if len(cron_parts) == 5:
        trigger = CronTrigger(
            minute=cron_parts[0],
            hour=cron_parts[1],
            day=cron_parts[2],
            month=cron_parts[3],
            day_of_week=cron_parts[4],
        )
        scheduler.add_job(scheduled_pipeline_run, trigger, id="pipeline")
        scheduler.start()
        logger.info(f"Scheduler started with schedule: {settings.schedule}")

    yield

    # Shutdown
    scheduler.shutdown()


app = FastAPI(title="PodClean", lifespan=lifespan)

# Templates
templates = Jinja2Templates(directory="templates")

# Static files (if any)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# --- Web UI Routes ---


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    """Main dashboard."""
    # Get all podcasts with episode counts
    result = await db.execute(select(Podcast).order_by(Podcast.name))
    podcasts = list(result.scalars().all())

    podcast_data = []
    for podcast in podcasts:
        # Get episode stats
        episodes_result = await db.execute(
            select(Episode).where(Episode.podcast_id == podcast.id)
        )
        episodes = list(episodes_result.scalars().all())

        completed = sum(1 for e in episodes if e.status == EpisodeStatus.COMPLETED)
        processing = sum(
            1 for e in episodes if e.status not in [EpisodeStatus.COMPLETED, EpisodeStatus.FAILED]
        )
        failed = sum(1 for e in episodes if e.status == EpisodeStatus.FAILED)

        podcast_data.append({
            "podcast": podcast,
            "completed": completed,
            "processing": processing,
            "failed": failed,
            "feed_url": f"{settings.base_url}/feeds/{podcast.slug}.xml",
        })

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "podcasts": podcast_data,
            "base_url": settings.base_url,
        },
    )


@app.get("/add", response_class=HTMLResponse)
async def add_podcast_form(request: Request):
    """Show add podcast form."""
    return templates.TemplateResponse("add.html", {"request": request})


@app.post("/add")
async def add_podcast(
    name: str = Form(...),
    url: str = Form(...),
    podcast_type: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Add a new podcast."""
    slug = slugify(name)

    # Check for duplicate
    existing = await db.execute(select(Podcast).where(Podcast.slug == slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Podcast with this name already exists")

    podcast = Podcast(
        name=name,
        slug=slug,
        url=url,
        podcast_type=PodcastType(podcast_type),
        enabled=True,
    )
    db.add(podcast)
    await db.commit()

    logger.info(f"Added podcast: {name}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/podcast/{podcast_id}/delete")
async def delete_podcast(podcast_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a podcast and all its episodes."""
    result = await db.execute(select(Podcast).where(Podcast.id == podcast_id))
    podcast = result.scalar_one_or_none()

    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")

    await db.delete(podcast)
    await db.commit()

    logger.info(f"Deleted podcast: {podcast.name}")
    return RedirectResponse(url="/", status_code=303)


@app.post("/podcast/{podcast_id}/toggle")
async def toggle_podcast(podcast_id: int, db: AsyncSession = Depends(get_db)):
    """Enable/disable a podcast."""
    result = await db.execute(select(Podcast).where(Podcast.id == podcast_id))
    podcast = result.scalar_one_or_none()

    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")

    podcast.enabled = not podcast.enabled
    await db.commit()

    return RedirectResponse(url="/", status_code=303)


@app.get("/podcast/{podcast_id}", response_class=HTMLResponse)
async def podcast_detail(
    request: Request,
    podcast_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Show podcast details and episodes."""
    result = await db.execute(select(Podcast).where(Podcast.id == podcast_id))
    podcast = result.scalar_one_or_none()

    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")

    episodes_result = await db.execute(
        select(Episode)
        .where(Episode.podcast_id == podcast_id)
        .order_by(Episode.published_at.desc().nullslast(), Episode.created_at.desc())
    )
    episodes = list(episodes_result.scalars().all())

    return templates.TemplateResponse(
        "podcast.html",
        {
            "request": request,
            "podcast": podcast,
            "episodes": episodes,
            "feed_url": f"{settings.base_url}/feeds/{podcast.slug}.xml",
            "base_url": settings.base_url,
        },
    )


@app.post("/run")
async def trigger_run(db: AsyncSession = Depends(get_db)):
    """Manually trigger a pipeline run."""
    logger.info("Manual pipeline run triggered")
    stats = await run_pipeline(db)
    return RedirectResponse(url="/", status_code=303)


# --- Feed & Episode Routes ---


@app.get("/feeds/{slug}.xml")
async def get_feed(slug: str):
    """Serve a podcast RSS feed."""
    feed_path = os.path.join(settings.processed_dir, "feeds", f"{slug}.xml")

    if not os.path.exists(feed_path):
        raise HTTPException(status_code=404, detail="Feed not found")

    return FileResponse(feed_path, media_type="application/rss+xml")


@app.get("/episodes/{podcast_slug}/{filename}")
async def get_episode(podcast_slug: str, filename: str):
    """Serve an episode audio file."""
    file_path = os.path.join(settings.processed_dir, podcast_slug, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Episode not found")

    return FileResponse(file_path, media_type="audio/mpeg")


# --- Health Check ---


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}
