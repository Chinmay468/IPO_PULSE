import pytest


@pytest.mark.asyncio
async def test_applications_require_authentication(client):
    res_list = await client.get("/api/v1/applications")
    assert res_list.status_code == 401

    res_create = await client.post("/api/v1/applications", json={"ipo_id": 1})
    assert res_create.status_code == 401


@pytest.mark.asyncio
async def test_application_lifecycle_and_metrics(client, auth_headers):
    # 1. Create an IPO
    ipo_res = await client.post(
        "/api/v1/ipos",
        headers=auth_headers,
        json={
            "symbol": "TESTAPP",
            "company_name": "Test Application Tech Ltd",
            "ipo_type": "MAINBOARD",
            "status": "LIVE",
            "price_band_low": 100.0,
            "price_band_high": 110.0,
            "issue_price": 110.0,
            "lot_size": 100,
            "issue_size_crores": 500.0,
        },
    )
    assert ipo_res.status_code == 201
    ipo_id = ipo_res.json()["id"]

    # Add GMP of +30
    gmp_res = await client.post(
        f"/api/v1/ipos/{ipo_id}/gmp",
        headers=auth_headers,
        json={"gmp_amount": 30.0, "gmp_percentage": 27.27, "source": "Test"},
    )
    assert gmp_res.status_code == 201

    # 2. Log an APPLIED bid (Self, 1 lot = 100 shares @ 110 = 11,000 blocked)
    app1_res = await client.post(
        "/api/v1/applications",
        headers=auth_headers,
        json={
            "ipo_id": ipo_id,
            "applicant_name": "Self",
            "category": "RETAIL",
            "lots_applied": 1,
            "status": "APPLIED",
            "notes": "UPI Mandate Approved",
        },
    )
    assert app1_res.status_code == 201
    app1 = app1_res.json()
    assert app1["shares_applied"] == 100
    assert app1["amount_blocked"] == 11000.0
    assert app1["estimated_profit"] == 3000.0  # 100 shares * 30 GMP

    # 3. Log a second application (Mom) and mark NOT_ALLOTTED
    app2_res = await client.post(
        "/api/v1/applications",
        headers=auth_headers,
        json={
            "ipo_id": ipo_id,
            "applicant_name": "Mom",
            "category": "RETAIL",
            "lots_applied": 1,
            "status": "NOT_ALLOTTED",
        },
    )
    assert app2_res.status_code == 201
    app2_id = app2_res.json()["id"]

    # 4. Update first application to SOLD at ₹155/share
    upd_res = await client.put(
        f"/api/v1/applications/{app1['id']}",
        headers=auth_headers,
        json={
            "status": "SOLD",
            "lots_allotted": 1,
            "selling_price": 155.0,
        },
    )
    assert upd_res.status_code == 200
    upd_data = upd_res.json()
    assert upd_data["status"] == "SOLD"
    assert upd_data["shares_allotted"] == 100
    assert upd_data["realized_profit"] == 4500.0  # (155 - 110) * 100

    # 5. Check summary metrics (1 SOLD, 1 NOT_ALLOTTED -> Hit ratio = 50.0%, Realized profit = ₹4500)
    list_res = await client.get("/api/v1/applications", headers=auth_headers)
    assert list_res.status_code == 200
    summary = list_res.json()["summary"]
    assert summary["total_applications"] == 2
    assert summary["allotted_count"] == 1
    assert summary["not_allotted_count"] == 1
    assert summary["decided_count"] == 2
    assert summary["hit_ratio_pct"] == 50.0
    assert summary["total_realized_profit"] == 4500.0

    # 6. Delete second application
    del_res = await client.delete(f"/api/v1/applications/{app2_id}", headers=auth_headers)
    assert del_res.status_code == 204

    list_after = await client.get("/api/v1/applications", headers=auth_headers)
    assert list_after.json()["summary"]["total_applications"] == 1
    assert list_after.json()["summary"]["hit_ratio_pct"] == 100.0
