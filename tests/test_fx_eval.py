from liq.sim.fx_eval import (
    build_trace_payload,
    capacity_proxy,
    cvar_from_pnl,
    max_exposure,
    summarize_fx_performance,
    tail_stability,
    tail_stability_violations,
    turnover_from_positions,
)


def test_fx_performance_summary() -> None:
    equity = [100.0, 101.0, 99.0, 102.0]
    metrics = summarize_fx_performance(equity, periods_per_year=252)
    assert metrics["total_return"] == (102.0 / 100.0) - 1
    assert metrics["max_drawdown"] > 0


def test_fx_performance_short_series() -> None:
    metrics = summarize_fx_performance([100.0])
    assert metrics["sharpe"] == 0.0
    assert metrics["sortino"] == 0.0


def test_turnover_from_positions() -> None:
    turnover = turnover_from_positions([0.0, 1.0, -1.0])
    assert turnover == 1.5
    assert turnover_from_positions([1.0]) == 0.0


def test_cvar_from_pnl_tail() -> None:
    pnl = [1.0, -2.0, -4.0, 3.0, -1.0, 5.0]
    assert cvar_from_pnl(pnl, alpha=0.9) == 4.0


def test_tail_stability_and_capacity_metrics() -> None:
    positions = [0.0, 0.1, -0.2, 0.3, -0.1]
    equity = [10000.0, 9900.0, 9950.0, 10050.0, 10100.0]
    expected_max = max(
        abs(pos) / eq
        for pos, eq in zip(positions, equity, strict=False)
        if eq > 0
    )
    expected_capacity = sum(
        abs(pos) / eq
        for pos, eq in zip(positions, equity, strict=False)
        if eq > 0
    ) / len(positions)

    assert max_exposure(positions, equity) == expected_max
    assert capacity_proxy(positions, equity) == expected_capacity

    stability = tail_stability([100.0, 101.0, 102.0, 103.0, 104.0], window=2)
    assert stability >= 0.0


def test_trace_payload_defaults_and_downsample() -> None:
    payload = build_trace_payload(signal=[1.0] * 2, max_length=4)
    assert payload["schema_version"] == "1.0"
    assert payload["signal_trace"]["length"] == 2
    assert payload["position_trace"]["values"] == [0.0]
    assert payload["pnl_trace"]["values"] == [0.0]


def test_tail_stability_violations_when_threshold_exceeded() -> None:
    assert tail_stability_violations(0.8, max_stability=0.2) == ["tail_stability_exceeded"]
    assert tail_stability_violations(0.1, max_stability=0.2) == []
