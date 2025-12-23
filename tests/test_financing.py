from datetime import UTC, datetime
from decimal import Decimal

from liq.sim.financing import borrow_cost, daily_swap, swap_applicable, swap_multiplier_for_weekday


def test_daily_swap_calculation() -> None:
    cost = daily_swap(Decimal("10000"), Decimal("0.05"))
    assert cost == Decimal("10000") * Decimal("0.05") / Decimal("365")


def test_borrow_cost_alias() -> None:
    cost = borrow_cost(Decimal("5000"), Decimal("0.1"))
    assert cost == daily_swap(Decimal("5000"), Decimal("0.1"))


def test_swap_applicable_at_roll() -> None:
    ts = datetime(2024, 1, 1, 22, 0, tzinfo=UTC)
    assert swap_applicable(ts)


def test_swap_applicable_handles_dst_shift() -> None:
    summer_before = datetime(2024, 7, 1, 20, 59, tzinfo=UTC)
    summer_after = datetime(2024, 7, 1, 21, 0, tzinfo=UTC)
    assert not swap_applicable(summer_before)
    assert swap_applicable(summer_after)


def test_swap_multiplier_wednesday() -> None:
    ts = datetime(2024, 1, 3, 12, 0, tzinfo=UTC)  # Wednesday
    assert swap_multiplier_for_weekday(ts) == 3
