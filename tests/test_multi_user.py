import pytest
import io
import pandas as pd
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.portfolio import Holding, Exchange
from app.models.mutual_fund import MFHolding, MFScheme
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
async def test_multi_user_portfolio_isolation(client: AsyncClient, db_session: AsyncSession):
    """
    Ensures User A and User B maintain completely isolated stock portfolios:
    - User A imports/adds stocks -> only User A sees them
    - User B imports/adds different stocks -> only User B sees them
    - No cross-visibility of holdings, summary, or net worth
    """
    # 1. Register User A and User B
    res_a = await client.post("/api/v1/auth/register", json={
        "username": "user_alpha",
        "password": "AlphaPassword123"
    })
    token_a = res_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    res_b = await client.post("/api/v1/auth/register", json={
        "username": "user_beta",
        "password": "BetaPassword123"
    })
    token_b = res_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 2. User A adds RELIANCE
    add_a = await client.post(
        "/api/v1/portfolio/holdings",
        json={"symbol": "RELIANCE", "company_name": "Reliance Industries", "exchange": "NSE", "quantity": 10, "avg_buy_price": 2500.0},
        headers=headers_a
    )
    assert add_a.status_code == 201

    # 3. User B adds TCS
    add_b = await client.post(
        "/api/v1/portfolio/holdings",
        json={"symbol": "TCS", "company_name": "Tata Consultancy Services", "exchange": "NSE", "quantity": 5, "avg_buy_price": 3500.0},
        headers=headers_b
    )
    assert add_b.status_code == 201

    # 4. Check User A's holdings and summary
    summary_a = await client.get("/api/v1/portfolio/summary", headers=headers_a)
    assert summary_a.status_code == 200
    symbols_a = [h["symbol"] for h in summary_a.json()["holdings"]]
    assert "RELIANCE" in symbols_a
    assert "TCS" not in symbols_a
    assert summary_a.json()["holdings_count"] == 1

    # 5. Check User B's holdings and summary
    summary_b = await client.get("/api/v1/portfolio/summary", headers=headers_b)
    assert summary_b.status_code == 200
    symbols_b = [h["symbol"] for h in summary_b.json()["holdings"]]
    assert "TCS" in symbols_b
    assert "RELIANCE" not in symbols_b
    assert summary_b.json()["holdings_count"] == 1


@pytest.mark.asyncio
async def test_multi_user_excel_csv_import_isolation(client: AsyncClient):
    """
    Ensures that when a user imports an Excel/CSV file, the imported holdings
    are scoped strictly to that user's account.
    """
    # 1. Register User C
    res_c = await client.post("/api/v1/auth/register", json={
        "username": "user_charlie",
        "password": "CharliePass123"
    })
    token_c = res_c.json()["access_token"]
    headers_c = {"Authorization": f"Bearer {token_c}"}

    # 2. Register User D
    res_d = await client.post("/api/v1/auth/register", json={
        "username": "user_david",
        "password": "DavidPass123"
    })
    token_d = res_d.json()["access_token"]
    headers_d = {"Authorization": f"Bearer {token_d}"}

    # 3. User C imports CSV file with INFY
    csv_content = "Symbol,Quantity,Average Price,Company Name\nINFY,20,1400.0,Infosys Ltd\n"
    files = {"file": ("zerodha_holdings.csv", csv_content.encode("utf-8"), "text/csv")}
    import_res = await client.post("/api/v1/portfolio/import/csv", files=files, headers=headers_c)
    assert import_res.status_code == 200
    assert import_res.json()["created"] == 1

    # 4. User C should see INFY
    holdings_c = await client.get("/api/v1/portfolio/holdings", headers=headers_c)
    assert holdings_c.status_code == 200
    assert len(holdings_c.json()) == 1
    assert holdings_c.json()[0]["symbol"] == "INFY"

    # 5. User D should have empty holdings
    holdings_d = await client.get("/api/v1/portfolio/holdings", headers=headers_d)
    assert holdings_d.status_code == 200
    assert len(holdings_d.json()) == 0


@pytest.mark.asyncio
async def test_multi_user_mutual_funds_isolation(client: AsyncClient):
    """
    Ensures Mutual Fund holdings and summary are strictly isolated between users.
    """
    # Register User E and F
    res_e = await client.post("/api/v1/auth/register", json={
        "username": "user_eva",
        "password": "EvaPassword123"
    })
    token_e = res_e.json()["access_token"]
    headers_e = {"Authorization": f"Bearer {token_e}"}

    res_f = await client.post("/api/v1/auth/register", json={
        "username": "user_frank",
        "password": "FrankPassword123"
    })
    token_f = res_f.json()["access_token"]
    headers_f = {"Authorization": f"Bearer {token_f}"}

    # User E creates manual MF holding
    res_add_e = await client.post(
        "/api/v1/portfolio/mf/holdings",
        json={
            "scheme_name": "Parag Parikh Flexi Cap Fund",
            "scheme_code": "122639",
            "units": 150.0,
            "avg_nav": 65.5,
            "folio_masked": "1234567/89"
        },
        headers=headers_e
    )
    assert res_add_e.status_code == 200

    # User E summary shows 1 MF
    sum_e = await client.get("/api/v1/portfolio/mf/summary", headers=headers_e)
    assert sum_e.status_code == 200
    assert sum_e.json()["holdings_count"] == 1
    assert sum_e.json()["holdings"][0]["scheme_name"] == "Parag Parikh Flexi Cap Fund"

    # User F summary shows 0 MFs
    sum_f = await client.get("/api/v1/portfolio/mf/summary", headers=headers_f)
    assert sum_f.status_code == 200
    assert sum_f.json()["holdings_count"] == 0
    assert len(sum_f.json()["holdings"]) == 0
