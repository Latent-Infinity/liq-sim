from decimal import Decimal

from liq.sim.risk_caps import (
    enforce_equity_floor,
    enforce_frequency_cap,
    enforce_net_position_cap,
    enforce_pyramiding_limit,
)


def test_net_position_cap() -> None:
    assert enforce_net_position_cap(Decimal("10"), Decimal("100"), 0.2) is True
    assert enforce_net_position_cap(Decimal("30"), Decimal("100"), 0.2) is False


def test_pyramiding_limit() -> None:
    assert enforce_pyramiding_limit(1, 2) is True
    assert enforce_pyramiding_limit(2, 2) is False


def test_equity_floor() -> None:
    assert enforce_equity_floor(Decimal("90"), 0.8, Decimal("100")) is True
    assert enforce_equity_floor(Decimal("70"), 0.8, Decimal("100")) is False


def test_frequency_cap() -> None:
    assert enforce_frequency_cap(5, 10) is True
    assert enforce_frequency_cap(10, 10) is False
