from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from liq.core import Fill

from liq.sim.accounting import AccountState, PositionLot, PositionRecord


def make_fill(symbol: str, side: str, price: str, qty: str, ts: datetime | None = None) -> Fill:
    return Fill(
        fill_id=uuid4(),
        client_order_id=uuid4(),
        symbol=symbol,
        side=side,
        quantity=Decimal(qty),
        price=Decimal(price),
        commission=Decimal("0"),
        timestamp=ts or datetime.now(UTC),
    )


def test_fifo_realized_pnl_long() -> None:
    now = datetime.now(UTC)
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
    now = datetime.now(UTC)
    acct = AccountState(cash=Decimal("100"))
    acct.apply_fill(make_fill("MSFT", "sell", "10", "1", now))
    buy_fill = make_fill("MSFT", "buy", "8", "1", now + timedelta(minutes=1))
    realized = acct.apply_fill(buy_fill)

    assert realized == Decimal("2")  # 10 - 8
    assert acct.cash == Decimal("102")  # +10 then -8
    assert acct.positions["MSFT"].net_quantity == Decimal("0")


def test_settlement_queue_release() -> None:
    now = datetime.now(UTC)
    acct = AccountState(cash=Decimal("0"))
    acct.apply_fill(make_fill("AAPL", "sell", "5", "10", now), settlement_days=1)

    assert acct.cash == Decimal("0")
    assert acct.unsettled_cash == Decimal("50")
    acct.process_settlement(now + timedelta(days=1, minutes=1))
    assert acct.unsettled_cash == Decimal("0")
    assert acct.cash == Decimal("50")


def test_portfolio_state_marks_midrange() -> None:
    now = datetime.now(UTC)
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
    now = datetime.now(UTC)
    acct = AccountState(cash=Decimal("0"))
    acct.apply_fill(make_fill("AAPL", "buy", "10", "1", now))
    acct.apply_fill(make_fill("AAPL", "sell", "12", "1", now + timedelta(minutes=1)))
    state = acct.to_portfolio_state(marks={}, timestamp=now)
    assert state.realized_pnl == Decimal("2")


def test_fx_conversion_keeps_equity_in_account_currency() -> None:
    now = datetime.now(UTC)
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


def test_borrow_cost_converts_mark_when_fx_provided() -> None:
    now = datetime.now(UTC)
    acct = AccountState(cash=Decimal("1000"))
    fill = make_fill("USD_JPY", "sell", "150", "1", now)
    acct.apply_fill(fill, borrow_rate_annual=Decimal("0.0365"), fx_rates={"USD_JPY": Decimal("150")})
    # borrow cost should be accrued in USD (1 notional * rate/365)
    expected_cost = Decimal("1") * Decimal("0.0365") / Decimal("365")
    assert acct.cash == Decimal("1001") - expected_cost


def test_realized_conversion_skips_when_rate_missing() -> None:
    now = datetime.now(UTC)
    acct = AccountState(cash=Decimal("0"))
    acct.apply_fill(make_fill("EUR_JPY", "buy", "150", "1", now), fx_rates={"USD_JPY": Decimal("150")})
    state = acct.to_portfolio_state(marks={"EUR_JPY": Decimal("150")}, timestamp=now, fx_rates={"USD_JPY": Decimal("150")})
    # no KeyError; realized remains zero and mark stays unconverted because USD_EUR missing
    assert state.realized_pnl == Decimal("0")
    assert state.positions["EUR_JPY"].current_price == Decimal("1")


def test_zero_quantity_position_keeps_avg_price() -> None:
    now = datetime.now(UTC)
    acct = AccountState(cash=Decimal("0"))
    acct.positions["AAPL"] = PositionRecord()
    state = acct.to_portfolio_state(marks={"AAPL": Decimal("10")}, timestamp=now)
    assert state.positions["AAPL"].quantity == Decimal("0")
    assert state.positions["AAPL"].average_price == Decimal("0")


def test_settlement_queue_retains_future_release() -> None:
    now = datetime.now(UTC)
    acct = AccountState(cash=Decimal("0"))
    acct.apply_fill(make_fill("AAPL", "sell", "10", "1", now), settlement_days=2)
    acct.process_settlement(now + timedelta(days=1))
    assert acct.unsettled_cash == Decimal("10")


def test_mixed_lots_skip_wrong_direction() -> None:
    now = datetime.now(UTC)
    rec = PositionRecord(
        lots=[
            PositionLot(quantity=Decimal("-1"), entry_price=Decimal("5"), entry_time=now),
            PositionLot(quantity=Decimal("1"), entry_price=Decimal("10"), entry_time=now),
        ]
    )
    fill = make_fill("MIX", "sell", "8", "1", now)
    realized = rec.apply_fill(fill)
    # Should have skipped the short lot, closed the long, and left the short intact
    assert realized == Decimal("-2")
    assert rec.net_quantity == Decimal("-1")
