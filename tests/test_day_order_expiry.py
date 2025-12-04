from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator
from liq.core import Bar, OrderRequest
from liq.core.enums import OrderSide, OrderType, TimeInForce


def make_day_order(ts: datetime, price: str) -> OrderRequest:
    return OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        limit_price=Decimal(price),
        time_in_force=TimeInForce.DAY,
        timestamp=ts,
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


def test_day_order_expires_after_bar() -> None:
    cfg = ProviderConfig(
        name="coinbase",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        slippage_params={"base_bps": "0", "volume_impact": "0"},
    )
    sim = Simulator(provider_config=cfg, config=SimulatorConfig(min_order_delay_bars=0))

    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    orders = [make_day_order(t0, price="100")]
    bars = [
        make_bar(t0, "90"),  # should fill (limit buy)
        make_bar(t0 + timedelta(minutes=1), "110"),  # no residual orders
    ]

    result = sim.run(orders, bars)
    assert len(result.fills) == 1
    # ensure no pending orders carried into next bar; portfolio history length should match bars
    assert len(result.portfolio_history) == 2
