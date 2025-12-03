from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator
from liq.types import Bar, OrderRequest
from liq.types.enums import OrderSide, OrderType, TimeInForce


def make_order(timestamp: datetime, side: str, qty: str, limit: str | None = None) -> OrderRequest:
    return OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side=side,
        order_type=OrderType.LIMIT if limit else OrderType.MARKET,
        quantity=Decimal(qty),
        limit_price=Decimal(limit) if limit else None,
        time_in_force=TimeInForce.DAY,
        timestamp=timestamp,
    )


def make_bar(ts: datetime, open_price: str, high: str, low: str, close: str) -> Bar:
    return Bar(
        symbol="AAPL",
        timestamp=ts,
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1000"),
    )


def test_simulator_executes_with_delay_and_fees() -> None:
    provider_cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="TieredMakerTaker",
        fee_params={"maker_bps": "10", "taker_bps": "20"},
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
        settlement_days=0,
    )
    sim = Simulator(provider_config=provider_cfg, config=SimulatorConfig(min_order_delay_bars=1))

    t0 = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    orders = [
        make_order(t0, side="buy", qty="1", limit="100"),
    ]
    bars = [
        make_bar(t0, "99", "101", "98", "100"),  # order not yet eligible
        make_bar(t0 + timedelta(minutes=1), "99", "101", "98", "100"),  # executes here
    ]

    result = sim.run(orders, bars)
    assert len(result.fills) == 1
    fill = result.fills[0]
    assert fill.price == Decimal("99")  # gap benefit
    assert fill.commission > Decimal("0")  # taker assumed since price crosses open
    assert len(result.portfolio_history) == 2


def test_simulator_honors_settlement_days() -> None:
    provider_cfg = ProviderConfig(
        name="robinhood",
        asset_classes=["equity"],
        fee_model="ZeroCommission",
        slippage_model="PFOF",
        slippage_params={"adverse_bps": "0"},
        settlement_days=1,
    )
    sim = Simulator(provider_config=provider_cfg, config=SimulatorConfig(min_order_delay_bars=0, initial_capital=Decimal("0")))

    t0 = datetime(2024, 1, 1, 9, 30, tzinfo=timezone.utc)
    # seed a long position to sell
    from liq.sim.accounting import PositionRecord, PositionLot
    sim.account_state.positions["AAPL"] = PositionRecord(
        lots=[PositionLot(quantity=Decimal("1"), entry_price=Decimal("10"), entry_time=t0)]
    )
    orders = [make_order(t0, side="sell", qty="1")]
    bars = [
        make_bar(t0, "10", "11", "9", "10"),
        make_bar(t0 + timedelta(days=1), "10", "11", "9", "10"),
    ]

    result = sim.run(orders, bars)
    assert len(result.fills) == 1
    # unsettled proceeds reflected in equity immediately (cash + unsettled)
    assert result.portfolio_history[0] == Decimal("10")
    assert result.portfolio_history[1] == Decimal("10")
