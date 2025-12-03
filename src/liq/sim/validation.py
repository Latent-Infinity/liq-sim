"""Order eligibility and bias checks."""

from datetime import datetime

from liq.sim.exceptions import IneligibleOrderError, LookAheadBiasError


def is_order_eligible(order_bar_index: int, current_bar_index: int, min_delay_bars: int = 1) -> bool:
    """Return True if the order generated at order_bar_index can execute at current_bar_index."""
    if min_delay_bars < 0:
        raise ValueError("min_delay_bars must be >= 0")
    return current_bar_index - order_bar_index >= min_delay_bars


def assert_no_lookahead(order_timestamp: datetime, current_bar_timestamp: datetime) -> None:
    """Raise when an order timestamp implies using future information."""
    if order_timestamp > current_bar_timestamp:
        raise LookAheadBiasError("order timestamp is after current bar timestamp")


def ensure_order_eligible(
    order_bar_index: int,
    current_bar_index: int,
    min_delay_bars: int = 1,
) -> None:
    """Validate order eligibility, raising an error if not eligible."""
    if not is_order_eligible(order_bar_index, current_bar_index, min_delay_bars):
        raise IneligibleOrderError(
            f"Order at bar {order_bar_index} not eligible until "
            f"{order_bar_index + min_delay_bars}; current bar is {current_bar_index}"
        )
