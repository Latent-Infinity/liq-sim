from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator
from liq.types import Bar, OrderRequest
from liq.types.enums import OrderSide, OrderType, TimeInForce


def make_order(ts: datetime, qty: str, price: str) -> OrderRequest:
    return OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        time_in_force=TimeInForce.DAY,
        timestamp=ts,
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


def test_buying_power_blocks_when_insufficient() -> None:
    cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
    )
    sim = Simulator(provider_config=cfg, config=SimulatorConfig(min_order_delay_bars=0, initial_capital=Decimal("0")))
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    orders = [make_order(t0, qty="2", price="100")]
    bars = [make_bar(t0, "100")]

    result = sim.run(orders, bars)
    assert len(result.fills) == 0
