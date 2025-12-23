from datetime import UTC, datetime
from decimal import Decimal

import polars as pl
import pytest
from liq.core import Bar, OrderRequest, OrderSide, OrderType

from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator


def simple_provider() -> ProviderConfig:
    return ProviderConfig(
        name="test",
        asset_classes=["crypto"],
        fee_model="ZeroCommission",
        slippage_model="VolumeWeighted",
        account_currency="USD",
    )


def bar(ts: datetime, price: float) -> Bar:
    return Bar(
        symbol="BTC_USDT",
        timestamp=ts,
        open=Decimal(str(price)),
        high=Decimal(str(price)),
        low=Decimal(str(price)),
        close=Decimal(str(price)),
        volume=Decimal("1"),
    )


def market_buy(ts: datetime, qty: float) -> OrderRequest:
    return OrderRequest(
        symbol="BTC_USDT",
        quantity=Decimal(str(qty)),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        timestamp=ts,
    )


def test_funding_and_slippage_reporting() -> None:
    cfg = SimulatorConfig()
    cfg.funding.enabled = True
    cfg.funding.scenario = "base"
    sim = Simulator(provider_config=simple_provider(), config=cfg)
    now = datetime(2024, 1, 1, tzinfo=UTC)
    orders = [market_buy(now, 1)]
    bars = [bar(now, 10), bar(now.replace(minute=1), 10)]
    result = sim.run(orders, bars)
    assert result.funding_charged >= 0
    assert "p50" in result.slippage_stats


def test_risk_caps_reject_when_frequency_exceeded() -> None:
    cfg = SimulatorConfig()
    cfg.min_order_delay_bars = 0
    cfg.risk_caps.frequency_cap_per_day = 0
    sim = Simulator(provider_config=simple_provider(), config=cfg)
    now = datetime(2024, 1, 1, tzinfo=UTC)
    orders = [market_buy(now, 1)]
    bars = [bar(now, 10)]
    result = sim.run(orders, bars)
    assert result.rejected_orders, "Order should be rejected due to frequency cap"


def test_risk_caps_equity_floor_blocks() -> None:
    cfg = SimulatorConfig(initial_capital=Decimal("100"))
    cfg.min_order_delay_bars = 0
    cfg.risk_caps.equity_floor_pct = 0.9
    sim = Simulator(provider_config=simple_provider(), config=cfg)
    sim.account_state.cash = Decimal("80")  # simulate drawdown below floor
    now = datetime(2024, 1, 1, tzinfo=UTC)
    orders = [market_buy(now, 1)]
    bars = [bar(now, 10)]
    result = sim.run(orders, bars)
    assert result.rejected_orders, "Order should be rejected due to equity floor"
