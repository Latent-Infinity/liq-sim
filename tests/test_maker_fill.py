"""Traded-through maker-fill policy and maker-fill diagnostics.

A resting maker limit should fill only when price trades *through* it, not on a
mere touch (a touch does not guarantee a passive fill given queue priority).
The default policy stays TOUCH so existing consumers are unchanged; opt-in
TRADED_THROUGH tightens the fill condition, and ``classify_limit_fill`` reports
the maker-fill quality (missed / touched / traded-through / adverse selection).
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from liq.core import Bar, OrderRequest
from liq.core.enums import OrderSide, OrderType, TimeInForce

from liq.sim.execution import (
    FillPolicy,
    MakerFillOutcome,
    classify_limit_fill,
    match_order,
)


def make_order(*, side: OrderSide, limit: str, qty: str = "1") -> OrderRequest:
    return OrderRequest(
        client_order_id=uuid4(),
        symbol="AAPL",
        side=side,
        order_type=OrderType.LIMIT,
        quantity=Decimal(qty),
        limit_price=Decimal(limit),
        time_in_force=TimeInForce.DAY,
        timestamp=datetime.now(UTC),
    )


def make_bar(open_price: str, high: str, low: str, close: str) -> Bar:
    return Bar(
        symbol="AAPL",
        timestamp=datetime.now(UTC),
        open=Decimal(open_price),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1000"),
    )


class TestTouchPolicyUnchanged:
    """The default policy must reproduce the pre-existing touch behavior."""

    def test_buy_fills_on_touch_by_default(self) -> None:
        order = make_order(side=OrderSide.BUY, limit="100")
        bar = make_bar("101", "102", "100", "101")  # low == limit, exact touch
        assert match_order(order, bar) is not None

    def test_sell_fills_on_touch_by_default(self) -> None:
        order = make_order(side=OrderSide.SELL, limit="100")
        bar = make_bar("99", "100", "98", "99")  # high == limit
        assert match_order(order, bar) is not None


class TestTradedThroughPolicy:
    def test_buy_touch_does_not_fill(self) -> None:
        order = make_order(side=OrderSide.BUY, limit="100")
        bar = make_bar("101", "102", "100", "101")  # only touches
        assert match_order(order, bar, fill_policy=FillPolicy.TRADED_THROUGH) is None

    def test_buy_through_fills(self) -> None:
        order = make_order(side=OrderSide.BUY, limit="100")
        bar = make_bar("101", "102", "99", "100.5")  # low < limit
        fill = match_order(order, bar, fill_policy=FillPolicy.TRADED_THROUGH)
        assert fill is not None
        assert fill.price == Decimal("100")  # open above limit -> fill at limit

    def test_sell_touch_does_not_fill(self) -> None:
        order = make_order(side=OrderSide.SELL, limit="100")
        bar = make_bar("99", "100", "98", "99")  # only touches
        assert match_order(order, bar, fill_policy=FillPolicy.TRADED_THROUGH) is None

    def test_sell_through_fills(self) -> None:
        order = make_order(side=OrderSide.SELL, limit="100")
        bar = make_bar("99", "101", "98", "99.5")  # high > limit
        fill = match_order(order, bar, fill_policy=FillPolicy.TRADED_THROUGH)
        assert fill is not None
        assert fill.price == Decimal("100")

    def test_gap_price_benefit_preserved_through(self) -> None:
        # gap down below limit -> filled at the better (open) price, still a through
        order = make_order(side=OrderSide.BUY, limit="100")
        bar = make_bar("95", "97", "90", "96")
        fill = match_order(order, bar, fill_policy=FillPolicy.TRADED_THROUGH)
        assert fill is not None
        assert fill.price == Decimal("95")


class TestClassifyLimitFill:
    def test_buy_missed(self) -> None:
        bar = make_bar("101", "103", "100.5", "102")
        assert classify_limit_fill(OrderSide.BUY, Decimal("100"), bar) == MakerFillOutcome.MISSED

    def test_buy_touched(self) -> None:
        bar = make_bar("101", "102", "100", "101")
        assert classify_limit_fill(OrderSide.BUY, Decimal("100"), bar) == MakerFillOutcome.TOUCHED

    def test_buy_traded_through(self) -> None:
        bar = make_bar("101", "102", "99", "100.5")  # penetrates, closes back above limit
        assert (
            classify_limit_fill(OrderSide.BUY, Decimal("100"), bar)
            == MakerFillOutcome.TRADED_THROUGH
        )

    def test_buy_adverse_selection(self) -> None:
        bar = make_bar("101", "102", "97", "98")  # penetrates and closes well below limit
        assert (
            classify_limit_fill(OrderSide.BUY, Decimal("100"), bar, adverse_margin=Decimal("1"))
            == MakerFillOutcome.ADVERSE
        )

    def test_sell_missed(self) -> None:
        bar = make_bar("98", "99.5", "97", "98")
        assert classify_limit_fill(OrderSide.SELL, Decimal("100"), bar) == MakerFillOutcome.MISSED

    def test_sell_touched(self) -> None:
        bar = make_bar("99", "100", "98", "99")
        assert classify_limit_fill(OrderSide.SELL, Decimal("100"), bar) == MakerFillOutcome.TOUCHED

    def test_sell_traded_through(self) -> None:
        bar = make_bar("99", "101", "98", "99.5")
        assert (
            classify_limit_fill(OrderSide.SELL, Decimal("100"), bar)
            == MakerFillOutcome.TRADED_THROUGH
        )

    def test_sell_adverse_selection(self) -> None:
        bar = make_bar("99", "103", "98", "102")
        assert (
            classify_limit_fill(OrderSide.SELL, Decimal("100"), bar, adverse_margin=Decimal("1"))
            == MakerFillOutcome.ADVERSE
        )

    def test_buy_close_below_limit_is_adverse_by_default(self) -> None:
        # penetrates then closes below the limit; with default margin 0 any close
        # beyond the limit against the maker is adverse selection.
        bar = make_bar("101", "102", "99", "99.5")
        assert classify_limit_fill(OrderSide.BUY, Decimal("100"), bar) == MakerFillOutcome.ADVERSE

    def test_buy_through_within_margin_not_adverse(self) -> None:
        # closes just below the limit but within the adverse margin -> a clean through
        bar = make_bar("101", "102", "99", "99.5")
        assert (
            classify_limit_fill(OrderSide.BUY, Decimal("100"), bar, adverse_margin=Decimal("1"))
            == MakerFillOutcome.TRADED_THROUGH
        )
