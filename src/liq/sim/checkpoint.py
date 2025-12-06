"""Checkpoint utilities for deterministic restart using msgspec/MessagePack."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from random import getstate as _get_random_state
from random import setstate as _set_random_state
from typing import Any

import msgspec

from liq.sim.accounting import AccountState, PositionLot, PositionRecord, SettlementEntry
from liq.sim.brackets import BracketState
from liq.sim.config import ProviderConfig, SimulatorConfig

logger = logging.getLogger(__name__)

# Schema version for checkpoint format migrations
CHECKPOINT_SCHEMA_VERSION = 1


class CheckpointFormatError(Exception):
    """Raised when checkpoint file format is invalid or corrupted."""

    pass


@dataclass
class SimulationCheckpoint:
    """Serializable snapshot of simulator state."""

    backtest_id: str
    config_hash: str
    provider_config: ProviderConfig
    simulator_config: SimulatorConfig
    account_state: AccountState
    current_day: datetime | None
    peak_equity: Decimal
    daily_start_equity: Decimal
    kill_switch_engaged: bool
    active_brackets: list[BracketState]
    random_state: tuple[Any, ...]
    schema_version: int = CHECKPOINT_SCHEMA_VERSION

    def save(self, path: Path) -> None:
        """Persist checkpoint to disk using MessagePack format.

        Args:
            path: Path to save checkpoint file (recommended extension: .msgpack)
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _checkpoint_to_dict(self)
        with path.open("wb") as f:
            f.write(msgspec.msgpack.encode(data))
        logger.info(
            "Checkpoint saved",
            extra={
                "path": str(path),
                "backtest_id": self.backtest_id,
                "config_hash": self.config_hash,
                "schema_version": self.schema_version,
            },
        )

    @staticmethod
    def load(path: Path, expected_config_hash: str | None = None) -> SimulationCheckpoint:
        """Load checkpoint from MessagePack file.

        Args:
            path: Path to checkpoint file
            expected_config_hash: Optional hash to validate config hasn't changed

        Returns:
            SimulationCheckpoint restored from file

        Raises:
            CheckpointFormatError: If file is corrupted, wrong format, or schema mismatch
            ValueError: If config hash doesn't match expected value
        """
        try:
            with path.open("rb") as f:
                raw_data = f.read()

            # Check for pickle format (legacy files)
            if raw_data[:2] == b"\x80\x04" or raw_data[:1] == b"\x80":
                raise CheckpointFormatError(
                    f"Checkpoint file '{path}' appears to be in legacy pickle format. "
                    "Please re-run the simulation to create a new checkpoint in msgpack format."
                )

            data = msgspec.msgpack.decode(raw_data)

            if not isinstance(data, dict):
                raise CheckpointFormatError(
                    f"Invalid checkpoint format: expected dict, got {type(data).__name__}"
                )

            # Validate schema version
            schema_version = data.get("schema_version", 0)
            if schema_version > CHECKPOINT_SCHEMA_VERSION:
                raise CheckpointFormatError(
                    f"Checkpoint schema version {schema_version} is newer than supported "
                    f"version {CHECKPOINT_SCHEMA_VERSION}. Please upgrade liq-sim."
                )

            chk = _dict_to_checkpoint(data)

        except msgspec.DecodeError as e:
            raise CheckpointFormatError(f"Failed to decode checkpoint file '{path}': {e}") from e

        if expected_config_hash is not None and chk.config_hash != expected_config_hash:
            logger.error(
                "Checkpoint config hash mismatch",
                extra={
                    "path": str(path),
                    "checkpoint_hash": chk.config_hash,
                    "expected_hash": expected_config_hash,
                },
            )
            raise ValueError(
                f"Config hash mismatch: checkpoint has '{chk.config_hash}', "
                f"expected '{expected_config_hash}'"
            )

        logger.info(
            "Checkpoint loaded",
            extra={
                "path": str(path),
                "backtest_id": chk.backtest_id,
                "config_hash": chk.config_hash,
                "schema_version": chk.schema_version,
            },
        )
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
    current_day: datetime | None,
    peak_equity: Decimal,
    daily_start_equity: Decimal,
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
        schema_version=CHECKPOINT_SCHEMA_VERSION,
    )


def _checkpoint_to_dict(chk: SimulationCheckpoint) -> dict[str, Any]:
    """Convert checkpoint to serializable dict."""
    return {
        "schema_version": chk.schema_version,
        "backtest_id": chk.backtest_id,
        "config_hash": chk.config_hash,
        "provider_config": chk.provider_config.model_dump(mode="json"),
        "simulator_config": chk.simulator_config.model_dump(mode="json"),
        "account_state": _account_state_to_dict(chk.account_state),
        "current_day": chk.current_day.isoformat() if chk.current_day else None,
        "peak_equity": str(chk.peak_equity),
        "daily_start_equity": str(chk.daily_start_equity),
        "kill_switch_engaged": chk.kill_switch_engaged,
        "active_brackets": [_bracket_to_dict(b) for b in chk.active_brackets],
        "random_state": _random_state_to_serializable(chk.random_state),
    }


def _dict_to_checkpoint(data: dict[str, Any]) -> SimulationCheckpoint:
    """Restore checkpoint from dict."""
    return SimulationCheckpoint(
        schema_version=data.get("schema_version", 1),
        backtest_id=data["backtest_id"],
        config_hash=data["config_hash"],
        provider_config=ProviderConfig(**data["provider_config"]),
        simulator_config=SimulatorConfig(**data["simulator_config"]),
        account_state=_dict_to_account_state(data["account_state"]),
        current_day=datetime.fromisoformat(data["current_day"]) if data["current_day"] else None,
        peak_equity=Decimal(data["peak_equity"]),
        daily_start_equity=Decimal(data["daily_start_equity"]),
        kill_switch_engaged=data["kill_switch_engaged"],
        active_brackets=[_dict_to_bracket(b) for b in data["active_brackets"]],
        random_state=_serializable_to_random_state(data["random_state"]),
    )


def _account_state_to_dict(state: AccountState) -> dict[str, Any]:
    """Serialize AccountState to dict."""
    return {
        "cash": str(state.cash),
        "unsettled_cash": str(state.unsettled_cash),
        "positions": {
            sym: _position_record_to_dict(rec)
            for sym, rec in state.positions.items()
        },
        "settlement_queue": [_settlement_entry_to_dict(e) for e in state.settlement_queue],
        "day_trades_remaining": state.day_trades_remaining,
        "account_currency": state.account_currency,
    }


def _dict_to_account_state(data: dict[str, Any]) -> AccountState:
    """Restore AccountState from dict."""
    state = AccountState(cash=Decimal(data["cash"]))
    state.unsettled_cash = Decimal(data["unsettled_cash"])
    state.positions = {
        sym: _dict_to_position_record(rec)
        for sym, rec in data["positions"].items()
    }
    state.settlement_queue = [_dict_to_settlement_entry(e) for e in data["settlement_queue"]]
    state.day_trades_remaining = data["day_trades_remaining"]
    state.account_currency = data["account_currency"]
    return state


def _position_record_to_dict(rec: PositionRecord) -> dict[str, Any]:
    """Serialize PositionRecord to dict."""
    return {
        "lots": [_position_lot_to_dict(lot) for lot in rec.lots],
        "realized_pnl": str(rec.realized_pnl),
    }


def _dict_to_position_record(data: dict[str, Any]) -> PositionRecord:
    """Restore PositionRecord from dict."""
    rec = PositionRecord()
    rec.lots = [_dict_to_position_lot(lot) for lot in data["lots"]]
    rec.realized_pnl = Decimal(data["realized_pnl"])
    return rec


def _position_lot_to_dict(lot: PositionLot) -> dict[str, Any]:
    """Serialize PositionLot to dict."""
    return {
        "quantity": str(lot.quantity),
        "entry_price": str(lot.entry_price),
        "entry_time": lot.entry_time.isoformat(),
    }


def _dict_to_position_lot(data: dict[str, Any]) -> PositionLot:
    """Restore PositionLot from dict."""
    return PositionLot(
        quantity=Decimal(data["quantity"]),
        entry_price=Decimal(data["entry_price"]),
        entry_time=datetime.fromisoformat(data["entry_time"]),
    )


def _settlement_entry_to_dict(entry: SettlementEntry) -> dict[str, Any]:
    """Serialize SettlementEntry to dict."""
    return {
        "amount": str(entry.amount),
        "release_time": entry.release_time.isoformat(),
    }


def _dict_to_settlement_entry(data: dict[str, Any]) -> SettlementEntry:
    """Restore SettlementEntry from dict."""
    return SettlementEntry(
        amount=Decimal(data["amount"]),
        release_time=datetime.fromisoformat(data["release_time"]),
    )


def _bracket_to_dict(bracket: BracketState) -> dict[str, Any]:
    """Serialize BracketState to dict."""
    return {
        "stop_loss": _order_request_to_dict(bracket.stop_loss) if bracket.stop_loss else None,
        "take_profit": _order_request_to_dict(bracket.take_profit) if bracket.take_profit else None,
        "parent_id": bracket.parent_id,
    }


def _dict_to_bracket(data: dict[str, Any]) -> BracketState:
    """Restore BracketState from dict."""
    from liq.core import OrderRequest

    return BracketState(
        stop_loss=OrderRequest(**data["stop_loss"]) if data["stop_loss"] else None,
        take_profit=OrderRequest(**data["take_profit"]) if data["take_profit"] else None,
        parent_id=data["parent_id"],
    )


def _order_request_to_dict(order: Any) -> dict[str, Any]:
    """Serialize OrderRequest to dict."""
    result: dict[str, Any] = order.model_dump(mode="json")
    return result


def _random_state_to_serializable(state: tuple[Any, ...]) -> list[Any]:
    """Convert random.getstate() tuple to JSON-serializable format.

    The random state is a tuple: (version, state_tuple, gauss_next)
    where state_tuple contains a large tuple of ints.
    """
    version, state_tuple, gauss_next = state
    return [version, list(state_tuple), gauss_next]


def _serializable_to_random_state(data: list[Any]) -> tuple[Any, ...]:
    """Restore random state tuple from serialized format."""
    version, state_list, gauss_next = data
    return (version, tuple(state_list), gauss_next)
