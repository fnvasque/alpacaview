"""
Unit tests for src.forward_testing.market_hours.is_market_open().

No network, no DB. All times are injected as UTC datetimes.
Reference Monday: 2026-05-18. May is EDT (UTC-4).
"""
from datetime import datetime, timedelta, timezone

import pytz
import pytest

from src.forward_testing.market_hours import is_market_open

_NY = pytz.timezone("America/New_York")
_BASE_MONDAY = datetime(2026, 5, 18)  # known Monday


def make_utc(weekday_offset: int, hour: int, minute: int) -> datetime:
    """Build UTC datetime for BASE_MONDAY + offset at hour:minute ET."""
    target = _BASE_MONDAY + timedelta(days=weekday_offset)
    local_naive = target.replace(hour=hour, minute=minute, second=0, microsecond=0)
    local_aware = _NY.localize(local_naive)
    return local_aware.astimezone(timezone.utc)


def test_weekday_inside_hours_returns_true() -> None:
    assert is_market_open(make_utc(0, 10, 0)) is True


def test_weekday_at_open_boundary_returns_true() -> None:
    assert is_market_open(make_utc(0, 9, 30)) is True


def test_weekday_at_close_boundary_returns_false() -> None:
    assert is_market_open(make_utc(0, 16, 0)) is False


def test_weekday_before_open_returns_false() -> None:
    assert is_market_open(make_utc(0, 9, 0)) is False


def test_weekday_after_close_returns_false() -> None:
    assert is_market_open(make_utc(0, 17, 0)) is False


def test_saturday_returns_false() -> None:
    assert is_market_open(make_utc(5, 12, 0)) is False


def test_sunday_returns_false() -> None:
    assert is_market_open(make_utc(6, 12, 0)) is False


def test_friday_inside_hours_returns_true() -> None:
    assert is_market_open(make_utc(4, 14, 0)) is True


def test_friday_after_close_returns_false() -> None:
    assert is_market_open(make_utc(4, 16, 1)) is False
