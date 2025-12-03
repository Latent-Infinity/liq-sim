from decimal import Decimal
from uuid import uuid4

from datetime import datetime, timezone
from liq.sim.models.fee import TieredMakerTakerFee, ZeroCommissionFee
from liq.types import OrderRequest
from liq.types.enums import OrderSide, OrderType, TimeInForce


def make_order(
    price: str,
    qty: str,
    order_type: OrderType = OrderType.MARKET,
    limit: str | None = None,
) -> OrderRequest:
    return OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=order_type,
        quantity=Decimal(qty),
        limit_price=Decimal(limit) if limit else (Decimal(price) if order_type == OrderType.LIMIT else None),
        stop_price=None,
        time_in_force=TimeInForce.DAY,
        timestamp=datetime.now(timezone.utc),
    )


def test_tiered_maker_fee() -> None:
    model = TieredMakerTakerFee(maker_bps=Decimal("10"), taker_bps=Decimal("20"))
    order = make_order("100", "1", OrderType.LIMIT, limit="100")
    fee = model.calculate(order, fill_price=Decimal("100"), is_maker=True)
    assert fee == Decimal("0.10")  # 1*100*10bps/10000


def test_tiered_taker_fee() -> None:
    model = TieredMakerTakerFee(maker_bps=Decimal("10"), taker_bps=Decimal("20"))
    order = make_order("100", "2", OrderType.MARKET)
    fee = model.calculate(order, fill_price=Decimal("50"), is_maker=False)
    assert fee == Decimal("0.20")  # 2*50*20bps/10000


def test_zero_commission_fee() -> None:
    model = ZeroCommissionFee()
    order = make_order("100", "5", OrderType.MARKET)
    fee = model.calculate(order, fill_price=Decimal("10"), is_maker=False)
    assert fee == Decimal("0")
