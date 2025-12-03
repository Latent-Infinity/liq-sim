"""Execution simulation package for the LIQ Stack."""

__all__ = [
    "SimulatorConfig",
    "ProviderConfig",
    "LookAheadBiasError",
    "SimulationCheckpoint",
    "SimulationResult",
    "Simulator",
    "is_order_eligible",
    "assert_no_lookahead",
    "match_order",
    "TieredMakerTakerFee",
    "ZeroCommissionFee",
    "VolumeWeightedSlippage",
    "PFOFSlippage",
]

from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.execution import match_order
from liq.sim.exceptions import LookAheadBiasError
from liq.sim.checkpoint import SimulationCheckpoint
from liq.sim.simulator import SimulationResult, Simulator
from liq.sim.models.fee import TieredMakerTakerFee, ZeroCommissionFee
from liq.sim.models.slippage import PFOFSlippage, VolumeWeightedSlippage
from liq.sim.validation import assert_no_lookahead, is_order_eligible

__version__ = "0.1.0"
