from liq.sim.funding_model import SCENARIOS, funding_charge, slippage_percentiles


def test_funding_charge_respects_scenario() -> None:
    base = funding_charge(1000, days=1, scenario="base")
    elevated = funding_charge(1000, days=1, scenario="elevated")
    assert elevated > base
    assert "base" in SCENARIOS


def test_slippage_percentiles_handles_empty() -> None:
    res = slippage_percentiles([], [50, 90])
    assert res == {"p50": 0.0, "p90": 0.0}


def test_slippage_percentiles_returns_values() -> None:
    res = slippage_percentiles([1, 2, 3, 4], [50, 75])
    assert res["p50"] == 2.5
