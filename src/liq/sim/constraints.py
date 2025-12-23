"""Risk and constraint checks."""

from decimal import Decimal

from liq.core import OrderRequest, PortfolioState


class ConstraintViolation(Exception):
    """Raised when an order violates configured constraints."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def check_buying_power(
    order: OrderRequest,
    portfolio: PortfolioState,
    mark_price: Decimal,
) -> None:
    """Ensure order value does not exceed available cash + unsettled (for buys)."""
    side_val = getattr(order, "side", None)
    if side_val and str(side_val).lower().endswith("sell"):
        return
    order_value = order.quantity * mark_price
    available = portfolio.cash + portfolio.unsettled_cash
    if order_value > available:
        raise ConstraintViolation(
            f"Insufficient buying power: order value {order_value} exceeds available {available}"
        )


def check_margin(
    order: OrderRequest,
    portfolio: PortfolioState,
    mark_price: Decimal,
    initial_margin_rate: Decimal,
) -> None:
    """Basic margin check: order value * margin rate must be <= equity."""
    if str(order.side).lower().endswith("sell"):
        return
    equity = portfolio.equity if hasattr(portfolio, "equity") else portfolio.cash
    required = order.quantity * mark_price * initial_margin_rate
    if required > equity:
        raise ConstraintViolation(
            f"Margin requirement exceeds equity: required {required}, available equity {equity}"
        )


def check_short_permission(
    order: OrderRequest,
    portfolio: PortfolioState,
    short_enabled: bool,
    locate_required: bool = False,
) -> None:
    """Prevent creation of new shorts when not permitted."""
    if short_enabled:
        if locate_required and str(order.side).lower().endswith("sell"):
            pre_pos = portfolio.positions.get(order.symbol)
            pre_qty = getattr(pre_pos, "quantity", Decimal("0")) if pre_pos else Decimal("0")
            would_be_short = pre_qty - order.quantity < 0
            if would_be_short:
                metadata = getattr(order, "metadata", None) or {}
                locate_ok = bool(metadata.get("locate_available") or metadata.get("locate_borrowed"))
                if not locate_ok:
                    raise ConstraintViolation(
                        f"Locate required for short selling {order.symbol}: no locate_available or locate_borrowed in metadata"
                    )
        return
    side_val = str(order.side).lower()
    if side_val.endswith("sell"):
        # if we are already long, sell to flat is allowed; creating negative is not
        pre_pos = portfolio.positions.get(order.symbol)
        pre_qty = getattr(pre_pos, "quantity", Decimal("0")) if pre_pos else Decimal("0")
        if order.quantity > pre_qty:
            raise ConstraintViolation(
                f"Shorting not permitted: sell qty {order.quantity} exceeds position {pre_qty}"
            )


def check_position_limit(
    order: OrderRequest,
    portfolio: PortfolioState,
    max_position_pct: float,
    mark_price: Decimal,
) -> None:
    """Ensure post-trade position value does not exceed max_position_pct of equity."""
    side_val = getattr(order, "side", None)
    if side_val and str(side_val).lower().endswith("sell"):
        # Allow sells/position reductions without limit check
        return
    equity = portfolio.equity if hasattr(portfolio, "equity") else portfolio.cash
    if equity <= 0:
        raise ConstraintViolation(f"Cannot trade with non-positive equity: {equity}")
    target_value = order.quantity * mark_price
    max_value = Decimal(str(max_position_pct)) * equity
    # crude additive check ignoring existing position direction; refined logic can consider net
    if target_value > max_value:
        raise ConstraintViolation(
            f"Position limit exceeded: order value {target_value} exceeds max {max_value} "
            f"({max_position_pct * 100:.1f}% of equity {equity})"
        )


def check_gross_leverage(
    order: OrderRequest,
    portfolio: PortfolioState,
    mark_price: Decimal,
    max_gross_leverage: float,
) -> None:
    """Ensure projected gross exposure does not exceed leverage cap."""
    equity = portfolio.equity if hasattr(portfolio, "equity") else portfolio.cash
    if equity <= 0:
        raise ConstraintViolation(f"Cannot trade with non-positive equity: {equity}")
    gross = sum((abs(p.market_value) for p in portfolio.positions.values()), Decimal("0"))
    order_value = order.quantity * mark_price
    projected_gross = gross
    side_val = str(order.side).lower()
    if side_val.endswith("buy") or side_val.endswith("sell"):
        projected_gross += order_value
    cap = Decimal(str(max_gross_leverage)) * equity
    if projected_gross > cap:
        raise ConstraintViolation(
            f"Gross leverage exceeded: projected {projected_gross} > cap {cap} "
            f"({max_gross_leverage}x equity {equity})"
        )


def check_pdt(
    portfolio: PortfolioState,
    is_day_trade: bool,
) -> None:
    """Enforce Pattern Day Trader limits using PortfolioState.day_trades_remaining."""
    remaining = getattr(portfolio, "day_trades_remaining", None)
    if remaining is None:
        return
    if is_day_trade and remaining <= 0:
        raise ConstraintViolation(
            f"PDT limit exceeded: {remaining} day trades remaining, order would create a day trade"
        )


def check_kill_switch(
    kill_switch_engaged: bool,
    order: OrderRequest,
) -> None:
    """Block exposure-increasing orders when kill-switch is engaged."""
    if kill_switch_engaged and str(order.side).lower().endswith("buy"):
        raise ConstraintViolation("Kill switch engaged; exposure-increasing orders blocked")
