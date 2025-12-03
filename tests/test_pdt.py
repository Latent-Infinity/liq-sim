from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator
from liq.types import Bar, OrderRequest
from liq.types.enums import OrderSide, OrderType, TimeInForce


def make_order(timestamp: datetime, side: str, qty: str) -> OrderRequest:
    return OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side=side,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        time_in_force=TimeInForce.DAY,
        timestamp=timestamp,
    )


def make_bar(ts: datetime, price: str) -> Bar:
    return Bar(
        symbol="AAPL",
        timestamp=ts,
        open=Decimal(price),
        high=Decimal(price),
        low=Decimal(price),
        close=Decimal(price),
        volume=Decimal("1000"),
    )


def test_pdt_blocks_when_counter_zero() -> None:
    cfg = ProviderConfig(
        name="tradestation",
        asset_classes=["equity"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
        pdt_enabled=True,
    )
    sim = Simulator(
        provider_config=cfg,
        config=SimulatorConfig(min_order_delay_bars=0, initial_capital=Decimal("0")),
    )
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    sim.account_state.day_trades_remaining = 0
    # pre-existing long position lot
    from liq.sim.accounting import PositionRecord, PositionLot
    sim.account_state.positions["AAPL"] = PositionRecord(
        lots=[PositionLot(quantity=Decimal("1"), entry_price=Decimal("10"), entry_time=t0)]
    )
    orders = [make_order(t0, side="sell", qty="1")]
    bars = [make_bar(t0, "10")]

    result = sim.run(orders, bars)
    assert len(result.fills) == 0


def test_pdt_allows_and_decrements_when_available() -> None:
    cfg = ProviderConfig(
        name="tradestation",
        asset_classes=["equity"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
        pdt_enabled=True,
    )
    sim = Simulator(
        provider_config=cfg,
        config=SimulatorConfig(min_order_delay_bars=0, initial_capital=Decimal("0")),
    )
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    sim.account_state.day_trades_remaining = 1
    from liq.sim.accounting import PositionRecord, PositionLot
    sim.account_state.positions["AAPL"] = PositionRecord(
        lots=[PositionLot(quantity=Decimal("1"), entry_price=Decimal("10"), entry_time=t0)]
    )
    orders = [make_order(t0, side="sell", qty="1")]
    bars = [make_bar(t0, "10")]

    result = sim.run(orders, bars)
    assert len(result.fills) == 1
    assert sim.account_state.day_trades_remaining == 0
