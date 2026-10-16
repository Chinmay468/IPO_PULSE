import pytest
from datetime import date, datetime, timedelta, timezone
from app.core.ipo_timeline import (
    IST,
    count_business_days,
    compute_day_label,
    derive_ipo_status,
)
from app.models.ipo import IPOStatus, IPOType, IPO
from app.services.ipo_service import IPOService
from app.schemas.ipo import IPOCreate


def test_before_open():
    """When today < open_date, status is UPCOMING and label is 'Opens in N days'."""
    as_of = datetime(2026, 10, 10, 10, 0, tzinfo=IST)
    open_d = date(2026, 10, 15)
    close_d = date(2026, 10, 17)

    assert derive_ipo_status(open_d, close_d, as_of=as_of) == IPOStatus.UPCOMING
    assert compute_day_label(open_d, close_d, as_of=as_of) == "Opens in 5 days"

    # Exactly 1 day before
    as_of_one_day = datetime(2026, 10, 14, 15, 0, tzinfo=IST)
    assert derive_ipo_status(open_d, close_d, as_of=as_of_one_day) == IPOStatus.UPCOMING
    assert compute_day_label(open_d, close_d, as_of=as_of_one_day) == "Opens in 1 day"


def test_day_1():
    """On open date during market hours, status is LIVE and label is 'Day 1 of Y'."""
    open_d = date(2026, 10, 12)   # Monday
    close_d = date(2026, 10, 14)  # Wednesday
    as_of = datetime(2026, 10, 12, 10, 30, tzinfo=IST)

    assert derive_ipo_status(open_d, close_d, as_of=as_of) == IPOStatus.LIVE
    assert compute_day_label(open_d, close_d, as_of=as_of) == "Day 1 of 3"


def test_last_day_before_and_after_5pm():
    """
    On the closing day:
    - Before 5:00 PM IST: LIVE and 'Day Y of Y'
    - At or after 5:00 PM IST: CLOSED and 'Closed on <date>'
    """
    open_d = date(2026, 10, 12)   # Monday
    close_d = date(2026, 10, 14)  # Wednesday

    # Before 5 PM IST (e.g. 16:30 IST)
    as_of_live = datetime(2026, 10, 14, 16, 30, tzinfo=IST)
    assert derive_ipo_status(open_d, close_d, as_of=as_of_live) == IPOStatus.LIVE
    assert compute_day_label(open_d, close_d, as_of=as_of_live) == "Day 3 of 3"

    # At 5:00 PM IST (17:00 IST)
    as_of_closed = datetime(2026, 10, 14, 17, 0, tzinfo=IST)
    assert derive_ipo_status(open_d, close_d, as_of=as_of_closed) == IPOStatus.CLOSED
    assert compute_day_label(open_d, close_d, as_of=as_of_closed) == "Closed on 14 Oct"

    # After 5:00 PM IST (e.g. 19:15 IST)
    as_of_evening = datetime(2026, 10, 14, 19, 15, tzinfo=IST)
    assert derive_ipo_status(open_d, close_d, as_of=as_of_evening) == IPOStatus.CLOSED
    assert compute_day_label(open_d, close_d, as_of=as_of_evening) == "Closed on 14 Oct"


def test_after_close():
    """After close_date, status is CLOSED and label shows 'Closed on <date>'."""
    open_d = date(2026, 10, 1)
    close_d = date(2026, 10, 5)
    listing_d = date(2026, 10, 12)
    as_of = datetime(2026, 10, 8, 11, 0, tzinfo=IST)

    assert derive_ipo_status(open_d, close_d, listing_date=listing_d, as_of=as_of) == IPOStatus.CLOSED
    assert compute_day_label(open_d, close_d, listing_date=listing_d, as_of=as_of) == "Closed on 5 Oct"


def test_listing_date_passed():
    """When as_of >= listing_date, status is LISTED and label is 'Listed on <date>'."""
    open_d = date(2026, 10, 1)
    close_d = date(2026, 10, 5)
    listing_d = date(2026, 10, 12)
    as_of = datetime(2026, 10, 12, 10, 0, tzinfo=IST)

    assert derive_ipo_status(open_d, close_d, listing_date=listing_d, as_of=as_of) == IPOStatus.LISTED
    assert compute_day_label(open_d, close_d, listing_date=listing_d, as_of=as_of) == "Listed on 12 Oct"

    # Days after listing
    as_of_later = datetime(2026, 10, 15, 12, 0, tzinfo=IST)
    assert derive_ipo_status(open_d, close_d, listing_date=listing_d, as_of=as_of_later) == IPOStatus.LISTED
    assert compute_day_label(open_d, close_d, listing_date=listing_d, as_of=as_of_later) == "Listed on 12 Oct"


def test_close_earlier_than_open():
    """Invalid span where close_date < open_date yields 'Dates unavailable'."""
    open_d = date(2026, 10, 15)
    close_d = date(2026, 10, 10)
    as_of = datetime(2026, 10, 12, 10, 0, tzinfo=IST)

    assert derive_ipo_status(open_d, close_d, as_of=as_of) == IPOStatus.UPCOMING
    assert compute_day_label(open_d, close_d, as_of=as_of) == "Dates unavailable"


def test_missing_dates():
    """Missing open_date or close_date yields 'Dates unavailable'."""
    as_of = datetime(2026, 10, 12, 10, 0, tzinfo=IST)

    assert derive_ipo_status(None, date(2026, 10, 15), as_of=as_of) == IPOStatus.UPCOMING
    assert compute_day_label(None, date(2026, 10, 15), as_of=as_of) == "Dates unavailable"

    assert derive_ipo_status(date(2026, 10, 10), None, as_of=as_of) == IPOStatus.UPCOMING
    assert compute_day_label(date(2026, 10, 10), None, as_of=as_of) == "Dates unavailable"

    assert derive_ipo_status(None, None, as_of=as_of) == IPOStatus.UPCOMING
    assert compute_day_label(None, None, as_of=as_of) == "Dates unavailable"


def test_weekend_spans():
    """
    Spanning over weekends correctly counts only Monday-Friday business trading days:
    - Friday to Tuesday is 3 business days (Fri, Mon, Tue).
    - On Saturday and Sunday, elapsed business days stay bounded to Friday (1).
    """
    open_d = date(2026, 10, 9)    # Friday
    close_d = date(2026, 10, 13)  # Tuesday

    # Total trading days from Fri to Tue
    assert count_business_days(open_d, close_d) == 3

    # Friday (Day 1)
    as_of_fri = datetime(2026, 10, 9, 14, 0, tzinfo=IST)
    assert compute_day_label(open_d, close_d, as_of=as_of_fri) == "Day 1 of 3"

    # Saturday (weekend, stays Day 1 of 3)
    as_of_sat = datetime(2026, 10, 10, 12, 0, tzinfo=IST)
    assert compute_day_label(open_d, close_d, as_of=as_of_sat) == "Day 1 of 3"

    # Sunday (weekend, stays Day 1 of 3)
    as_of_sun = datetime(2026, 10, 11, 12, 0, tzinfo=IST)
    assert compute_day_label(open_d, close_d, as_of=as_of_sun) == "Day 1 of 3"

    # Monday (Day 2 of 3)
    as_of_mon = datetime(2026, 10, 12, 11, 0, tzinfo=IST)
    assert compute_day_label(open_d, close_d, as_of=as_of_mon) == "Day 2 of 3"

    # Tuesday afternoon before 5 PM (Day 3 of 3)
    as_of_tue_live = datetime(2026, 10, 13, 15, 0, tzinfo=IST)
    assert compute_day_label(open_d, close_d, as_of=as_of_tue_live) == "Day 3 of 3"

    # Tuesday evening after 5 PM (Closed on 13 Oct)
    as_of_tue_closed = datetime(2026, 10, 13, 17, 30, tzinfo=IST)
    assert compute_day_label(open_d, close_d, as_of=as_of_tue_closed) == "Closed on 13 Oct"


@pytest.mark.asyncio
async def test_service_date_validation_on_save(db_session):
    """
    IPOService.create_ipo sets dates to None and records invalid_dates in data_quality
    when close_date < open_date.
    """
    create_dto = IPOCreate(
        symbol="INVALIDDATES",
        company_name="Invalid Dates Ltd",
        ipo_type=IPOType.MAINBOARD,
        open_date=date(2026, 10, 20),
        close_date=date(2026, 10, 15),  # close < open
    )
    ipo = await IPOService.create_ipo(db_session, create_dto)
    assert ipo.open_date is None
    assert ipo.close_date is None
    assert "invalid_dates" in ipo.data_quality["missing_fields"]
    assert ipo.data_quality["status"] == "incomplete"


@pytest.mark.asyncio
async def test_scheduled_ipo_status_correction(db_session, monkeypatch):
    """
    Verifies that scheduled_ipo_status_correction updates IPO statuses in the database
    based on official IST timeline dates and recalculates composite scores.
    """
    from app.services.scheduler import scheduled_ipo_status_correction
    from unittest.mock import patch

    # Create an IPO that was marked LIVE but close_date has passed
    from datetime import timedelta
    today_dt = date.today()
    old_closed_ipo = IPO(
        symbol="EXPIREDLIVE",
        company_name="Expired Live Ltd",
        ipo_type=IPOType.MAINBOARD,
        status=IPOStatus.LIVE,  # Stuck as LIVE
        open_date=today_dt - timedelta(days=15),
        close_date=today_dt - timedelta(days=10),
        listing_date=today_dt + timedelta(days=10),
        issue_price=100.0,
    )
    db_session.add(old_closed_ipo)
    await db_session.commit()

    # Mock AsyncSessionLocal to return the test db_session
    class DummyAsyncSessionLocal:
        def __init__(self, session):
            self.session = session
        async def __aenter__(self):
            return self.session
        async def __aexit__(self, exc_type, exc, tb):
            pass

    with patch("app.services.scheduler.AsyncSessionLocal", return_value=DummyAsyncSessionLocal(db_session)):
        await scheduled_ipo_status_correction()

    await db_session.refresh(old_closed_ipo)
    assert old_closed_ipo.status == IPOStatus.CLOSED

