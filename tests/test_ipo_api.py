import pytest
from datetime import date, timedelta
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_get_ipo(auth_client: AsyncClient):
    client = auth_client
    payload = {
        "symbol": "TESTTECH",
        "company_name": "Test Technologies Ltd",
        "ipo_type": "MAINBOARD",
        "status": "LIVE",
        "price_band_low": 100.0,
        "price_band_high": 110.0,
        "issue_price": 110.0,
        "lot_size": 100,
        "issue_size_crores": 500.0,
        "fresh_issue_crores": 400.0,
        "ofs_crores": 100.0,
        "pe_ratio": 20.0,
        "industry_pe": 35.0,
        "ronw": 18.0
    }

    # 1. Create
    res = await client.post("/api/v1/ipos", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["symbol"] == "TESTTECH"
    ipo_id = data["id"]
    assert data["score"] is not None

    # 2. Get by ID
    res_get = await client.get(f"/api/v1/ipos/{ipo_id}")
    assert res_get.status_code == 200
    detail = res_get.json()
    assert detail["company_name"] == "Test Technologies Ltd"

    # 3. Get by Symbol
    res_sym = await client.get("/api/v1/ipos/symbol/TESTTECH")
    assert res_sym.status_code == 200
    assert res_sym.json()["id"] == ipo_id


@pytest.mark.asyncio
async def test_add_subscription_and_gmp(auth_client: AsyncClient):
    client = auth_client
    # Create IPO
    create_res = await client.post("/api/v1/ipos", json={
        "symbol": "ALPHA",
        "company_name": "Alpha Biotech Ltd",
        "ipo_type": "MAINBOARD",
        "status": "LIVE",
        "issue_price": 250.0,
        "issue_size_crores": 800.0,
        "fresh_issue_crores": 600.0,
        "pe_ratio": 22.0,
        "industry_pe": 40.0,
        "ronw": 20.0
    })
    ipo_id = create_res.json()["id"]

    # Add GMP
    gmp_res = await client.post(f"/api/v1/ipos/{ipo_id}/gmp", json={
        "gmp_amount": 100.0,
        "gmp_percentage": 40.0,
        "source": "investorgain"
    })
    assert gmp_res.status_code == 201
    assert gmp_res.json()["gmp_amount"] == 100.0

    # Add Subscription
    sub_res = await client.post(f"/api/v1/ipos/{ipo_id}/subscriptions", json={
        "qib_multiple": 25.0,
        "nii_multiple": 12.0,
        "retail_multiple": 8.0,
        "total_multiple": 18.0,
        "day_number": 2
    })
    assert sub_res.status_code == 201
    assert sub_res.json()["total_multiple"] == 18.0

    # Fetch updated IPO detail with recalculated score
    detail_res = await client.get(f"/api/v1/ipos/{ipo_id}")
    assert detail_res.status_code == 200
    data = detail_res.json()
    assert data["latest_gmp"]["gmp_amount"] == 100.0
    assert data["latest_subscription"]["total_multiple"] == 18.0
    assert data["score"]["composite_score"] >= 70.0


@pytest.mark.asyncio
async def test_list_ipos_with_filters(auth_client: AsyncClient):
    client = auth_client
    today = date.today()
    # Add multiple IPOs with different statuses
    await client.post("/api/v1/ipos", json={
        "symbol": "LIVE_CORP",
        "company_name": "Live Corp India",
        "ipo_type": "MAINBOARD",
        "status": "LIVE",
        "open_date": (today - timedelta(days=1)).isoformat(),
        "close_date": (today + timedelta(days=2)).isoformat(),
    })
    await client.post("/api/v1/ipos", json={
        "symbol": "UPCOMING_SME",
        "company_name": "Upcoming SME Corp",
        "ipo_type": "SME",
        "status": "UPCOMING",
        "open_date": (today + timedelta(days=5)).isoformat(),
        "close_date": (today + timedelta(days=8)).isoformat(),
    })

    # Filter by status
    res = await client.get("/api/v1/ipos?status=LIVE")
    assert res.status_code == 200
    data = res.json()
    for item in data["items"]:
        assert item["status"] == "LIVE"

    # Filter by type
    res_sme = await client.get("/api/v1/ipos?ipo_type=SME")
    assert res_sme.status_code == 200
    for item in res_sme.json()["items"]:
        assert item["ipo_type"] == "SME"

    # Search filter
    res_search = await client.get("/api/v1/ipos?search=Live")
    assert res_search.status_code == 200
    assert any(it["symbol"] == "LIVE_CORP" for it in res_search.json()["items"])


@pytest.mark.asyncio
async def test_angelone_redirect(auth_client: AsyncClient):
    client = auth_client
    today = date.today()
    create_res = await client.post("/api/v1/ipos", json={
        "symbol": "ANGEL_TEST",
        "company_name": "Angel Test Corp",
        "ipo_type": "MAINBOARD",
        "status": "LIVE",
        "open_date": (today - timedelta(days=1)).isoformat(),
        "close_date": (today + timedelta(days=2)).isoformat(),
    })
    ipo_id = create_res.json()["id"]

    # Test ID redirect (follow_redirects=False to catch 307)
    res_redirect = await client.get(f"/api/v1/ipos/{ipo_id}/apply/angelone", follow_redirects=False)
    assert res_redirect.status_code == 307
    assert "angelone.in/ipo-app" in res_redirect.headers["location"]

    # Test Symbol redirect
    res_sym_redirect = await client.get("/api/v1/ipos/symbol/ANGEL_TEST/apply/angelone", follow_redirects=False)
    assert res_sym_redirect.status_code == 307
    assert "angelone.in/ipo-app" in res_sym_redirect.headers["location"]

    # Test that LISTED IPO redirect returns 400 Bad Request
    create_listed = await client.post("/api/v1/ipos", json={
        "symbol": "ALREADY_LISTED",
        "company_name": "Already Listed Corp",
        "ipo_type": "MAINBOARD",
        "status": "LISTED",
        "open_date": (today - timedelta(days=10)).isoformat(),
        "close_date": (today - timedelta(days=7)).isoformat(),
        "listing_date": (today - timedelta(days=2)).isoformat(),
    })
    listed_id = create_listed.json()["id"]
    res_listed = await client.get(f"/api/v1/ipos/{listed_id}/apply/angelone", follow_redirects=False)
    assert res_listed.status_code == 400

