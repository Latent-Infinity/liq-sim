from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator
from liq.core import Bar, OrderRequest
from liq.core.enums import OrderSide, OrderType, TimeInForce


def make_order(timestamp: datetime, qty: str, price: str) -> OrderRequest:
    return OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        time_in_force=TimeInForce.DAY,
        timestamp=timestamp,
    )


def make_bar(ts: datetime, open_price: str) -> Bar:
    return Bar(
        symbol="AAPL",
        timestamp=ts,
        open=Decimal(open_price),
        high=Decimal(open_price),
        low=Decimal(open_price),
        close=Decimal(open_price),
        volume=Decimal("1000"),
    )


def test_position_limit_blocks_order() -> None:
    cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
    )
    sim = Simulator(provider_config=cfg, config=SimulatorConfig(max_position_pct=0.1))
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    # order value 2000 vs equity 0 cash -> will raise due to non-positive equity
    orders = [make_order(t0, qty="20", price="100")]
    bars = [make_bar(t0, "100")]
    result = sim.run(orders, bars)
    assert len(result.fills) == 0
