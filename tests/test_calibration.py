import polars as pl

from liq.sim.calibration import CalibrationResult, ev_threshold_search, temperature_scale


def test_temperature_scale_returns_params() -> None:
    scores = pl.Series([0.1, 0.5, 0.9])
    labels = pl.Series([0, 1, 1])
    res = temperature_scale(scores, labels)
    assert isinstance(res, CalibrationResult)
    assert "temperature" in res.params
    assert res.scores.len() == scores.len()


def test_ev_threshold_search_respects_constraints() -> None:
    scores = pl.Series([0.9, 0.8, 0.2, 0.1])
    labels = pl.Series([1, 1, 0, 0])
    diag = ev_threshold_search(scores, labels, min_precision=0.5, min_recall=0.5, min_trades=1)
    assert diag.constraints_satisfied is True
    assert 0 < diag.threshold < 1


def test_ev_threshold_search_handles_empty() -> None:
    diag = ev_threshold_search(pl.Series([], dtype=pl.Float64), pl.Series([], dtype=pl.Int64))
    assert diag.constraints_satisfied is False
