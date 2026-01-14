from liq.sim.fx_eval import summarize_fx_performance, turnover_from_positions


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
