"""Financing helpers for swaps/borrow."""

from datetime import UTC, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo


def daily_swap(notional: Decimal, annual_rate: Decimal) -> Decimal:
    """Calculate daily financing given notional and annual rate."""
    return notional * annual_rate / Decimal("365")


def borrow_cost(notional: Decimal, annual_borrow_rate: Decimal) -> Decimal:
    """Daily borrow cost for shorts."""
    return daily_swap(notional, annual_borrow_rate)


def swap_applicable(timestamp: datetime) -> bool:
    """Return True if swaps should be applied at 5pm New York (DST-aware via zoneinfo)."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    ny_time = timestamp.astimezone(ZoneInfo("America/New_York"))
    roll_time = time(17, 0, tzinfo=ZoneInfo("America/New_York"))
    return ny_time.timetz() >= roll_time


def swap_multiplier_for_weekday(timestamp: datetime) -> int:
    """Triple swap on Wednesday per FX convention."""
    if timestamp.weekday() == 2:  # Wednesday
        return 3
    return 1
