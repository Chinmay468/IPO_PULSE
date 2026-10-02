from app.routers.ipo import router as ipo_router
from app.routers.allotment import router as allotment_router
from app.routers.scraper import router as scraper_router
from app.routers.portfolio import router as portfolio_router
from app.routers.auth import router as auth_router

__all__ = ["ipo_router", "allotment_router", "scraper_router", "portfolio_router", "auth_router"]
