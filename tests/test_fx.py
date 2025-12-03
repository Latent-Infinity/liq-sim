from decimal import Decimal

import pytest

from liq.sim.fx import convert_to_usd


def test_convert_quote_usd_returns_identity() -> None:
    assert convert_to_usd(Decimal("10"), "EUR_USD", {"EUR_USD": Decimal("1.1")}) == Decimal("10")


def test_convert_base_usd_divides() -> None:
    result = convert_to_usd(Decimal("1000"), "USD_JPY", {"USD_JPY": Decimal("150")})
    assert result == Decimal("1000") / Decimal("150")


def test_convert_cross_uses_usd_pair() -> None:
    result = convert_to_usd(Decimal("1000"), "EUR_JPY", {"USD_JPY": Decimal("150")})
    assert result == Decimal("1000") / Decimal("150")


def test_convert_missing_rate_errors() -> None:
    with pytest.raises(KeyError):
        convert_to_usd(Decimal("10"), "EUR_JPY", {})


def test_convert_missing_rate_base_usd_errors() -> None:
    with pytest.raises(KeyError):
        convert_to_usd(Decimal("10"), "USD_JPY", {})


def test_convert_non_fx_pair_noop() -> None:
    result = convert_to_usd(Decimal("50"), "AAPL", {"USD_JPY": Decimal("150")})
    assert result == Decimal("50")
