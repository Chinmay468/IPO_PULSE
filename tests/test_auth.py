import hashlib
import secrets
import pytest
from httpx import AsyncClient
from app.config import settings
from app.auth import create_access_token

TEST_ADMIN_AUTH_KEY = f"adm_mock_{secrets.token_hex(8)}"


@pytest.fixture(autouse=True)
def setup_auth_env(monkeypatch):
    """Sets known test admin credentials and JWT secret."""
    test_user = "admin"
    test_hash = hashlib.sha256(TEST_ADMIN_AUTH_KEY.encode("utf-8")).hexdigest()

    monkeypatch.setattr(settings, "ADMIN_USERNAME", test_user)
    monkeypatch.setattr(settings, "ADMIN_PASSWORD_HASH", test_hash)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", f"jwt_secret_{secrets.token_hex(16)}")


@pytest.mark.asyncio
async def test_portfolio_unauthorized_without_token(client: AsyncClient):
    """Protected /portfolio routes must return 401 when accessed without token."""
    res_summary = await client.get("/api/v1/portfolio/summary")
    assert res_summary.status_code == 401
    assert "detail" in res_summary.json()

    res_holdings = await client.get("/api/v1/portfolio/holdings")
    assert res_holdings.status_code == 401


@pytest.mark.asyncio
async def test_portfolio_unauthorized_with_invalid_token(client: AsyncClient):
    """Protected routes must return 401 when accessed with an invalid or tampered token."""
    headers = {"Authorization": "Bearer invalid_gibberish_token_string"}
    res = await client.get("/api/v1/portfolio/summary", headers=headers)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_mutating_ipo_unauthorized_without_token(client: AsyncClient):
    """Mutating IPO routes must return 401 when accessed without token."""
    res = await client.post("/api/v1/ipos", json={"symbol": "UNAUTH_TEST", "company_name": "Test"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_scraper_unauthorized_without_token(client: AsyncClient):
    """Scraper routes must return 401 when accessed without token."""
    res = await client.post("/api/v1/scraper/sync")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_public_routes_accessible_without_token(client: AsyncClient):
    """Public endpoints (GET /ipos, allotment proxy, /, /health) must be accessible without token."""
    res_ipos = await client.get("/api/v1/ipos")
    assert res_ipos.status_code == 200

    res_health = await client.get("/health")
    assert res_health.status_code == 200

    res_root = await client.get("/")
    assert res_root.status_code == 200


@pytest.mark.asyncio
async def test_login_and_access_with_token(client: AsyncClient):
    """Logging in with correct credentials returns a JWT which unlocks protected routes."""
    # 1. Invalid login attempt
    bad_login = await client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "wrongpassword"
    })
    assert bad_login.status_code == 401

    # 2. Valid login attempt
    good_login = await client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": TEST_ADMIN_AUTH_KEY
    })
    assert good_login.status_code == 200
    login_data = good_login.json()
    assert "access_token" in login_data
    assert login_data["token_type"] == "bearer"

    token = login_data["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    # 3. Access protected portfolio route with token -> 200 OK
    res_summary = await client.get("/api/v1/portfolio/summary", headers=auth_headers)
    assert res_summary.status_code == 200

    res_holdings = await client.get("/api/v1/portfolio/holdings", headers=auth_headers)
    assert res_holdings.status_code == 200


@pytest.mark.asyncio
async def test_login_rate_limiting(client: AsyncClient):
    """POST /auth/login is rate limited to 5 requests per minute per IP."""
    # Reset limiter storage if available or make rapid requests
    responses = []
    for _ in range(7):
        r = await client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": TEST_ADMIN_AUTH_KEY
        })
        responses.append(r.status_code)

    # At least one request beyond the 5 limit must receive 429 Too Many Requests
    assert 429 in responses


@pytest.mark.asyncio
async def test_advisory_ask_rate_limiting(client: AsyncClient, monkeypatch):
    """POST /portfolio/advisory/ask is rate limited to 10 requests per minute per IP."""
    token = create_access_token({"sub": "admin"})
    auth_headers = {"Authorization": f"Bearer {token}"}

    async def mock_groq(*args, **kwargs):
        return ("Mocked advisor response.", "ai")
    monkeypatch.setattr("app.services.portfolio_advisor_service.groq_answer_query", mock_groq)

    responses = []
    for _ in range(13):
        r = await client.post(
            "/api/v1/portfolio/advisory/ask",
            headers=auth_headers,
            json={"query": "What is my portfolio health score?"}
        )
        responses.append(r.status_code)

    # Requests beyond 10 must receive 429 Too Many Requests
    assert 429 in responses


@pytest.mark.asyncio
async def test_change_password_flow(client: AsyncClient):
    """Test authenticated password change and login with updated password."""
    uname = f"user_{secrets.token_hex(4)}"
    cred_orig = f"init_{secrets.token_hex(8)}"
    cred_next = f"next_{secrets.token_hex(8)}"

    reg_res = await client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": cred_orig,
        "email": f"{uname}@example.com"
    })
    assert reg_res.status_code == 201
    token = reg_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Attempt with incorrect current password -> 400
    bad_change = await client.post("/api/v1/auth/change-password", headers=headers, json={
        "current_password": "incorrect_temp_key",
        "new_password": cred_next
    })
    assert bad_change.status_code == 400

    # 2. Attempt with same password -> 400
    same_change = await client.post("/api/v1/auth/change-password", headers=headers, json={
        "current_password": cred_orig,
        "new_password": cred_orig
    })
    assert same_change.status_code == 400

    # 3. Successful password change
    good_change = await client.post("/api/v1/auth/change-password", headers=headers, json={
        "current_password": cred_orig,
        "new_password": cred_next
    })
    assert good_change.status_code == 200
    assert "successfully" in good_change.json()["message"]

    # 4. Old password no longer works
    old_login = await client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": cred_orig
    })
    assert old_login.status_code == 401

    # 5. New password works
    new_login = await client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": cred_next
    })
    assert new_login.status_code == 200
    assert "access_token" in new_login.json()


@pytest.mark.asyncio
async def test_forgot_and_reset_password_flow(client: AsyncClient):
    """Test recovery flow: forgot password verification + token-based reset."""
    uname = f"user_{secrets.token_hex(4)}"
    email = f"{uname}@example.com"
    cred_orig = f"orig_{secrets.token_hex(8)}"
    cred_recovery = f"recov_{secrets.token_hex(8)}"

    reg_res = await client.post("/api/v1/auth/register", json={
        "username": uname,
        "password": cred_orig,
        "email": email
    })
    assert reg_res.status_code == 201

    # 1. Non-existent username -> 404
    f_bad_user = await client.post("/api/v1/auth/forgot-password", json={
        "username": "non_existent_user_999",
        "email": email
    })
    assert f_bad_user.status_code == 404

    # 2. Wrong email -> 400
    f_bad_email = await client.post("/api/v1/auth/forgot-password", json={
        "username": uname,
        "email": "wrong_email@example.com"
    })
    assert f_bad_email.status_code == 400

    # 3. Valid identity verification -> 200 with reset token
    f_good = await client.post("/api/v1/auth/forgot-password", json={
        "username": uname,
        "email": email
    })
    assert f_good.status_code == 200
    data = f_good.json()
    assert "reset_token" in data
    reset_token = data["reset_token"]

    # 4. Attempt reset with invalid token -> 400
    bad_reset = await client.post("/api/v1/auth/reset-password-with-token", json={
        "reset_token": "tampered_or_invalid_token",
        "new_password": cred_recovery
    })
    assert bad_reset.status_code == 400

    # 5. Valid reset with token -> 200 with new login token
    good_reset = await client.post("/api/v1/auth/reset-password-with-token", json={
        "reset_token": reset_token,
        "new_password": cred_recovery
    })
    assert good_reset.status_code == 200
    reset_data = good_reset.json()
    assert "access_token" in reset_data

    # 6. Verify login with newly reset password
    fresh_login = await client.post("/api/v1/auth/login", json={
        "username": uname,
        "password": cred_recovery
    })
    assert fresh_login.status_code == 200
    assert "access_token" in fresh_login.json()
