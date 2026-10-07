import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db, AsyncSessionLocal
from app.routers import (
    ipo_router,
    allotment_router,
    scraper_router,
    portfolio_router,
    auth_router,
    telegram_router,
    predictions_router,
    scoring_router,
    mutual_fund_router,
)
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.scraper_service import ScraperService
from app.auth import limiter
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
import app.models.portfolio  # ensure portfolio tables are registered with Base
import app.models.prediction  # ensure prediction tables are registered with Base
import app.models.mutual_fund  # ensure mutual fund tables are registered with Base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup sequence
    logger.info("Initializing database...")
    await init_db()

    # Seed baseline market data if database is fresh
    try:
        async with AsyncSessionLocal() as session:
            count = await ScraperService.seed_market_data(session)
            if count > 0:
                logger.info(f"Seeded {count} IPO records on initial startup.")
    except Exception as exc:
        logger.warning(f"Initial market seeding check: {exc}")

    # Start background scraper scheduler
    start_scheduler()

    yield

    # Shutdown sequence
    logger.info("Shutting down background scheduler...")
    stop_scheduler()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="End-to-end backend service for tracking IPO master data, subscription metrics, Grey Market Premium (GMP), AI-driven Apply/Avoid suggestions, and Link Intime allotment status.",
    lifespan=lifespan
)

# Attach SlowAPI Rate Limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API Routers
app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(ipo_router, prefix=settings.API_V1_PREFIX)
app.include_router(allotment_router, prefix=settings.API_V1_PREFIX)
app.include_router(scraper_router, prefix=settings.API_V1_PREFIX)
app.include_router(portfolio_router, prefix=settings.API_V1_PREFIX)
app.include_router(telegram_router, prefix=settings.API_V1_PREFIX)
app.include_router(predictions_router, prefix=settings.API_V1_PREFIX)
app.include_router(scoring_router, prefix=settings.API_V1_PREFIX)
app.include_router(mutual_fund_router, prefix=settings.API_V1_PREFIX)


from pathlib import Path
from fastapi.responses import HTMLResponse

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
async def dashboard():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>IPO Pulse Service Online</h1><p><a href='/docs'>View API Docs</a></p>")


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "service": settings.APP_NAME
    }
