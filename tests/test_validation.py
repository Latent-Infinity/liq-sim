from datetime import datetime, timezone

import pytest

from liq.sim.exceptions import IneligibleOrderError, LookAheadBiasError
from liq.sim.validation import assert_no_lookahead, ensure_order_eligible, is_order_eligible


def test_order_eligibility_delay() -> None:
    assert not is_order_eligible(order_bar_index=5, current_bar_index=5, min_delay_bars=1)
    assert is_order_eligible(order_bar_index=5, current_bar_index=6, min_delay_bars=1)


def test_order_eligibility_delay_zero_allowed() -> None:
    assert is_order_eligible(order_bar_index=5, current_bar_index=5, min_delay_bars=0)


def test_order_ineligible_raises() -> None:
    with pytest.raises(IneligibleOrderError):
        ensure_order_eligible(order_bar_index=5, current_bar_index=5, min_delay_bars=1)


def test_lookahead_rejected() -> None:
    order_ts = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
    bar_ts = datetime(2024, 1, 1, 9, 59, tzinfo=timezone.utc)
    with pytest.raises(LookAheadBiasError):
        assert_no_lookahead(order_ts, bar_ts)


def test_valid_timestamp_no_lookahead() -> None:
    order_ts = datetime(2024, 1, 1, 9, 59, tzinfo=timezone.utc)
    bar_ts = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert_no_lookahead(order_ts, bar_ts)


def test_negative_delay_rejected() -> None:
    with pytest.raises(ValueError):
        is_order_eligible(order_bar_index=1, current_bar_index=2, min_delay_bars=-1)
