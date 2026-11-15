import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.auth import verify_password, hash_password_secure


@pytest.mark.asyncio
async def test_user_registration_and_encrypted_password(client: AsyncClient, db_session: AsyncSession):
    """
    Test user registration, ensuring password is saved with salted PBKDF2 encryption,
    not plain text, and JWT access token is returned.
    """
    reg_payload = {
        "username": "investor_rohit",
        "password": "SecretPassword@123",
        "email": "rohit@example.com",
        "full_name": "Rohit Sharma"
    }
    res = await client.post("/api/v1/auth/register", json=reg_payload)
    assert res.status_code == 201
    data = res.json()
    assert data["username"] == "investor_rohit"
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user_id"] > 0

    # Verify database record
    user_res = await db_session.execute(select(User).where(User.username == "investor_rohit"))
    user = user_res.scalar_one()
    assert user.email == "rohit@example.com"
    assert user.full_name == "Rohit Sharma"
    assert user.is_superuser is False
    # Ensure password is encrypted with salted PBKDF2-HMAC-SHA256
    assert user.hashed_password.startswith("pbkdf2:sha256:100000$")
    assert "SecretPassword@123" not in user.hashed_password
    # Verify password verification works
    assert verify_password("SecretPassword@123", user.hashed_password) is True
    assert verify_password("WrongPassword!", user.hashed_password) is False


@pytest.mark.asyncio
async def test_registration_duplicate_and_reserved_username(client: AsyncClient):
    """Registration rejects reserved admin name and duplicate username."""
    # 1. Reserved admin name
    res_admin = await client.post("/api/v1/auth/register", json={
        "username": "admin",
        "password": "Password123"
    })
    assert res_admin.status_code == 400
    assert "reserved" in res_admin.json()["detail"].lower()

    # 2. Register user
    res1 = await client.post("/api/v1/auth/register", json={
        "username": "unique_user",
        "password": "Password123"
    })
    assert res1.status_code == 201

    # 3. Duplicate registration attempt
    res2 = await client.post("/api/v1/auth/register", json={
        "username": "unique_user",
        "password": "AnotherPassword123"
    })
    assert res2.status_code == 400
    assert "already registered" in res2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_user_login_flow(client: AsyncClient):
    """Registered user can log in with credentials and receive valid token."""
    await client.post("/api/v1/auth/register", json={
        "username": "trader_priya",
        "password": "SecurePassword456"
    })

    # Wrong password
    bad_login = await client.post("/api/v1/auth/login", json={
        "username": "trader_priya",
        "password": "WrongPassword"
    })
    assert bad_login.status_code == 401

    # Correct password
    login_res = await client.post("/api/v1/auth/login", json={
        "username": "trader_priya",
        "password": "SecurePassword456"
    })
    assert login_res.status_code == 200
    data = login_res.json()
    assert "access_token" in data
    assert data["username"] == "trader_priya"

    # Test /auth/me
    token = data["access_token"]
    me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["username"] == "trader_priya"


@pytest.mark.asyncio
async def test_check_username_availability(client: AsyncClient):
    """Real-time username availability validation."""
    # 1. Available username
    r1 = await client.get("/api/v1/auth/check-username?username=brand_new_user_99")
    assert r1.status_code == 200
    assert r1.json()["available"] is True
    assert "available" in r1.json()["message"].lower()

    # 2. Too short (< 3 chars)
    r2 = await client.get("/api/v1/auth/check-username?username=ab")
    assert r2.status_code == 200
    assert r2.json()["available"] is False
    assert "3 characters" in r2.json()["message"]

    # 3. Invalid characters
    r3 = await client.get("/api/v1/auth/check-username?username=invalid@user!")
    assert r3.status_code == 200
    assert r3.json()["available"] is False

    # 4. Reserved usernames (admin, root, etc.)
    r4 = await client.get("/api/v1/auth/check-username?username=admin")
    assert r4.status_code == 200
    assert r4.json()["available"] is False
    assert "reserved" in r4.json()["message"]

    r4b = await client.get("/api/v1/auth/check-username?username=root")
    assert r4b.status_code == 200
    assert r4b.json()["available"] is False

    # 5. Register user, then verify taken case-insensitively
    reg = await client.post("/api/v1/auth/register", json={
        "username": "taken_user_123",
        "password": "Password123"
    })
    assert reg.status_code == 201

    # Exact match check
    r5 = await client.get("/api/v1/auth/check-username?username=taken_user_123")
    assert r5.status_code == 200
    assert r5.json()["available"] is False
    assert "already taken" in r5.json()["message"].lower()

    # Case-insensitive match check (e.g. Taken_User_123)
    r6 = await client.get("/api/v1/auth/check-username?username=Taken_User_123")
    assert r6.status_code == 200
    assert r6.json()["available"] is False
    assert "already taken" in r6.json()["message"].lower()
