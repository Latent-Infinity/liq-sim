"""Protocol and interface definitions for extensible simulation components.

These are placeholders for upcoming implementations and are intentionally
interface-only in Phase 0.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, Sequence

import polars as pl


class CalibrationStrategy(ABC):
    """Per-fold calibration for model scores (e.g., temperature or Platt)."""

    @abstractmethod
    def calibrate(self, scores: pl.Series, labels: pl.Series) -> dict:
        """Return calibrated scores and params; to be implemented."""
        raise NotImplementedError  # pragma: no cover


class EVThresholdSelector(ABC):
    """Expected value thresholding with constraints on precision/recall/trades."""

    @abstractmethod
    def select(self, scores: pl.Series, labels: pl.Series) -> dict:
        """Return chosen threshold and diagnostics; to be implemented."""
        raise NotImplementedError  # pragma: no cover


class FundingModel(Protocol):
    """Funding model that returns a rate or charge over a time window."""

    def charge(self, notional: float, start_ts: int, end_ts: int) -> float:  # pragma: no cover - protocol
        """Compute funding charge for a window."""
        ...


class SlippageReporter(Protocol):
    """Report slippage percentiles over a window."""

    def summarize(self, samples: Sequence[float]) -> dict:  # pragma: no cover - protocol
        """Return percentile summaries."""
        ...


class RiskCapPolicy(Protocol):
    """Risk caps sourced from liq-risk (net, pyramiding, equity floor, frequency)."""

    def allow_order(self, order: object, portfolio: object) -> bool:  # pragma: no cover - protocol
        """Return whether the order is permitted under risk caps."""
        ...
