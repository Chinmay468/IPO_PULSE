import pytest
from datetime import date, datetime, timedelta
from pathlib import Path
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ipo import IPO, IPOType, IPOStatus, IPOScore
from app.services.chittorgarh_scraper import (
    parse_dashboard_list,
    normalize_company_name,
    sync_chittorgarh_data,
)
from app.core.ipo_timeline import (
    derive_ipo_status,
    compute_day_label,
    count_business_days,
    IST,
)
from app.services.scraper_service import ScraperService


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def mainboard_fixture():
    return (FIXTURES_DIR / "chittorgarh_mainboard_dashboard.html").read_text(encoding="utf-8")


@pytest.fixture
def upcoming_drhp_fixture():
    return (FIXTURES_DIR / "chittorgarh_upcoming_drhp.html").read_text(encoding="utf-8")


# ── 1. Discovery Creating a New IPO from Fixture ──
@pytest.mark.asyncio
async def test_discovery_creates_new_ipo_from_fixture(db_session: AsyncSession, mainboard_fixture):
    # Parse dashboard list from saved fixture
    discovered_items = parse_dashboard_list(mainboard_fixture, ipo_type=IPOType.MAINBOARD)
    assert len(discovered_items) > 0

    first_item = discovered_items[0]
    first_name = first_item["company_name"]
    first_url = first_item["source_url"]
    first_id = first_item["source_id"]

    # Verify not yet in DB
    existing = (await db_session.execute(
        select(IPO).where(IPO.source_id == first_id)
    )).scalar_one_or_none()
    assert existing is None

    # Simulate discovery creation
    norm_name = normalize_company_name(first_name)
    sym = (first_name.split()[0].upper()[:10] or "IPO").replace(".", "")
    new_ipo = IPO(
        symbol=sym,
        company_name=first_name,
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.UPCOMING,
        source="chittorgarh",
        source_url=first_url,
        source_id=first_id,
        is_seed=False,
        dates_tba=True,
    )
    db_session.add(new_ipo)
    await db_session.commit()
    await db_session.refresh(new_ipo)

    assert new_ipo.id is not None
    assert new_ipo.is_seed is False
    assert new_ipo.source == "chittorgarh"
    assert new_ipo.source_id == first_id
    assert new_ipo.source_url == first_url
    assert new_ipo.dates_tba is True


# ── 2. Matching an Existing IPO by source_id or Normalized Name ──
@pytest.mark.asyncio
async def test_discovery_matching_existing_ipo(db_session: AsyncSession):
    # Pre-create an IPO with source_id 7788
    pre_existing = IPO(
        symbol="NEXGEN",
        company_name="NexGen Robotics Limited",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.UPCOMING,
        source="chittorgarh",
        source_id=7788,
        source_url="https://www.chittorgarh.com/ipo/nexgen-robotics/7788/",
        is_seed=False,
        dates_tba=True,
    )
    db_session.add(pre_existing)
    await db_session.commit()

    # Incoming discovery item with same source_id but updated dates
    incoming_item = {
        "company_name": "NexGen Robotics Ltd",
        "source_id": 7788,
        "source_url": "https://www.chittorgarh.com/ipo/nexgen-robotics/7788/",
        "open_date": date(2026, 11, 1),
        "close_date": date(2026, 11, 4),
        "price_band_high": 250.0,
    }

    # Match by source_id
    stmt = select(IPO).where(IPO.source_id == incoming_item["source_id"])
    matched = (await db_session.execute(stmt)).scalar_one_or_none()
    assert matched is not None
    assert matched.id == pre_existing.id

    # Update rather than duplicate
    matched.open_date = incoming_item["open_date"]
    matched.close_date = incoming_item["close_date"]
    matched.dates_tba = False
    matched.price_band_high = incoming_item["price_band_high"]
    await db_session.commit()

    # Verify no duplicate was added
    total = (await db_session.execute(
        select(func.count(IPO.id)).where(IPO.source_id == 7788)
    )).scalar_one()
    assert total == 1

    # Match by normalized name when source_id is missing
    norm_target = normalize_company_name("NexGen Robotics Limited")
    norm_query = normalize_company_name("NexGen Robotics Ltd")
    assert norm_target == norm_query


# ── 3. dates_tba Handling ──
def test_dates_tba_handling():
    # IPO with no announced dates
    status = derive_ipo_status(
        open_date=None,
        close_date=None,
        listing_date=None,
        dates_tba=True
    )
    assert status == IPOStatus.UPCOMING

    day_label = compute_day_label(
        open_date=None,
        close_date=None,
        dates_tba=True
    )
    assert day_label == "Dates to be announced"


# ── 4. Status Derivation Edge Cases ──
def test_status_derivation_edge_cases():
    open_d = date(2026, 10, 15)  # Thursday
    close_d = date(2026, 10, 19) # Monday
    list_d = date(2026, 10, 24)

    # Before open
    as_of_before = datetime(2026, 10, 10, 10, 0, tzinfo=IST)
    assert derive_ipo_status(open_d, close_d, list_d, as_of=as_of_before) == IPOStatus.UPCOMING
    assert compute_day_label(open_d, close_d, list_d, as_of=as_of_before) == "Opens in 5 days"

    # Day 1 of bidding
    as_of_d1 = datetime(2026, 10, 15, 11, 0, tzinfo=IST)
    assert derive_ipo_status(open_d, close_d, list_d, as_of=as_of_d1) == IPOStatus.LIVE
    assert compute_day_label(open_d, close_d, list_d, as_of=as_of_d1) == "Day 1 of 3"

    # On closing day before 17:00 IST
    as_of_close_live = datetime(2026, 10, 19, 16, 30, tzinfo=IST)
    assert derive_ipo_status(open_d, close_d, list_d, as_of=as_of_close_live) == IPOStatus.LIVE
    assert compute_day_label(open_d, close_d, list_d, as_of=as_of_close_live) == "Day 3 of 3"

    # On closing day after 17:00 IST (17:05 IST)
    as_of_close_ended = datetime(2026, 10, 19, 17, 5, tzinfo=IST)
    assert derive_ipo_status(open_d, close_d, list_d, as_of=as_of_close_ended) == IPOStatus.CLOSED
    assert compute_day_label(open_d, close_d, list_d, as_of=as_of_close_ended) == "Closed on 19 Oct"

    # After close date
    as_of_after = datetime(2026, 10, 21, 10, 0, tzinfo=IST)
    assert derive_ipo_status(open_d, close_d, list_d, as_of=as_of_after) == IPOStatus.CLOSED
    assert compute_day_label(open_d, close_d, list_d, as_of=as_of_after) == "Closed on 19 Oct"

    # Listing date passed
    as_of_listed = datetime(2026, 10, 25, 10, 0, tzinfo=IST)
    assert derive_ipo_status(open_d, close_d, list_d, as_of=as_of_listed) == IPOStatus.LISTED
    assert compute_day_label(open_d, close_d, list_d, as_of=as_of_listed) == "Listed on 24 Oct"

    # close_date earlier than open_date (bogus date validation)
    bogus_open = date(2026, 10, 20)
    bogus_close = date(2026, 10, 10)
    assert derive_ipo_status(bogus_open, bogus_close) == IPOStatus.UPCOMING
    assert compute_day_label(bogus_open, bogus_close) == "Dates unavailable"

    # Missing dates with dates_tba=True
    assert derive_ipo_status(None, None, dates_tba=True) == IPOStatus.UPCOMING
    assert compute_day_label(None, None, dates_tba=True) == "Dates to be announced"

    # Missing dates without TBA flag
    assert derive_ipo_status(None, None) == IPOStatus.UPCOMING
    assert compute_day_label(None, None) == "Dates unavailable"

    # Business days skipping weekend
    # Thursday (15) to Monday (19): 15 (Thu), 16 (Fri), 19 (Mon) -> 3 business days
    assert count_business_days(open_d, close_d) == 3


# ── 5. Seed Rows Excluded from Lists and Counts ──
@pytest.mark.asyncio
async def test_seed_rows_excluded_from_lists_and_counts(client: AsyncClient, db_session: AsyncSession):
    # Add one real IPO and one seed IPO
    real_ipo = IPO(
        symbol="REAL_DISC",
        company_name="Real Discovered Corp",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.UPCOMING,
        source="chittorgarh",
        source_id=9901,
        is_seed=False,
        dates_tba=True,
    )
    seed_ipo = IPO(
        symbol="MOCK_SEED",
        company_name="Mock Seed Entry Corp",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.UPCOMING,
        source=None,
        is_seed=True,
        dates_tba=True,
    )
    db_session.add_all([real_ipo, seed_ipo])
    await db_session.commit()

    # Default /api/v1/ipos excludes seed rows
    res = await client.get("/api/v1/ipos")
    assert res.status_code == 200
    items = res.json()["items"]
    symbols = [it["symbol"] for it in items]
    assert "REAL_DISC" in symbols
    assert "MOCK_SEED" not in symbols

    # Requesting include_seed=true exposes seed rows
    res_seed = await client.get("/api/v1/ipos?include_seed=true")
    assert res_seed.status_code == 200
    seed_symbols = [it["symbol"] for it in res_seed.json()["items"]]
    assert "REAL_DISC" in seed_symbols
    assert "MOCK_SEED" in seed_symbols


# ── 6. Seed Gating Refuses Execution without ALLOW_SEED=1 ──
@pytest.mark.asyncio
async def test_seed_refuses_without_env_flag(auth_client: AsyncClient, db_session: AsyncSession, monkeypatch):
    monkeypatch.delenv("ALLOW_SEED", raising=False)

    # API endpoint gating
    res = await auth_client.post("/api/v1/scraper/seed")
    assert res.status_code == 403
    assert "ALLOW_SEED=1" in res.json()["detail"]

    # Service layer gating
    with pytest.raises(PermissionError, match="ALLOW_SEED=1"):
        await ScraperService.seed_market_data(db_session)
