import pytest
import pytest_asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.database import Base, get_db
from app.main import app

# In-memory or temporary test SQLite DB
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False
)

TestAsyncSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestAsyncSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    from app.auth import limiter
    try:
        limiter._storage.reset()
    except Exception:
        pass

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(monkeypatch) -> dict:
    import hashlib
    from app.auth import create_access_token
    from app.config import settings

    test_user = "admin"
    test_pass = "admin123"
    test_hash = hashlib.sha256(test_pass.encode("utf-8")).hexdigest()

    monkeypatch.setattr(settings, "ADMIN_USERNAME", test_user)
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", test_hash)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "test-secret-key-1234567890-abcdef-1234567890")

    token = create_access_token({"sub": test_user})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="function")
async def auth_client(client: AsyncClient, auth_headers: dict) -> AsyncClient:
    client.headers.update(auth_headers)
    return client


@pytest.fixture(autouse=True)
def isolate_gemini_env(monkeypatch):
    """Ensure developer's local GEMINI_API_KEY does not cause unintended live calls during tests."""
    from app.config import settings
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("PRIMARY_LLM_PROVIDER", raising=False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "PRIMARY_LLM_PROVIDER", "groq")
    from app.services.groq_client_service import groq_key_pool
    from app.services.gemini_client_service import gemini_key_pool
    groq_key_pool.clear_cooldowns()
    gemini_key_pool.clear_cooldowns()


