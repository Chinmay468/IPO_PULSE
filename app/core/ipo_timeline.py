from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple, Union
from app.models.ipo import IPOStatus

# Indian Standard Time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))


def get_ist_now() -> datetime:
    """Returns the current timezone-aware datetime in Indian Standard Time (IST)."""
    return datetime.now(IST)


def get_ist_today() -> date:
    """Returns the current date in Indian Standard Time (IST)."""
    return get_ist_now().date()


def count_business_days(start_date: date, end_date: date) -> int:
    """
    Counts trading/business days (Monday to Friday, weekday < 5)
    between start_date and end_date (inclusive).
    Returns 0 if end_date < start_date.
    """
    if end_date < start_date:
        return 0

    business_days = 0
    curr = start_date
    while curr <= end_date:
        if curr.weekday() < 5:  # Monday = 0, Friday = 4
            business_days += 1
        curr += timedelta(days=1)

    return business_days


def compute_day_label(
    open_date: Optional[date],
    close_date: Optional[date],
    listing_date: Optional[date] = None,
    as_of: Optional[Union[date, datetime]] = None,
    dates_tba: bool = False
) -> str:
    """
    Shared canonical helper for computing the timeline / day label using IST dates:
    - If dates_tba is True -> "Dates to be announced"
    - If dates missing or close_date < open_date -> "Dates unavailable" (or "Dates to be announced" if TBA)
    - If today < open_date -> "Opens in N days" (or "Opens in 1 day")
    - If open_date <= today <= close_date -> "Day X of Y" where:
        X = business days since open (inclusive, bounded in [1, Y])
        Y = business days from open to close (inclusive, min 1)
    - If today > close_date (or on close_date at/after 5 PM IST):
        If listing_date and today >= listing_date -> "Listed on <date>"
        Else -> "Closed on <date>"
    """
    if dates_tba:
        return "Dates to be announced"

    if as_of is None:
        as_of = get_ist_now()

    if isinstance(as_of, datetime):
        as_of_dt = as_of
        as_of_date = as_of.date()
    else:
        as_of_dt = None
        as_of_date = as_of

    # Missing or invalid dates validation
    if not open_date or not close_date or close_date < open_date:
        return "Dates to be announced" if dates_tba else "Dates unavailable"

    if as_of_date < open_date:
        days_to_open = (open_date - as_of_date).days
        if days_to_open == 1:
            return "Opens in 1 day"
        return f"Opens in {days_to_open} days"

    # If listing date has passed
    if listing_date and as_of_date >= listing_date:
        return f"Listed on {listing_date.day} {listing_date.strftime('%b')}"

    # If past close date, or on close date after 5 PM IST
    if as_of_date > close_date or (as_of_dt and as_of_date == close_date and as_of_dt.hour >= 17):
        return f"Closed on {close_date.day} {close_date.strftime('%b')}"

    if open_date <= as_of_date <= close_date:
        total_b_days = count_business_days(open_date, close_date)
        y = max(1, total_b_days)
        elapsed_b_days = count_business_days(open_date, as_of_date)
        x = max(1, min(elapsed_b_days, y))
        return f"Day {x} of {y}"

    return f"Closed on {close_date.day} {close_date.strftime('%b')}"


def derive_ipo_status(
    open_date: Optional[date],
    close_date: Optional[date],
    listing_date: Optional[date] = None,
    as_of: Optional[Union[date, datetime]] = None,
    dates_tba: bool = False
) -> IPOStatus:
    """
    Derives the true life-cycle state of an IPO strictly from official dates:
    - If dates_tba is True or dates missing -> UPCOMING (or LISTED if listing_date has passed)
    - LISTED: if listing_date has passed (as_of_date >= listing_date)
    - CLOSED: after close_date, OR on close_date at/after 5:00 PM IST (17:00 IST)
    - LIVE: open_date <= as_of_date <= close_date (before 5:00 PM IST on close_date)
    - UPCOMING: before open_date or dates_tba
    """
    if as_of is None:
        as_of = get_ist_now()

    if isinstance(as_of, datetime):
        as_of_dt = as_of
        as_of_date = as_of.date()
    else:
        as_of_dt = None
        as_of_date = as_of

    if listing_date and as_of_date >= listing_date:
        return IPOStatus.LISTED

    if dates_tba:
        return IPOStatus.UPCOMING

    if not open_date or not close_date or close_date < open_date:
        return IPOStatus.UPCOMING

    if as_of_date > close_date:
        return IPOStatus.CLOSED

    if as_of_date == close_date:
        # Bidding officially closes at 5:00 PM IST on the closing day
        if as_of_dt and as_of_dt.hour >= 17:
            return IPOStatus.CLOSED
        return IPOStatus.LIVE

    if open_date <= as_of_date < close_date:
        return IPOStatus.LIVE

    return IPOStatus.UPCOMING

