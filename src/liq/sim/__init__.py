"""Execution simulation package for the LIQ Stack."""

__all__ = [
    "SimulatorConfig",
    "ProviderConfig",
    "LookAheadBiasError",
    "SimulationCheckpoint",
    "CheckpointFormatError",
    "SimulationResult",
    "RejectedOrder",
    "Simulator",
    "is_order_eligible",
    "assert_no_lookahead",
    "match_order",
    "TieredMakerTakerFee",
    "ZeroCommissionFee",
    "VolumeWeightedSlippage",
    "PFOFSlippage",
    "summarize_fx_performance",
    "turnover_from_positions",
    "cvar_from_pnl",
    "max_exposure",
    "tail_stability",
    "capacity_proxy",
    "signal_trace",
    "position_trace",
    "pnl_trace",
    "build_trace_payload",
    "tail_stability_violations",
]

from liq.sim.checkpoint import CheckpointFormatError, SimulationCheckpoint
from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.exceptions import LookAheadBiasError
from liq.sim.execution import match_order
from liq.sim.fx_eval import (
    build_trace_payload,
    capacity_proxy,
    cvar_from_pnl,
    max_exposure,
    pnl_trace,
    position_trace,
    signal_trace,
    summarize_fx_performance,
    tail_stability,
    tail_stability_violations,
    turnover_from_positions,
)
from liq.sim.models.fee import TieredMakerTakerFee, ZeroCommissionFee
from liq.sim.models.slippage import PFOFSlippage, VolumeWeightedSlippage
from liq.sim.simulator import RejectedOrder, SimulationResult, Simulator
from liq.sim.validation import assert_no_lookahead, is_order_eligible
