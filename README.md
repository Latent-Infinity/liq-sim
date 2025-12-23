# liq-sim

Execution simulation layer for the LIQ Stack. Scope: simulate broker-specific execution (fees, slippage, settlement, PDT, brackets) over pre-sized orders from `liq-risk`. Out of scope: signal generation, feature computation, reporting, and experiment orchestration (handled by `liq-signals`, `liq-features`, `liq-metrics`, `liq-runner`).

Status: Phases 0–10 complete (scaffolding through CLI). See `docs/IMPLEMENTATION_PLAN.md` for the phased TDD roadmap aligned to the PRD.

Recent additions: funding scenarios (base/elevated/spike) charged during runs, slippage percentile reporting in `SimulationResult.slippage_stats`, and additional risk caps (frequency, equity floor, net/pyramiding checks) aligned with `liq-risk`.

## Installation

```bash
pip install liq-sim
```

For development:
```bash
pip install -e ".[dev]"
```

## Quick Start

### Programmatic Usage

```python
from datetime import datetime, timezone
from decimal import Decimal

from liq.core import Bar, OrderRequest
from liq.core.enums import OrderSide, OrderType, TimeInForce
from liq.sim import ProviderConfig, SimulatorConfig, Simulator

# Configure provider (broker-specific settings)
provider_config = ProviderConfig(
    name="alpaca",
    asset_classes=["equity"],
    fee_model="TieredMakerTaker",
    fee_params={"maker_bps": "0", "taker_bps": "0"},
    slippage_model="VolumeWeighted",
    slippage_params={"base_bps": "1", "volume_impact": "0.1"},
    settlement_days=2,  # T+2 for equities
)

# Configure simulator
sim_config = SimulatorConfig(
    initial_capital=Decimal("100000"),
    min_order_delay_bars=1,
    max_position_pct=0.25,  # Max 25% in single position
    random_seed=42,
)

# Create simulator
sim = Simulator(provider_config=provider_config, config=sim_config)

# Define orders and bars
ts = datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc)
orders = [
    OrderRequest(
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("100"),
        time_in_force=TimeInForce.DAY,
        timestamp=ts,
    )
]

bars = [
    Bar(
        symbol="AAPL",
        timestamp=ts,
        open=Decimal("150.00"),
        high=Decimal("152.00"),
        low=Decimal("149.50"),
        close=Decimal("151.00"),
        volume=Decimal("1000000"),
    )
]

# Run simulation
result = sim.run(orders, bars)

# Access results
print(f"Fills: {len(result.fills)}")
print(f"Rejected orders: {len(result.rejected_orders)}")
print(f"Final equity: {result.equity_curve[-1][1]}")
for fill in result.fills:
    print(f"  {fill.symbol}: {fill.side.value} {fill.quantity} @ {fill.price}")
```

### CLI Usage

A Typer + Rich CLI is available for quick runs and config validation:

```bash
# Validate configs
python -m liq.sim.cli validate-config provider.json simulator.json

# Run a simulation and emit a checkpoint
python -m liq.sim.cli run orders.json bars.json provider.json simulator.json --checkpoint-out chk.msgpack

# Resume from checkpoint
python -m liq.sim.cli run orders.json bars.json provider.json simulator.json --checkpoint-in chk.msgpack
```

- `validate-config`: ensures provider and simulator configs conform to the PRD/liq-core models.
- `run`: executes a simulation from JSON inputs, prints equity via Rich, and can emit/resume from checkpoints.

## Configuration Reference

### ProviderConfig

Broker-specific execution parameters:

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Provider identifier (e.g., "alpaca", "coinbase") |
| `asset_classes` | `list[str]` | Supported asset classes (e.g., ["equity", "crypto"]) |
| `fee_model` | `str` | Fee model: "TieredMakerTaker", "ZeroCommission", "PerShare" |
| `fee_params` | `dict` | Fee model parameters (e.g., `{"maker_bps": "2", "taker_bps": "5"}`) |
| `slippage_model` | `str` | Slippage model: "VolumeWeighted", "PFOF", "SpreadBased" |
| `slippage_params` | `dict` | Slippage parameters (e.g., `{"base_bps": "1"}`) |
| `settlement_days` | `int` | Settlement period (0 for crypto, 2 for equities) |
| `pdt_enabled` | `bool` | Enable Pattern Day Trader tracking |
| `short_enabled` | `bool` | Allow short selling |
| `locate_required` | `bool` | Require locate for shorts |
| `initial_margin_rate` | `Decimal` | Initial margin requirement (default: 0.5) |
| `borrow_rate_annual` | `Decimal` | Annual borrow rate for shorts |

### SimulatorConfig

Simulation behavior settings:

| Field | Type | Description |
|-------|------|-------------|
| `initial_capital` | `Decimal` | Starting cash balance |
| `min_order_delay_bars` | `int` | Bars before order becomes eligible (prevents lookahead) |
| `max_position_pct` | `float` | Maximum position size as % of equity (0.0-1.0) |
| `max_drawdown_pct` | `float` | Kill switch trigger on drawdown |
| `max_daily_loss_pct` | `float` | Kill switch trigger on daily loss |
| `random_seed` | `int` | RNG seed for deterministic replay |

## Fee Models

### TieredMakerTaker
Maker/taker fee structure common in exchanges:
```python
fee_params={"maker_bps": "2", "taker_bps": "5"}
```

### ZeroCommission
No commission (e.g., Robinhood-style):
```python
fee_model="ZeroCommission"
```

### PerShare
Per-share pricing with minimum:
```python
fee_params={"per_share": "0.005", "minimum": "1.00"}
```

## Slippage Models

### VolumeWeighted
Slippage increases with order size relative to volume:
```python
slippage_params={"base_bps": "1", "volume_impact": "0.1"}
```

### PFOF (Payment for Order Flow)
Fixed adverse price impact:
```python
slippage_params={"adverse_bps": "0.5"}
```

### SpreadBased
Uses bid-ask spread from bar data:
```python
slippage_params={"spread_pct": "0.1"}
```

## Constraint Checks

The simulator enforces several risk constraints:

| Constraint | Description |
|------------|-------------|
| **Buying Power** | Order value cannot exceed available cash |
| **Position Limit** | Single position cannot exceed `max_position_pct` of equity |
| **Margin** | Margin requirement must not exceed equity |
| **PDT** | Pattern Day Trader limit (3 day trades per rolling 5 days) |
| **Short Permission** | Shorts blocked if `short_enabled=False` |
| **Locate Required** | Short sells require locate metadata |
| **Kill Switch** | Blocks buys after drawdown/daily loss thresholds |

Rejected orders are tracked in `SimulationResult.rejected_orders` with reasons.

## Checkpointing

Simulations can be checkpointed and resumed for long-running backtests:

```python
# Save checkpoint
checkpoint = sim.to_checkpoint(backtest_id="bt-001", config_hash="abc123")
checkpoint.save(Path("checkpoint.msgpack"))

# Load and resume
from liq.sim import SimulationCheckpoint

loaded = SimulationCheckpoint.load(Path("checkpoint.msgpack"))
resumed_sim = Simulator.from_checkpoint(loaded)
result = resumed_sim.run(remaining_orders, remaining_bars)
```

Checkpoints use MessagePack format (`.msgpack` extension) for security and efficiency. See `docs/CHECKPOINT.md` for format details.
