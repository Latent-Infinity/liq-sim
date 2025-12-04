from datetime import datetime, timezone
from decimal import Decimal

from liq.sim.accounting import AccountState, PositionLot, PositionRecord
from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.financing import daily_swap
from liq.sim.simulator import Simulator
from liq.core import Bar, OrderRequest
from liq.core.enums import OrderSide, OrderType, TimeInForce


def make_order(ts: datetime) -> OrderRequest:
    return OrderRequest(
        symbol="EUR_USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        time_in_force=TimeInForce.DAY,
        timestamp=ts,
    )


def make_bar(ts: datetime, price: str) -> Bar:
    return Bar(
        symbol="EUR_USD",
        timestamp=ts,
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal("1000"),
    )


def test_swap_applied_at_roll() -> None:
    cfg = ProviderConfig(
        name="oanda",
        asset_classes=["forex"],
        fee_model="ZeroCommission",
        slippage_model="SpreadBased",
    )
    sim = Simulator(provider_config=cfg, config=SimulatorConfig(min_order_delay_bars=0, initial_capital=Decimal("1000")))

    t0 = datetime(2024, 1, 1, 21, 59, tzinfo=timezone.utc)
    t1 = datetime(2024, 1, 1, 22, 1, tzinfo=timezone.utc)
    orders = [make_order(t0)]
    bars = [make_bar(t0, "1.10"), make_bar(t1, "1.10")]
    result = sim.run(orders, bars, swap_rates={"EUR_USD": Decimal("0.05")})
    assert len(result.fills) == 1
    # swap should reduce equity vs start
    assert result.portfolio_history[-1] < Decimal("1000")


def test_swap_applied_once_per_day() -> None:
    now = datetime(2024, 1, 1, 22, 5, tzinfo=timezone.utc)
    acct = AccountState(cash=Decimal("1000"))
    acct.positions["EUR_USD"] = PositionRecord(
        lots=[PositionLot(quantity=Decimal("1"), entry_price=Decimal("1.10"), entry_time=now)]
    )
    marks = {"EUR_USD": Decimal("1.10")}
    rates = {"EUR_USD": Decimal("0.05")}
    acct.apply_daily_swap(now, swap_rates=rates, marks=marks)
    cash_after_first = acct.cash
    acct.apply_daily_swap(now, swap_rates=rates, marks=marks)
    assert acct.cash == cash_after_first


def test_swap_triple_roll_on_wednesday() -> None:
    now = datetime(2024, 1, 3, 22, 5, tzinfo=timezone.utc)  # Wednesday
    acct = AccountState(cash=Decimal("1000"))
    acct.positions["EUR_USD"] = PositionRecord(
        lots=[PositionLot(quantity=Decimal("1"), entry_price=Decimal("1.0"), entry_time=now)]
    )
    marks = {"EUR_USD": Decimal("1.0")}
    rate = Decimal("0.0365")
    acct.apply_daily_swap(now, swap_rates={"EUR_USD": rate}, marks=marks)
    expected_cost = daily_swap(Decimal("1.0"), rate) * Decimal("3")
    assert acct.cash == Decimal("1000") - expected_cost
