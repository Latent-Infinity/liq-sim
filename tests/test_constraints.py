from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from liq.core import OrderRequest, PortfolioState
from liq.core.enums import OrderType

from liq.sim.constraints import (
    ConstraintViolation,
    check_buying_power,
    check_margin,
    check_pdt,
    check_position_limit,
    check_short_permission,
)


def make_portfolio(equity: Decimal, day_trades_remaining: int | None = None) -> PortfolioState:
    return PortfolioState(
        cash=equity,
        unsettled_cash=Decimal("0"),
        positions={},
        realized_pnl=Decimal("0"),
        buying_power=None,
        margin_used=None,
        day_trades_remaining=day_trades_remaining,
        timestamp=datetime.now(UTC),
    )


def test_position_limit_rejects_when_exceeds() -> None:
    portfolio = make_portfolio(Decimal("1000"))
    class Order:  # lightweight stand-in
        quantity = Decimal("10")
    order = Order()
    with pytest.raises(ConstraintViolation):
        check_position_limit(order, portfolio, max_position_pct=0.1, mark_price=Decimal("20"))


def test_position_limit_allows_within_limit() -> None:
    portfolio = make_portfolio(Decimal("1000"))
    class Order:
        quantity = Decimal("1")
    order = Order()
    check_position_limit(order, portfolio, max_position_pct=0.1, mark_price=Decimal("50"))


def test_buying_power_rejects_buy() -> None:
    portfolio = make_portfolio(Decimal("100"))
    order = OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side="buy",
        order_type=OrderType.MARKET,
        quantity=Decimal("2"),
        timestamp=portfolio.timestamp,
    )
    with pytest.raises(ConstraintViolation):
        check_buying_power(order, portfolio, mark_price=Decimal("100"))


def test_margin_rejects_when_required_exceeds_equity() -> None:
    portfolio = make_portfolio(Decimal("100"))
    order = OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side="buy",
        order_type=OrderType.MARKET,
        quantity=Decimal("2"),
        timestamp=portfolio.timestamp,
    )
    with pytest.raises(ConstraintViolation):
        check_margin(order, portfolio, mark_price=Decimal("100"), initial_margin_rate=Decimal("1.0"))


def test_pdt_allows_when_none() -> None:
    portfolio = make_portfolio(Decimal("1000"), day_trades_remaining=None)
    check_pdt(portfolio, is_day_trade=True)


def test_pdt_rejects_when_exhausted() -> None:
    portfolio = make_portfolio(Decimal("1000"), day_trades_remaining=0)
    with pytest.raises(ConstraintViolation):
        check_pdt(portfolio, is_day_trade=True)


def test_short_rejects_when_shorting_disallowed() -> None:
    portfolio = make_portfolio(Decimal("1000"))
    # attempt to short 1 share from flat
    order = OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side="sell",
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        timestamp=portfolio.timestamp,
    )
    with pytest.raises(ConstraintViolation):
        check_short_permission(order, portfolio, short_enabled=False)


def test_short_requires_locate_when_configured() -> None:
    portfolio = make_portfolio(Decimal("1000"))
    order = OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side="sell",
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        timestamp=portfolio.timestamp,
    )
    with pytest.raises(ConstraintViolation):
        check_short_permission(order, portfolio, short_enabled=True, locate_required=True)


def test_short_allows_when_locate_provided() -> None:
    portfolio = make_portfolio(Decimal("1000"))
    order = OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side="sell",
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        timestamp=portfolio.timestamp,
        metadata={"locate_available": True},
    )
    check_short_permission(order, portfolio, short_enabled=True, locate_required=True)
