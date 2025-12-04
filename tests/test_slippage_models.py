from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from liq.sim.models.slippage import PFOFSlippage, VolumeWeightedSlippage
from liq.sim.models.spread import SpreadBasedSlippage
from liq.core import Bar, OrderRequest
from liq.core.enums import OrderSide, OrderType, TimeInForce


def make_order(qty: str) -> OrderRequest:
    return OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        time_in_force=TimeInForce.DAY,
        timestamp=datetime.now(timezone.utc),
    )


def make_bar(open_price: str, high: str, low: str, close: str, volume: str) -> Bar:
    return Bar(
        symbol="AAPL",
        timestamp=datetime.now(timezone.utc),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(volume),
    )


def test_volume_weighted_slippage_scales_with_participation() -> None:
    model = VolumeWeightedSlippage(base_bps=Decimal("2"), volume_impact=Decimal("50"))
    order = make_order("10")
    bar = make_bar("100", "105", "95", "102", "100")

    slippage = model.calculate(order, bar)
    # participation = 10/100 = 0.1, slippage_bps = 2 + 50*0.1 = 7
    expected = bar.midrange * Decimal("7") / Decimal("10000")
    assert slippage == expected


def test_pfof_slippage_adverse_bps() -> None:
    model = PFOFSlippage(adverse_bps=Decimal("20"))
    order = make_order("1")
    bar = make_bar("100", "110", "90", "105", "100")
    slippage = model.calculate(order, bar)
    expected = bar.midrange * Decimal("20") / Decimal("10000")
    assert slippage == expected


def test_volume_weighted_zero_volume_uses_base_only() -> None:
    model = VolumeWeightedSlippage(base_bps=Decimal("5"), volume_impact=Decimal("100"))
    order = make_order("10")
    bar = make_bar("100", "101", "99", "100", "0")
    slippage = model.calculate(order, bar)
    expected = bar.midrange * Decimal("5") / Decimal("10000")
    assert slippage == expected


def test_spread_based_slippage_uses_bar_spread() -> None:
    model = SpreadBasedSlippage()
    bar = make_bar("100", "102", "98", "101", "1000")
    order = make_order("1")
    slippage = model.calculate(order, bar)
    assert slippage == Decimal("2")  # half the spread so buy +2 / sell -2 = full spread width


def test_spread_based_slippage_prefers_explicit_spread() -> None:
    model = SpreadBasedSlippage()
    bar = SimpleNamespace(spread=Decimal("0.8"), high=Decimal("0"), low=Decimal("0"))
    order = make_order("1")
    slippage = model.calculate(order, bar)
    assert slippage == Decimal("0.4")
