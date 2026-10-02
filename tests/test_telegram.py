import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch
from httpx import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.ipo import IPO, IPOScore, IPOGmp, IPOSubscription, IPOStatus, IPOType, RecommendationType
from app.services.telegram_service import TelegramService, _ALERT_CACHE, _RATE_LIMIT_CACHE


@pytest.fixture(autouse=True)
def clear_caches():
    _ALERT_CACHE.clear()
    _RATE_LIMIT_CACHE.clear()
    yield
    _ALERT_CACHE.clear()
    _RATE_LIMIT_CACHE.clear()


def test_telegram_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", None)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", None)
    assert TelegramService.is_configured() is False

    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "mock_token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", True)
    assert TelegramService.is_configured() is True

    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", False)
    assert TelegramService.is_configured() is False


def test_format_ipo_alert():
    ipo = IPO(
        company_name="Premier Energies Ltd & Co <Tech>",
        symbol="PREMIERENE",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        price_band_low=427.0,
        price_band_high=450.0,
        open_date=date(2026, 10, 5),
        close_date=date(2026, 10, 7),
        listing_date=date(2026, 10, 12),
    )
    score = IPOScore(
        composite_score=84.5,
        recommendation=RecommendationType.STRONG_APPLY,
        rationale={"positive_factors": ["Strong revenue growth > 40%", "Exceptional anchor book response"]}
    )
    gmp = IPOGmp(
        gmp_amount=195.0,
        gmp_percentage=43.3
    )
    sub = IPOSubscription(
        total_multiple=18.4
    )

    alert_text = TelegramService.format_ipo_alert(ipo, score, gmp, sub)

    assert "Premier Energies Ltd &amp; Co &lt;Tech&gt;" in alert_text
    assert "STRONG APPLY" in alert_text
    assert "84.5 / 100" in alert_text
    assert "+₹195.00" in alert_text
    assert "(+43.3%)" in alert_text
    assert "18.40x" in alert_text
    assert "05 Oct 2026" in alert_text
    assert "Strong revenue growth &gt; 40%" in alert_text


@pytest.mark.asyncio
async def test_send_message_success(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "test_bot_token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "987654321")
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", True)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Response(200, json={"ok": True, "result": {"message_id": 101}})
        success, err = await TelegramService.send_message("<b>Hello World</b>")
        assert success is True
        assert err is None
        mock_post.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_message_api_failure(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "bad_token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "987654321")
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", True)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = Response(401, json={"ok": False, "description": "Unauthorized: invalid bot token"})
        success, err = await TelegramService.send_message("Test message")
        assert success is False
        assert "Unauthorized" in err


@pytest.mark.asyncio
async def test_send_test_message(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "mock_token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", True)

    with patch.object(TelegramService, "send_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = (True, None)
        res = await TelegramService.send_test_message()
        assert res["success"] is True
        assert "Test notification delivered successfully" in res["message"]


@pytest.mark.asyncio
async def test_send_best_ipo_alerts_deduplication(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_MIN_SCORE", 65.0)
    monkeypatch.setattr(settings, "TELEGRAM_MIN_GMP_PCT", 20.0)

    # 1. Create a top-pick IPO
    top_ipo = IPO(
        company_name="Premier Energies Ltd",
        symbol="PREMIERENE",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        open_date=date.today(),
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(top_ipo)
    await db_session.flush()

    top_score = IPOScore(
        ipo_id=top_ipo.id,
        composite_score=82.0,
        recommendation=RecommendationType.STRONG_APPLY,
        calculated_at=datetime.now(timezone.utc)
    )
    top_gmp = IPOGmp(
        ipo_id=top_ipo.id,
        gmp_amount=75.0,
        gmp_percentage=45.0,
        recorded_at=datetime.now(timezone.utc)
    )
    db_session.add_all([top_score, top_gmp])

    # 2. Create an AVOID IPO (should be skipped)
    avoid_ipo = IPO(
        company_name="Laggard Ltd",
        symbol="LAGGARD",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(avoid_ipo)
    await db_session.flush()

    avoid_score = IPOScore(
        ipo_id=avoid_ipo.id,
        composite_score=35.0,
        recommendation=RecommendationType.AVOID,
        calculated_at=datetime.now(timezone.utc)
    )
    db_session.add(avoid_score)
    await db_session.commit()

    with patch.object(TelegramService, "send_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = (True, None)

        # First run: should alert the top IPO once
        result1 = await TelegramService.send_best_ipo_alerts(db_session)
        assert result1["sent"] == 1
        assert result1["skipped"] == 1  # Laggard Ltd skipped
        mock_send.assert_awaited_once()

        # Second run immediately without changes: should skip both due to deduplication
        mock_send.reset_mock()
        result2 = await TelegramService.send_best_ipo_alerts(db_session)
        assert result2["sent"] == 0
        assert result2["skipped"] == 2
        mock_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_best_ipo_alerts_filters_out_sme(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_MIN_SCORE", 65.0)
    monkeypatch.setattr(settings, "TELEGRAM_MIN_GMP_PCT", 20.0)
    monkeypatch.setattr(settings, "TELEGRAM_MAINBOARD_ONLY", True)

    sme_ipo = IPO(
        company_name="Solarium Green SME",
        symbol="SOLARIUM_SME",
        ipo_type=IPOType.SME,
        status=IPOStatus.LIVE,
        open_date=date.today(),
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(sme_ipo)
    await db_session.flush()

    sme_score = IPOScore(
        ipo_id=sme_ipo.id,
        composite_score=85.0,
        recommendation=RecommendationType.STRONG_APPLY,
        calculated_at=datetime.now(timezone.utc)
    )
    sme_gmp = IPOGmp(
        ipo_id=sme_ipo.id,
        gmp_amount=90.0,
        gmp_percentage=50.0,
        recorded_at=datetime.now(timezone.utc)
    )
    db_session.add_all([sme_score, sme_gmp])
    await db_session.commit()

    with patch.object(TelegramService, "send_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = (True, None)

        # With TELEGRAM_MAINBOARD_ONLY=True: SME must be completely excluded
        res = await TelegramService.send_best_ipo_alerts(db_session)
        assert res["sent"] == 0
        mock_send.assert_not_awaited()

        # With TELEGRAM_MAINBOARD_ONLY=False: SME is alerted
        monkeypatch.setattr(settings, "TELEGRAM_MAINBOARD_ONLY", False)
        res_all = await TelegramService.send_best_ipo_alerts(db_session)
        assert res_all["sent"] == 1
        mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_top_picks_digest_mainboard_only(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_MIN_SCORE", 65.0)
    monkeypatch.setattr(settings, "TELEGRAM_MAINBOARD_ONLY", True)

    main_ipo = IPO(
        company_name="Bajaj Housing Finance",
        symbol="BAJAJHFL",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,
        created_at=datetime.now(timezone.utc)
    )
    sme_ipo = IPO(
        company_name="Awesome SME Ltd",
        symbol="AWESOMESME",
        ipo_type=IPOType.SME,
        status=IPOStatus.LIVE,
        created_at=datetime.now(timezone.utc)
    )
    db_session.add_all([main_ipo, sme_ipo])
    await db_session.flush()

    m_score = IPOScore(ipo_id=main_ipo.id, composite_score=88.0, recommendation=RecommendationType.STRONG_APPLY)
    s_score = IPOScore(ipo_id=sme_ipo.id, composite_score=92.0, recommendation=RecommendationType.STRONG_APPLY)
    db_session.add_all([m_score, s_score])
    await db_session.commit()

    with patch.object(TelegramService, "send_message", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = (True, None)

        res = await TelegramService.send_top_picks_digest(db_session)
        assert res["success"] is True
        assert res["picks_count"] == 1
        mock_send.assert_awaited_once()
        msg_text = mock_send.call_args[0][0]
        assert "Bajaj Housing Finance" in msg_text
        assert "Awesome SME Ltd" not in msg_text
        assert "MAINBOARD" in msg_text


def test_format_ipo_lookup_card_sme_notice(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_MAINBOARD_ONLY", True)

    sme_ipo = IPO(
        company_name="KRN Heat Exchanger SME",
        symbol="KRN",
        ipo_type=IPOType.SME,
        status=IPOStatus.LIVE
    )
    card_sme = TelegramService.format_ipo_lookup_card(sme_ipo)
    assert "SME Notice" in card_sme
    assert "₹1,00,000+" in card_sme

    main_ipo = IPO(
        company_name="Tata Technologies",
        symbol="TATATECH",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE
    )
    card_main = TelegramService.format_ipo_lookup_card(main_ipo)
    assert "SME Notice" not in card_main


@pytest.mark.asyncio
async def test_telegram_api_endpoints(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "mock_bot_token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", True)

    # 1. Status endpoint
    status_resp = await client.get("/api/v1/telegram/status", headers=auth_headers)
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["configured"] is True
    assert status_data["chat_id_configured"] is True
    assert status_data["mainboard_only"] is True
    assert "mock_bot_token" not in status_resp.text  # NEVER leak token

    # 2. Test notification endpoint
    with patch.object(TelegramService, "send_test_message", new_callable=AsyncMock) as mock_test:
        mock_test.return_value = {"success": True, "message": "Delivered successfully"}
        test_resp = await client.post("/api/v1/telegram/test", headers=auth_headers)
        assert test_resp.status_code == 200
        assert test_resp.json()["success"] is True

    # 3. Digest endpoint
    with patch.object(TelegramService, "send_top_picks_digest", new_callable=AsyncMock) as mock_digest:
        mock_digest.return_value = {"success": True, "picks_count": 2}
        digest_resp = await client.post("/api/v1/telegram/digest", headers=auth_headers)
        assert digest_resp.status_code == 200
        assert digest_resp.json()["picks_count"] == 2


def test_markdown_to_telegram_html():
    from app.services.telegram_service import markdown_to_telegram_html
    md = "**Strong Buy** and *caution* on `TATAMOTORS`.\n# Heading\n- Item 1\n- Item 2"
    res = markdown_to_telegram_html(md)
    assert "<b>Strong Buy</b>" in res
    assert "<i>caution</i>" in res
    assert "<code>TATAMOTORS</code>" in res
    assert "<b>Heading</b>" in res
    assert "• Item 1" in res


@pytest.mark.asyncio
async def test_webhook_unauthorized_user(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "mock_bot_token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", True)

    with patch.object(TelegramService, "send_message", new_callable=AsyncMock) as mock_send, \
         patch.object(TelegramService, "send_chat_action", new_callable=AsyncMock):
        mock_send.return_value = (True, None)

        # Message from stranger chat_id 999999
        payload = {
            "update_id": 100,
            "message": {
                "message_id": 1,
                "chat": {"id": 999999},
                "text": "Hello"
            }
        }
        resp = await client.post("/api/v1/telegram/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "ignored_unauthorized"
        # Bot ignores unauthorized users completely without sending any message back
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_rate_limiting(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "mock_bot_token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", True)

    with patch.object(TelegramService, "send_message", new_callable=AsyncMock) as mock_send, \
         patch.object(TelegramService, "send_chat_action", new_callable=AsyncMock):
        mock_send.return_value = (True, None)

        # Simulate 20 requests rapidly
        for i in range(20):
            payload = {
                "update_id": 200 + i,
                "message": {
                    "message_id": 10 + i,
                    "chat": {"id": 123456789},
                    "text": "/help"
                }
            }
            resp = await client.post("/api/v1/telegram/webhook", json=payload)
            assert resp.status_code == 200
            assert resp.json()["action"] == "help"

        # 21st request exceeds rate limit
        payload = {
            "update_id": 221,
            "message": {
                "message_id": 31,
                "chat": {"id": 123456789},
                "text": "/help"
            }
        }
        resp = await client.post("/api/v1/telegram/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "rate_limited"
        # Verify rate limit warning was sent
        sent_warning = mock_send.call_args[0][0]
        assert "Rate Limit Exceeded" in sent_warning


@pytest.mark.asyncio
async def test_webhook_start_command(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "mock_bot_token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", True)

    with patch.object(TelegramService, "send_message", new_callable=AsyncMock) as mock_send, \
         patch.object(TelegramService, "send_chat_action", new_callable=AsyncMock):
        mock_send.return_value = (True, None)

        payload = {
            "update_id": 101,
            "message": {
                "message_id": 2,
                "chat": {"id": 123456789},
                "text": "/start"
            }
        }
        resp = await client.post("/api/v1/telegram/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "help"
        mock_send.assert_called_once()
        assert "Welcome to IPO Pulse AI Bot" in mock_send.call_args[0][0]


@pytest.mark.asyncio
async def test_webhook_shares_command(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "mock_bot_token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", True)

    with patch.object(TelegramService, "send_message", new_callable=AsyncMock) as mock_send, \
         patch.object(TelegramService, "send_chat_action", new_callable=AsyncMock):
        mock_send.return_value = (True, None)

        payload = {
            "update_id": 102,
            "message": {
                "message_id": 3,
                "chat": {"id": 123456789},
                "text": "/shares"
            }
        }
        resp = await client.post("/api/v1/telegram/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "shares_suggested"
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][0]
        assert "CURATED SWING PICKS" in sent_text
        assert "HDFCBANK" in sent_text
        assert "NTPC" in sent_text
        assert "Target" in sent_text
        assert "Stop-Loss" in sent_text


@pytest.mark.asyncio
async def test_webhook_suggest_me_a_share_text(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "mock_bot_token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.setattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", True)

    with patch.object(TelegramService, "send_message", new_callable=AsyncMock) as mock_send, \
         patch.object(TelegramService, "send_chat_action", new_callable=AsyncMock):
        mock_send.return_value = (True, None)

        payload = {
            "update_id": 103,
            "message": {
                "message_id": 4,
                "chat": {"id": 123456789},
                "text": "suggest me a share to buy for 2-3 months"
            }
        }
        resp = await client.post("/api/v1/telegram/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "shares_suggested"
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][0]
        assert "CURATED SWING PICKS" in sent_text


def test_answer_portfolio_query_suggests_market_share():
    from app.services.portfolio_advisor_service import answer_portfolio_query
    res = answer_portfolio_query("suggest me a share in the market to buy", {"holdings": []})
    assert "High-Conviction Market Picks" in res
    assert "HDFC Bank (HDFCBANK)" in res
    assert "NTPC" in res
    assert "Stop-Loss" in res


