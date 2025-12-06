"""Typer-based CLI entrypoints for liq-sim."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from liq.core import Bar, OrderRequest
from rich.console import Console
from rich.table import Table

from liq.sim.checkpoint import SimulationCheckpoint
from liq.sim.config import ProviderConfig, SimulatorConfig
from liq.sim.simulator import Simulator

app = typer.Typer(help="liq-sim CLI")
console = Console()


def _load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def _render_equity_curve(equity_curve: list[tuple[datetime, Decimal]]) -> None:
    table = Table(title="Equity Curve", show_lines=False)
    table.add_column("Timestamp")
    table.add_column("Equity", justify="right")
    for ts, eq in equity_curve:
        table.add_row(str(ts), str(eq))
    console.print(table)


@app.command("validate-config")
def validate_config(
    provider_config: Path = typer.Argument(..., help="Path to provider config JSON"),  # noqa: B008
    simulator_config: Path = typer.Argument(..., help="Path to simulator config JSON"),  # noqa: B008
) -> None:
    """Validate provider and simulator configurations."""
    try:
        ProviderConfig(**_load_json(provider_config))
        SimulatorConfig(**_load_json(simulator_config))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Invalid config:[/red] {exc}")
        raise typer.Exit(1) from None
    console.print("[green]Configs are valid.[/green]")


@app.command("run")
def run_sim(
    orders_path: Path = typer.Argument(..., help="Path to orders JSON list"),  # noqa: B008
    bars_path: Path = typer.Argument(..., help="Path to bars JSON list"),  # noqa: B008
    provider_config: Path = typer.Argument(..., help="Path to provider config JSON"),  # noqa: B008
    simulator_config: Path = typer.Argument(..., help="Path to simulator config JSON"),  # noqa: B008
    checkpoint_in: Path | None = typer.Option(None, help="Checkpoint to resume from"),  # noqa: B008
    checkpoint_out: Path | None = typer.Option(None, help="Where to write checkpoint after run"),  # noqa: B008
) -> None:
    """Run a simulation from JSON inputs and render summary."""
    if checkpoint_in:
        chk = SimulationCheckpoint.load(checkpoint_in)
        sim = Simulator.from_checkpoint(chk)
    else:
        p_cfg = ProviderConfig(**_load_json(provider_config))
        s_cfg = SimulatorConfig(**_load_json(simulator_config))
        sim = Simulator(provider_config=p_cfg, config=s_cfg)

    orders = [OrderRequest(**o) for o in _load_json(orders_path)]
    bars = [Bar(**b) for b in _load_json(bars_path)]

    result = sim.run(orders, bars)
    _render_equity_curve(result.equity_curve)
    console.print(f"[cyan]Fills:[/cyan] {len(result.fills)}")
    console.print(f"[cyan]Final equity:[/cyan] {result.equity_curve[-1][1] if result.equity_curve else 'n/a'}")

    if checkpoint_out:
        sim.to_checkpoint(backtest_id="cli-run", config_hash="cli").save(checkpoint_out)
        console.print(f"[green]Checkpoint written to {checkpoint_out}[/green]")


if __name__ == "__main__":
    app()
