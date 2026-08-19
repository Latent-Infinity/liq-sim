"""Trading metric utilities and trace extraction helpers for evaluator pipelines."""

from __future__ import annotations

import math
from collections.abc import Iterable

TRACE_SCHEMA_VERSION = "1.0"
DEFAULT_MAX_TRACE_LENGTH = 512


def summarize_fx_performance(
    equity_curve: Iterable[float],
    periods_per_year: int = 252,
) -> dict[str, float]:
    """Summarize performance metrics from an equity trace.

    Args:
        equity_curve: Iterable of equity values over time.
        periods_per_year: Periods per year for annualization (default 252).

    Returns:
        Dictionary with total return, sharpe, sortino, and max drawdown.
    """
    equity = list(_to_floats(equity_curve))
    if len(equity) < 2:
        return {
            "total_return": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_drawdown": 0.0,
        }

    returns = _pct_returns(equity)
    total_return = (equity[-1] / equity[0]) - 1 if equity[0] != 0 else 0.0
    sharpe = _annualized_sharpe(returns, periods_per_year)
    sortino = _annualized_sortino(returns, periods_per_year)
    max_dd = _max_drawdown(equity)

    return {
        "total_return": total_return,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
    }


def turnover_from_positions(
    positions: Iterable[float],
) -> float:
    """Compute turnover as average absolute change in position size."""
    pos = _to_floats(positions)
    if len(pos) < 2:
        return 0.0
    deltas = [abs(curr - prev) for prev, curr in zip(pos, pos[1:], strict=False)]
    return sum(deltas) / len(deltas)


def cvar_from_pnl(pnl_trace: Iterable[float], alpha: float = 0.95) -> float:
    """Compute CVaR on the downside P&L tail.

    The function is pure, deterministic, and bounded to finite values.
    """
    if alpha <= 0 or alpha >= 1:
        raise ValueError("alpha must be in (0, 1)")
    values = _to_floats(pnl_trace)
    if not values:
        return 0.0
    sorted_values = sorted(values)
    tail_count = max(1, math.ceil(len(sorted_values) * (1 - alpha)))
    tail = sorted_values[:tail_count]
    return max(0.0, -sum(tail) / len(tail))


def max_exposure(
    position_trace: Iterable[float],
    equity_trace: Iterable[float] | None = None,
) -> float:
    """Compute maximum exposure from position and optional equity traces."""
    positions = _to_floats(position_trace)
    if not positions:
        return 0.0
    if equity_trace is None:
        return max(abs(v) for v in positions)

    equities = _to_floats(equity_trace)
    if not equities:
        return 0.0

    values: list[float] = []
    for pos, eq in zip(positions, equities, strict=False):
        if eq <= 0:
            continue
        values.append(abs(pos) / eq)
    if not values:
        return 0.0
    return max(values)


def tail_stability(
    pnl_trace: Iterable[float],
    window: int = 20,
    periods_per_year: int = 252,
) -> float:
    """Rolling Sharpe variance (instruments regime instability proxy)."""
    pnl = _to_floats(pnl_trace)
    if window <= 0 or len(pnl) < 2:
        return 0.0
    returns = _pct_returns(pnl)
    if len(returns) < window:
        return 0.0

    sharpe_values = []
    for start in range(0, len(returns) - window + 1):
        window_returns = returns[start : start + window]
        sharpe_values.append(_annualized_sharpe(window_returns, periods_per_year))
    return _stddev(sharpe_values)


def capacity_proxy(
    position_trace: Iterable[float],
    equity_trace: Iterable[float] | None = None,
) -> float:
    """Estimate capacity stress from position utilization.

    Returns:
        The average gross exposure ratio when equity is provided; otherwise
        average absolute position size.
    """
    positions = _to_floats(position_trace)
    if not positions:
        return 0.0
    if equity_trace is None:
        return sum(abs(v) for v in positions) / len(positions)

    equities = _to_floats(equity_trace)
    if not equities:
        return 0.0
    values: list[float] = []
    for pos, eq in zip(positions, equities, strict=False):
        if eq <= 0:
            continue
        values.append(abs(pos) / eq)
    if not values:
        return 0.0
    return sum(values) / len(values)


def signal_trace(
    values: Iterable[float] | None,
    *,
    max_length: int = DEFAULT_MAX_TRACE_LENGTH,
) -> dict[str, object]:
    """Serialize signal trace with bounded length and stable fallback."""
    return _serialize_trace("signal", values, max_length=max_length)


def position_trace(
    values: Iterable[float] | None,
    *,
    max_length: int = DEFAULT_MAX_TRACE_LENGTH,
) -> dict[str, object]:
    """Serialize position trace with bounded length and stable fallback."""
    return _serialize_trace("position", values, max_length=max_length)


def pnl_trace(
    values: Iterable[float] | None,
    *,
    max_length: int = DEFAULT_MAX_TRACE_LENGTH,
) -> dict[str, object]:
    """Serialize P&L trace with bounded length and stable fallback."""
    return _serialize_trace("pnl", values, max_length=max_length)


def build_trace_payload(
    *,
    signal: Iterable[float] | None = None,
    position: Iterable[float] | None = None,
    pnl: Iterable[float] | None = None,
    max_length: int = DEFAULT_MAX_TRACE_LENGTH,
) -> dict[str, object]:
    """Build a versioned payload for evaluator/semantic operator usage."""
    return {
        "schema_version": TRACE_SCHEMA_VERSION,
        "signal_trace": signal_trace(signal, max_length=max_length),
        "position_trace": position_trace(position, max_length=max_length),
        "pnl_trace": pnl_trace(pnl, max_length=max_length),
    }


def tail_stability_violations(
    tail_stability_value: float,
    max_stability: float,
) -> list[str]:
    """Emit violation strings when tail stability exceeds a threshold."""
    if max_stability < 0:
        raise ValueError("max_stability must be non-negative")
    if tail_stability_value > max_stability:
        return ["tail_stability_exceeded"]
    return []


def _serialize_trace(
    kind: str, values: Iterable[float] | None, *, max_length: int
) -> dict[str, object]:
    if max_length <= 0:
        raise ValueError("max_length must be positive")
    data = _safe_downsample(_to_floats(values), max_length=max_length)
    if not data:
        data = [0.0]
    return {
        "kind": kind,
        "version": TRACE_SCHEMA_VERSION,
        "length": len(data),
        "values": data,
    }


def _safe_downsample(values: list[float], *, max_length: int) -> list[float]:
    if len(values) <= max_length:
        return values
    if max_length == 1:
        return [values[-1]]
    step = (len(values) - 1) / (max_length - 1)
    return [values[int(i * step)] for i in range(max_length)]


def _to_floats(values: Iterable[float] | None) -> list[float]:
    if values is None:
        return []
    out: list[float] = []
    for value in values:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            out.append(parsed)
        else:
            out.append(0.0)
    return out


def _pct_returns(equity: list[float]) -> list[float]:
    returns = []
    for prev, curr in zip(equity, equity[1:], strict=False):
        if prev == 0:
            returns.append(0.0)
        else:
            returns.append((curr / prev) - 1)
    return returns


def _annualized_sharpe(returns: list[float], periods_per_year: int) -> float:
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def _annualized_sortino(returns: list[float], periods_per_year: int) -> float:
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    downside = [min(0.0, r) for r in returns]
    downside_var = sum(r**2 for r in downside) / len(returns)
    downside_std = math.sqrt(downside_var)
    if downside_std == 0:
        return 0.0
    return (mean / downside_std) * math.sqrt(periods_per_year)


def _max_drawdown(equity: list[float]) -> float:
    peak = equity[0]
    max_dd = 0.0
    for value in equity:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak != 0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown
    return max_dd


def _stddev(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)
