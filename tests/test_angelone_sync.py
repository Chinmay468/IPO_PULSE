"""
Tests for Angel One SmartAPI sync service, error classification,
diagnose endpoint, and security/privacy guarantees (zero secrets leaked).
"""
import logging
import socket
import pytest
import requests
from httpx import AsyncClient

from app.config import settings
from app.auth import create_access_token
from app.services.angelone_sync_service import (
    classify_error,
    force_ipv4,
    get_env_status,
    diagnose_angelone,
    _fetch_holdings_sync,
    record_sync_failure,
    record_sync_success,
    get_last_sync_status,
    AngelOneSyncError,
)


# ── 1. Error Classification Unit Tests ─────────────────────────────────────────

def test_classify_error_network_timeout():
    # Requests Timeout
    exc = requests.exceptions.Timeout("HTTPSConnectionPool(host='apiconnect.angelone.in'): Read timed out.")
    err_class, msg, code = classify_error(exc=exc, step="connect")
    assert err_class == "network_timeout"
    assert "timed out" in msg.lower()
    assert code == "NETWORK_TIMEOUT"

    # Socket Timeout
    err_class2, msg2, _ = classify_error(exc=socket.timeout("Socket timed out"), step="connect")
    assert err_class2 == "network_timeout"

    # ConnectionError
    exc_conn = requests.exceptions.ConnectionError("Failed to establish a new connection")
    err_class3, _, _ = classify_error(exc=exc_conn, step="connect")
    assert err_class3 == "network_timeout"


def test_classify_error_ip_not_whitelisted():
    # Response dict with errorcode
    resp = {
        "status": False,
        "message": "Client IP 203.0.113.195 is not whitelisted",
        "errorcode": "AB1008",
    }
    err_class, msg, code = classify_error(response_dict=resp, step="holdings")
    assert err_class == "ip_not_whitelisted"
    assert "whitelist" in msg.lower()
    assert code == "AB1008"

    # Message containing restricted IP
    resp2 = {
        "status": False,
        "message": "Access denied: IP address not allowed",
    }
    err_class2, msg2, _ = classify_error(response_dict=resp2, step="login")
    assert err_class2 == "ip_not_whitelisted"


def test_classify_error_invalid_credentials_mpin():
    # Invalid password/PIN response
    resp = {
        "status": False,
        "message": "Invalid password or PIN entered",
        "errorcode": "AB1001",
    }
    err_class, msg, code = classify_error(response_dict=resp, step="login")
    assert err_class == "invalid_credentials_mpin"
    assert "credentials" in msg.lower() or "mpin" in msg.lower()
    assert code == "AB1001"

    # HTTP 401 Unauthorized
    err_class2, _, _ = classify_error(http_status=401, step="login")
    assert err_class2 == "invalid_credentials_mpin"

    # Invalid Client ID
    resp3 = {
        "status": False,
        "message": "Invalid ClientId",
        "errorcode": "AB1004",
    }
    err_class3, _, code3 = classify_error(response_dict=resp3, step="login")
    assert err_class3 == "invalid_credentials_mpin"
    assert code3 == "AB1004"


def test_classify_error_invalid_totp():
    # Invalid TOTP errorcode
    resp = {
        "status": False,
        "message": "TOTP is invalid or expired",
        "errorcode": "AB1050",
    }
    err_class, msg, code = classify_error(response_dict=resp, step="login")
    assert err_class == "invalid_totp"
    assert "totp" in msg.lower()
    assert code == "AB1050"

    # 2FA keyword in message
    resp2 = {
        "status": False,
        "message": "Failed 2FA time based otp verification",
    }
    err_class2, _, _ = classify_error(response_dict=resp2, step="login")
    assert err_class2 == "invalid_totp"


def test_classify_error_rate_limited():
    # HTTP status 429
    err_class, msg, code = classify_error(http_status=429, step="holdings")
    assert err_class == "rate_limited"
    assert "rate limit" in msg.lower()

    # AB1010 code
    resp = {
        "status": False,
        "message": "Access frequency exceeded maximum limit",
        "errorcode": "AB1010",
    }
    err_class2, _, code2 = classify_error(response_dict=resp, step="holdings")
    assert err_class2 == "rate_limited"
    assert code2 == "AB1010"


def test_classify_error_unknown():
    resp = {
        "status": False,
        "message": "Something completely unexpected occurred on broker gateway",
        "errorcode": "EX9999",
    }
    err_class, msg, code = classify_error(response_dict=resp, step="holdings")
    assert err_class == "unknown"
    assert code == "EX9999"


# ── 2. Force IPv4 Context Manager ─────────────────────────────────────────────

def test_force_ipv4():
    import urllib3.util.connection as urllib3_conn
    original_fn = urllib3_conn.allowed_gai_family

    with force_ipv4():
        # Inside context, family must be AF_INET
        assert urllib3_conn.allowed_gai_family() == socket.AF_INET

    # Outside context, original function must be restored
    assert urllib3_conn.allowed_gai_family == original_fn


# ── 3. Diagnostic & State Tracking ───────────────────────────────────────────

def test_record_sync_status_tracking():
    record_sync_failure(step="login", error_class="invalid_totp", error_code="AB1050")
    st = get_last_sync_status()
    assert st["step"] == "login"
    assert st["error_class"] == "invalid_totp"
    assert st["error_code"] == "AB1050"
    assert st["success"] is False
    assert st["timestamp"] is not None

    record_sync_success()
    st_ok = get_last_sync_status()
    assert st_ok["step"] is None
    assert st_ok["error_class"] is None
    assert st_ok["success"] is True


def test_get_env_status_returns_booleans_only(monkeypatch):
    monkeypatch.setattr(settings, "ANGELONE_API_KEY", "secret_key_123")
    monkeypatch.setattr(settings, "ANGELONE_CLIENT_ID", "secret_client_456")
    monkeypatch.setattr(settings, "ANGELONE_PASSWORD", "9999")
    monkeypatch.setattr(settings, "ANGELONE_TOTP_SECRET", None)

    env_st = get_env_status()
    assert env_st["api_key_set"] is True
    assert env_st["client_id_set"] is True
    assert env_st["password_set"] is True
    assert env_st["totp_secret_set"] is False

    # Confirm values are strict bools, NEVER string content
    for k, val in env_st.items():
        assert isinstance(val, bool)
        assert val is True or val is False


@pytest.mark.asyncio
async def test_diagnose_endpoint_unauthenticated(client: AsyncClient):
    """GET /import/angelone/diagnose requires auth."""
    res = await client.get("/api/v1/portfolio/import/angelone/diagnose")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_diagnose_endpoint_non_admin_forbidden(client: AsyncClient, monkeypatch):
    """Non-admin user receives 403 Forbidden."""
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    non_admin_token = create_access_token({"sub": "regular_user"})
    headers = {"Authorization": f"Bearer {non_admin_token}"}

    res = await client.get("/api/v1/portfolio/import/angelone/diagnose", headers=headers)
    assert res.status_code == 403
    assert "admin privileges required" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_diagnose_endpoint_admin_success(auth_client: AsyncClient, monkeypatch):
    """Admin receives 200 with egress IPs, time offset, and env booleans."""
    from unittest.mock import patch

    with patch("app.services.angelone_sync_service.get_egress_ipv4", return_value="198.51.100.42"), \
         patch("app.services.angelone_sync_service.get_egress_ipv6", return_value=None), \
         patch("app.services.angelone_sync_service.get_time_offset", return_value=(0.125, True)):

        res = await auth_client.get("/api/v1/portfolio/import/angelone/diagnose")
        assert res.status_code == 200
        data = res.json()

        assert data["egress_ipv4"] == "198.51.100.42"
        assert data["egress_ipv6"] is None
        assert data["time_offset_seconds"] == 0.125
        assert data["ntp_sync_ok"] is True
        assert "env_vars" in data
        assert isinstance(data["env_vars"]["api_key_set"], bool)
        assert "last_failure" in data


# ── 4. Import Endpoint Error Handling & Mapping ───────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("error_class,error_code,step", [
    ("network_timeout", "NETWORK_TIMEOUT", "connect"),
    ("ip_not_whitelisted", "AB1008", "holdings"),
    ("invalid_credentials_mpin", "AB1001", "login"),
    ("invalid_totp", "AB1050", "login"),
    ("rate_limited", "AB1010", "holdings"),
    ("unknown", "EX9999", "holdings"),
])
async def test_import_endpoint_error_classes_map_to_502(
    auth_client: AsyncClient,
    monkeypatch,
    error_class,
    error_code,
    step
):
    """Confirm every error class returns HTTP 502 with structured diagnostic detail."""
    # Ensure credentials are configured
    monkeypatch.setattr(settings, "ANGELONE_API_KEY", "test_key")
    monkeypatch.setattr(settings, "ANGELONE_CLIENT_ID", "test_client")
    monkeypatch.setattr(settings, "ANGELONE_PASSWORD", "1234")

    from unittest.mock import patch

    mock_error = AngelOneSyncError(
        error_class=error_class,
        user_message=f"Mock error message for {error_class}",
        error_code=error_code,
        step=step,
    )

    with patch("app.services.angelone_sync_service.fetch_angelone_holdings", side_effect=mock_error):
        res = await auth_client.post("/api/v1/portfolio/import/angelone")
        assert res.status_code == 502
        detail = res.json()["detail"]
        assert detail["error_class"] == error_class
        assert detail["error_code"] == error_code
        assert detail["step"] == step
        assert "Mock error message" in detail["message"]


@pytest.mark.asyncio
async def test_import_endpoint_not_configured_returns_400(auth_client: AsyncClient, monkeypatch):
    """When Angel One is not configured in env, returns 400."""
    monkeypatch.setattr(settings, "ANGELONE_API_KEY", None)
    monkeypatch.setattr(settings, "ANGELONE_CLIENT_ID", None)
    monkeypatch.setattr(settings, "ANGELONE_PASSWORD", None)

    res = await auth_client.post("/api/v1/portfolio/import/angelone")
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["error_code"] == "NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_import_endpoint_success(auth_client: AsyncClient, monkeypatch):
    """Successful sync returns 200 with holding counts."""
    monkeypatch.setattr(settings, "ANGELONE_API_KEY", "test_key")
    monkeypatch.setattr(settings, "ANGELONE_CLIENT_ID", "test_client")
    monkeypatch.setattr(settings, "ANGELONE_PASSWORD", "1234")

    from unittest.mock import patch

    mock_holdings = [
        {"symbol": "TCS", "company_name": "Tata Consultancy Services", "exchange": "NSE", "quantity": 10, "avg_buy_price": 3800.0},
        {"symbol": "INFY", "company_name": "Infosys Ltd", "exchange": "NSE", "quantity": 25, "avg_buy_price": 1450.0},
    ]

    with patch("app.services.angelone_sync_service.fetch_angelone_holdings", return_value=mock_holdings):
        res = await auth_client.post("/api/v1/portfolio/import/angelone")
        assert res.status_code == 200
        data = res.json()
        assert data["created"] == 2
        assert data["updated"] == 0
        assert data["skipped"] == 0


# ── 5. Security & Privacy Audit: Zero Secrets Leaked ──────────────────────────

def test_no_secrets_in_logs_or_diagnose(monkeypatch, caplog):
    """
    CRITICAL SECURITY TEST:
    Verifies that credentials, MPIN/passwords, TOTP codes, and TOTP secrets
    NEVER appear in application log records or API responses.
    """
    SECRET_API_KEY = "SECRET_API_KEY_ABCD_9999"
    SECRET_CLIENT_CODE = "SECRET_CLIENT_CODE_XYZ_8888"
    SECRET_MPIN = "9876"
    SECRET_TOTP = "JBSWY3DPEHPK3PXP"  # Standard base32 test key

    monkeypatch.setattr(settings, "ANGELONE_API_KEY", SECRET_API_KEY)
    monkeypatch.setattr(settings, "ANGELONE_CLIENT_ID", SECRET_CLIENT_CODE)
    monkeypatch.setattr(settings, "ANGELONE_PASSWORD", SECRET_MPIN)
    monkeypatch.setattr(settings, "ANGELONE_TOTP_SECRET", SECRET_TOTP)

    from unittest.mock import MagicMock, patch

    # 1. Trigger simulated failures in _fetch_holdings_sync
    with caplog.at_level(logging.DEBUG):
        # Scenario A: Connect failure
        with patch("SmartApi.SmartConnect", side_effect=requests.exceptions.Timeout("Connection timed out")):
            try:
                _fetch_holdings_sync()
            except AngelOneSyncError:
                pass

        # Scenario B: Login failure
        mock_smart = MagicMock()
        mock_smart.generateSession.return_value = {
            "status": False,
            "message": "Invalid password or PIN",
            "errorcode": "AB1001",
        }
        with patch("SmartApi.SmartConnect", return_value=mock_smart):
            try:
                _fetch_holdings_sync()
            except AngelOneSyncError:
                pass

        # Scenario C: Holdings failure (IP not whitelisted)
        mock_smart_ok = MagicMock()
        mock_smart_ok.generateSession.return_value = {
            "status": True,
            "data": {"jwtToken": "mock_jwt_token_sample_123"},
        }
        mock_smart_ok.holding.return_value = {
            "status": False,
            "message": "Client IP is not whitelisted",
            "errorcode": "AB1008",
        }
        with patch("SmartApi.SmartConnect", return_value=mock_smart_ok):
            try:
                _fetch_holdings_sync()
            except AngelOneSyncError:
                pass

    # Audit all captured logs
    captured_logs = caplog.text
    assert SECRET_API_KEY not in captured_logs, "LEAK: API key appeared in log output!"
    assert SECRET_CLIENT_CODE not in captured_logs, "LEAK: Client code appeared in log output!"
    assert SECRET_MPIN not in captured_logs, "LEAK: Password/MPIN appeared in log output!"
    assert SECRET_TOTP not in captured_logs, "LEAK: TOTP secret appeared in log output!"
    assert "mock_jwt_token_sample_123" not in captured_logs, "LEAK: Session JWT token appeared in log output!"

    # 2. Audit diagnose response
    import asyncio
    diag = asyncio.run(diagnose_angelone())
    diag_str = str(diag)
    assert SECRET_API_KEY not in diag_str, "LEAK: API key appeared in diagnose output!"
    assert SECRET_CLIENT_CODE not in diag_str, "LEAK: Client code appeared in diagnose output!"
    assert SECRET_MPIN not in diag_str, "LEAK: Password/MPIN appeared in diagnose output!"
    assert SECRET_TOTP not in diag_str, "LEAK: TOTP secret appeared in diagnose output!"
