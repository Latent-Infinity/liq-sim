from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from liq.sim.constraints import ConstraintViolation, check_kill_switch
from liq.core import OrderRequest
from liq.core.enums import OrderSide, OrderType, TimeInForce


def make_order(side: str) -> OrderRequest:
    return OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side=OrderSide(side),
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        time_in_force=TimeInForce.DAY,
        timestamp=datetime.now(timezone.utc),
    )


def test_kill_switch_blocks_buys() -> None:
    order = make_order("buy")
    with pytest.raises(ConstraintViolation):
        check_kill_switch(True, order)


def test_kill_switch_allows_sells() -> None:
    order = make_order("sell")
    check_kill_switch(True, order)
