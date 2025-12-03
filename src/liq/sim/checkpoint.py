"""Checkpoint utilities for deterministic restart."""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from random import getstate as _get_random_state, setstate as _set_random_state
from typing import Any

from liq.sim.accounting import AccountState
from liq.sim.brackets import BracketState
from liq.sim.config import ProviderConfig, SimulatorConfig


@dataclass
class SimulationCheckpoint:
    """Serializable snapshot of simulator state."""

    backtest_id: str
    config_hash: str
    provider_config: ProviderConfig
    simulator_config: SimulatorConfig
    account_state: AccountState
    current_day: Any
    peak_equity: Any
    daily_start_equity: Any
    kill_switch_engaged: bool
    active_brackets: list[BracketState]
    random_state: Any

    def save(self, path: Path) -> None:
        """Persist checkpoint to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def load(path: Path, expected_config_hash: str | None = None) -> "SimulationCheckpoint":
        """Load checkpoint and optionally validate config hash."""
        with path.open("rb") as f:
            chk = pickle.load(f)
        if expected_config_hash is not None and chk.config_hash != expected_config_hash:
            raise ValueError("Config hash mismatch for checkpoint")
        return chk

    def restore_random_state(self) -> None:
        """Restore RNG state for deterministic continuation."""
        _set_random_state(self.random_state)


def create_checkpoint(
    *,
    backtest_id: str,
    config_hash: str,
    provider_config: ProviderConfig,
    simulator_config: SimulatorConfig,
    account_state: AccountState,
    current_day,
    peak_equity,
    daily_start_equity,
    kill_switch_engaged: bool,
    active_brackets: list[BracketState],
) -> SimulationCheckpoint:
    """Build a checkpoint capturing simulator runtime state and RNG."""
    return SimulationCheckpoint(
        backtest_id=backtest_id,
        config_hash=config_hash,
        provider_config=provider_config,
        simulator_config=simulator_config,
        account_state=account_state,
        current_day=current_day,
        peak_equity=peak_equity,
        daily_start_equity=daily_start_equity,
        kill_switch_engaged=kill_switch_engaged,
        active_brackets=active_brackets,
        random_state=_get_random_state(),
    )
