# liq-sim

Execution simulation layer for the LIQ Stack. Scope: simulate broker-specific execution (fees, slippage, settlement, PDT, brackets) over pre-sized orders from `liq-risk`. Out of scope: signal generation, feature computation, reporting, and experiment orchestration (handled by `liq-signals`, `liq-features`, `liq-metrics`, `liq-runner`).

Status: Phases 0–10 complete (scaffolding through CLI). See `docs/IMPLEMENTATION_PLAN.md` for the phased TDD roadmap aligned to the PRD.

## CLI

A Typer + Rich CLI is available for quick runs and config validation:

```bash
# Validate configs
python -m liq.sim.cli validate-config provider.json simulator.json

# Run a simulation and emit a checkpoint
python -m liq.sim.cli run orders.json bars.json provider.json simulator.json --checkpoint-out chk.pkl

# Resume from checkpoint
python -m liq.sim.cli run orders.json bars.json provider.json simulator.json --checkpoint-in chk.pkl
```

- `validate-config`: ensures provider and simulator configs conform to the PRD/liq-types models.
- `run`: executes a simulation from JSON inputs, prints equity via Rich, and can emit/resume from checkpoints.
