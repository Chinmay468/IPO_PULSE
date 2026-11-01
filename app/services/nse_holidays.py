"""
NSE (National Stock Exchange of India) Trading Holidays & Calendar Utilities.
Covers equity segment market holidays (2020-2026) and trading day validation.
"""

from datetime import date, datetime, timedelta
from typing import Set, List, Union


# Standard NSE Equity Market Closed Holidays (YYYY-MM-DD)
NSE_HOLIDAYS: Set[date] = {
    # 2020
    date(2020, 2, 21),  # Mahashivratri
    date(2020, 3, 10),  # Holi
    date(2020, 4, 2),   # Ram Navami
    date(2020, 4, 6),   # Mahavir Jayanti
    date(2020, 4, 10),  # Good Friday
    date(2020, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    date(2020, 5, 1),   # Maharashtra Day
    date(2020, 5, 25),  # Id-Ul-Fitr
    date(2020, 10, 2),  # Mahatma Gandhi Jayanti
    date(2020, 11, 16), # Diwali Balipratipada
    date(2020, 11, 30), # Gurunanak Jayanti
    date(2020, 12, 25), # Christmas

    # 2021
    date(2021, 1, 26),  # Republic Day
    date(2021, 3, 11),  # Mahashivratri
    date(2021, 3, 29),  # Holi
    date(2021, 4, 2),   # Good Friday
    date(2021, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    date(2021, 4, 21),  # Ram Navami
    date(2021, 5, 13),  # Id-Ul-Fitr
    date(2021, 7, 21),  # Bakri Id
    date(2021, 8, 19),  # Moharram
    date(2021, 9, 10),  # Ganesh Chaturthi
    date(2021, 10, 15), # Dussehra
    date(2021, 11, 5),  # Diwali Balipratipada
    date(2021, 11, 19), # Gurunanak Jayanti

    # 2022
    date(2022, 1, 26),  # Republic Day
    date(2022, 3, 1),   # Mahashivratri
    date(2022, 3, 18),  # Holi
    date(2022, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    date(2022, 4, 15),  # Good Friday
    date(2022, 5, 3),   # Id-Ul-Fitr
    date(2022, 8, 9),   # Moharram
    date(2022, 8, 15),  # Independence Day
    date(2022, 8, 31),  # Ganesh Chaturthi
    date(2022, 10, 5),  # Dussehra
    date(2022, 10, 26), # Diwali Balipratipada
    date(2022, 11, 8),  # Gurunanak Jayanti

    # 2023
    date(2023, 1, 26),  # Republic Day
    date(2023, 3, 7),   # Holi
    date(2023, 3, 30),  # Ram Navami
    date(2023, 4, 4),   # Mahavir Jayanti
    date(2023, 4, 7),   # Good Friday
    date(2023, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    date(2023, 5, 1),   # Maharashtra Day
    date(2023, 6, 29),  # Bakri Id
    date(2023, 8, 15),  # Independence Day
    date(2023, 9, 19),  # Ganesh Chaturthi
    date(2023, 10, 2),  # Mahatma Gandhi Jayanti
    date(2023, 10, 24), # Dussehra
    date(2023, 11, 14), # Diwali Balipratipada
    date(2023, 11, 27), # Gurunanak Jayanti
    date(2023, 12, 25), # Christmas

    # 2024
    date(2024, 1, 22),  # Special Holiday (Ayodhya Pran Pratishtha)
    date(2024, 1, 26),  # Republic Day
    date(2024, 3, 8),   # Mahashivratri
    date(2024, 3, 25),  # Holi
    date(2024, 3, 29),  # Good Friday
    date(2024, 4, 11),  # Id-Ul-Fitr (Ramzan Id)
    date(2024, 4, 17),  # Shri Ram Navami
    date(2024, 5, 1),   # Maharashtra Day
    date(2024, 5, 20),  # General Parliamentary Elections (Mumbai)
    date(2024, 6, 17),  # Bakri Id
    date(2024, 7, 17),  # Moharram
    date(2024, 8, 15),  # Independence Day
    date(2024, 10, 2),  # Mahatma Gandhi Jayanti
    date(2024, 11, 1),  # Diwali Laxmi Pujan (Day trading closed, evening Muhurat only)
    date(2024, 11, 15), # Gurunanak Jayanti
    date(2024, 11, 20), # Maharashtra Assembly Elections
    date(2024, 12, 25), # Christmas

    # 2025
    date(2025, 2, 26),  # Mahashivratri
    date(2025, 3, 14),  # Holi
    date(2025, 3, 31),  # Id-Ul-Fitr
    date(2025, 4, 10),  # Mahavir Jayanti
    date(2025, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 1),   # Maharashtra Day
    date(2025, 6, 7),   # Bakri Id
    date(2025, 8, 15),  # Independence Day
    date(2025, 8, 27),  # Ganesh Chaturthi
    date(2025, 10, 2),  # Mahatma Gandhi Jayanti / Dussehra
    date(2025, 10, 21), # Diwali Balipratipada
    date(2025, 11, 5),  # Gurunanak Jayanti
    date(2025, 12, 25), # Christmas

    # 2026
    date(2026, 1, 26),  # Republic Day
    date(2026, 2, 16),  # Mahashivratri
    date(2026, 3, 3),   # Holi
    date(2026, 3, 20),  # Id-Ul-Fitr
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day
    date(2026, 5, 27),  # Bakri Id
    date(2026, 6, 26),  # Moharram
    date(2026, 10, 2),  # Mahatma Gandhi Jayanti
    date(2026, 10, 20), # Dussehra
    date(2026, 11, 10), # Diwali Balipratipada
    date(2026, 11, 24), # Gurunanak Jayanti
    date(2026, 12, 25), # Christmas
}


def is_trading_day(target_date: Union[date, datetime]) -> bool:
    """
    Returns True if target_date is an NSE equity trading day (Monday-Friday, non-holiday).
    """
    if isinstance(target_date, datetime):
        d = target_date.date()
    else:
        d = target_date

    # 0 = Monday, ..., 4 = Friday, 5 = Saturday, 6 = Sunday
    if d.weekday() >= 5:
        return False

    return d not in NSE_HOLIDAYS


def get_trading_days(start_date: date, end_date: date) -> List[date]:
    """
    Returns an ordered list of all NSE trading days between start_date and end_date (inclusive).
    """
    if start_date > end_date:
        return []

    trading_days = []
    curr = start_date
    while curr <= end_date:
        if is_trading_day(curr):
            trading_days.append(curr)
        curr += timedelta(days=1)
    return trading_days


def get_previous_trading_day(ref_date: date) -> date:
    """
    Returns the most recent NSE trading day strictly prior to ref_date.
    """
    curr = ref_date - timedelta(days=1)
    while not is_trading_day(curr):
        curr -= timedelta(days=1)
    return curr


def get_missing_trading_days(dates_present: Set[date], start_date: date, end_date: date) -> List[date]:
    """
    Identifies all trading days between start_date and end_date that are missing from dates_present.
    """
    expected = get_trading_days(start_date, end_date)
    return [d for d in expected if d not in dates_present]
