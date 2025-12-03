from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from liq.sim.accounting import AccountState
from liq.types import Fill


def make_fill(symbol: str, side: str, price: str, qty: str, ts: datetime | None = None) -> Fill:
    return Fill(
        fill_id=uuid4(),
        client_order_id=uuid4(),
        symbol=symbol,
        side=side,
        quantity=Decimal(qty),
        price=Decimal(price),
        commission=Decimal("0"),
        timestamp=ts or datetime.now(timezone.utc),
    )


def test_fifo_realized_pnl_long() -> None:
    now = datetime.now(timezone.utc)
    acct = AccountState(cash=Decimal("100"))
    acct.apply_fill(make_fill("AAPL", "buy", "10", "1", now))
    acct.apply_fill(make_fill("AAPL", "buy", "20", "1", now + timedelta(minutes=1)))
    sell_fill = make_fill("AAPL", "sell", "15", "1", now + timedelta(minutes=2))
    realized = acct.apply_fill(sell_fill)

    assert realized == Decimal("5")
    assert acct.cash == Decimal("85")  # 100 -10 -20 +15
    record = acct.positions["AAPL"]
    assert record.net_quantity == Decimal("1")
    assert record.avg_entry_price == Decimal("20")


def test_short_entry_and_cover_realized_pnl() -> None:
    now = datetime.now(timezone.utc)
    acct = AccountState(cash=Decimal("100"))
    acct.apply_fill(make_fill("MSFT", "sell", "10", "1", now))
    buy_fill = make_fill("MSFT", "buy", "8", "1", now + timedelta(minutes=1))
    realized = acct.apply_fill(buy_fill)

    assert realized == Decimal("2")  # 10 - 8
    assert acct.cash == Decimal("102")  # +10 then -8
    assert acct.positions["MSFT"].net_quantity == Decimal("0")


def test_settlement_queue_release() -> None:
    now = datetime.now(timezone.utc)
    acct = AccountState(cash=Decimal("0"))
    acct.apply_fill(make_fill("AAPL", "sell", "5", "10", now), settlement_days=1)

    assert acct.cash == Decimal("0")
    assert acct.unsettled_cash == Decimal("50")
    acct.process_settlement(now + timedelta(days=1, minutes=1))
    assert acct.unsettled_cash == Decimal("0")
    assert acct.cash == Decimal("50")


def test_portfolio_state_marks_midrange() -> None:
    now = datetime.now(timezone.utc)
    acct = AccountState(cash=Decimal("100"))
    acct.apply_fill(make_fill("AAPL", "buy", "10", "1", now))

    state = acct.to_portfolio_state(marks={"AAPL": Decimal("12")}, timestamp=now)
    pos = state.positions["AAPL"]
    assert pos.current_price == Decimal("12")
    # market_value property uses current_price
    assert pos.market_value == Decimal("12")
    # equity includes cash + unsettled (0) + market_value
    assert state.equity == Decimal("102")


def test_to_portfolio_state_realized_sum() -> None:
    now = datetime.now(timezone.utc)
    acct = AccountState(cash=Decimal("0"))
    acct.apply_fill(make_fill("AAPL", "buy", "10", "1", now))
    acct.apply_fill(make_fill("AAPL", "sell", "12", "1", now + timedelta(minutes=1)))
    state = acct.to_portfolio_state(marks={}, timestamp=now)
    assert state.realized_pnl == Decimal("2")


def test_fx_conversion_keeps_equity_in_account_currency() -> None:
    now = datetime.now(timezone.utc)
    acct = AccountState(cash=Decimal("1000"))
    fill = make_fill("USD_JPY", "buy", "150", "1", now)
    acct.apply_fill(fill, fx_rates={"USD_JPY": Decimal("150")})
    state = acct.to_portfolio_state(
        marks={"USD_JPY": Decimal("150")},
        timestamp=now,
        fx_rates={"USD_JPY": Decimal("150")},
    )
    # price 150 JPY converts to 1 USD
    assert state.cash == Decimal("999")
    assert state.equity == Decimal("1000")
    pos = state.positions["USD_JPY"]
    assert pos.average_price == Decimal("1")
