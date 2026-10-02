from typing import List, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_NAME: str = "IPO Enquiry & Suggester Service"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    
    # Database URL: defaults to asyncpg postgresql, or fallback sqlite for dev/testing
    DATABASE_URL: str = "sqlite+aiosqlite:///./ipo.db"
    
    # Background Scraper Settings
    SCRAPER_ENABLED: bool = True
    SCRAPER_INTERVAL_MINUTES: int = 15
    
    # Registrar Settings
    LINK_INTIME_BASE_URL: str = "https://in.mpms.mufg.com/Initial_Offer/public-issues.html"
    LINK_INTIME_API_URL: str = "https://in.mpms.mufg.com/Initial_Offer/IPO.aspx"
    REQUEST_TIMEOUT_SECONDS: float = 10.0
    
    # CORS
    CORS_ORIGINS: List[str] = [
        "https://ipopulse-app.duckdns.org",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://localhost:5173"
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    # Authentication Settings (Single-User Admin)
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: Optional[str] = None  # Plain text password override (auto-hashed)
    ADMIN_PASSWORD_HASH: Optional[str] = "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9"  # Default: admin123
    JWT_SECRET_KEY: str = "ipo-pulse-secret-jwt-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24 hours

    # ── Angel One SmartAPI (optional — for portfolio sync) ───────────────────
    # Get your API key from https://smartapi.angelbroking.com
    ANGELONE_API_KEY: Optional[str] = None
    ANGELONE_CLIENT_ID: Optional[str] = None   # Your Angel One login ID (e.g. A123456)
    ANGELONE_PASSWORD: Optional[str] = None    # Your Angel One MPIN (4-digit)
    ANGELONE_TOTP_SECRET: Optional[str] = None # Base32 TOTP secret from 2FA setup
    ANGELONE_PAN: Optional[str] = None         # PAN number for decrypting Excel statement exports

    # ── Telegram Bot Notifications ──────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    TELEGRAM_NOTIFICATIONS_ENABLED: bool = True
    TELEGRAM_MIN_SCORE: float = 65.0
    TELEGRAM_MIN_GMP_PCT: float = 20.0
    TELEGRAM_MAINBOARD_ONLY: bool = True
    TELEGRAM_WEBHOOK_URL: Optional[str] = "https://ipopulse-app.duckdns.org/api/v1/telegram/webhook"


settings = Settings()

