from app.routers.ipo import router as ipo_router
from app.routers.allotment import router as allotment_router
from app.routers.scraper import router as scraper_router
from app.routers.auth import router as auth_router
from app.routers.telegram import router as telegram_router
from app.routers.scoring import router as scoring_router

__all__ = [
    "ipo_router",
    "allotment_router",
    "scraper_router",
    "auth_router",
    "telegram_router",
    "scoring_router",
]
