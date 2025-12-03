# liq-sim Implementation Plan

Guiding principles: SOLID, DRY, KISS. Build with strict TDD (red–green–refactor) and keep each phase in a stable, shippable state. Reference: `quant-planning/DEVELOPMENT_STANDARDS.md`, `quant-planning/liq-sim-prd.md`, and shared contracts in `liq-types`.

## Phase 0 – Groundwork (Commit-ready)
- Align dependencies with `liq-types` (latest contracts: `realized_pnl` on `Fill`, `strategy_id`/`confidence`/`tags` on `OrderRequest`, `PortfolioState` with `unsettled_cash` and `day_trades_remaining`).
- Scaffold package structure (`src/liq/sim/...`), pyproject with tool configs (ruff, mypy strict, pytest coverage gate), and pre-commit.
- Add CI placeholders and README note that scope is execution-only (no sizing/signals/metrics here).
- Tests: tooling smoke (import package), type-check pipeline.

## Phase 1 – Contracts & Validation (Commit-ready)
- Implement adapters/aliases to `liq-types` models (no redefinition), plus lightweight validators for provider config, simulator config, and comparison hooks (if any) to enforce PRD invariants.
- Add order eligibility timing logic stubs (`min_order_delay_bars`) and look-ahead guardrails.
- Tests: config validation (happy/negative), order eligibility delay and look-ahead rejection.

## Phase 2 – Accounting Core (Commit-ready)
- Implement `PositionManager` with FIFO lots, realized/unrealized P&L updates (mark using bar midrange per PRD), support shorts, and tracking of `unsettled_cash`, `cash`, `equity`, `day_trades_remaining`.
- Implement settlement queue (T+N) and borrowing cost hooks (placeholders for provider rates).
- Tests: FIFO correctness, unrealized mark-to-mid, settlement release, short borrow accrual placeholder behavior.

## Phase 3 – Provider Models v1 (Coinbase & Robinhood) (Commit-ready)
- Fee models: TieredMakerTaker, ZeroCommission.
- Slippage models: VolumeWeighted, PFOF.
- Constraints: shorting disabled for Robinhood; margin type hooks.
- Tests: maker vs taker application, PFOF adverse slippage, zero-commission correctness.

## Phase 4 – Execution Loop & Orders (Commit-ready)
- Implement bar-driven event loop per PRD: advance time, settlement, risk checks, validate orders, open orders, match orders, apply costs, execute fills, create/process brackets, update account.
- Implement order fill rules for MARKET/LIMIT/STOP/STOP_LIMIT with `min_order_delay_bars`.
- Bracket orders: OCO, adverse-path rule when both levels hit, GTC across bars, activation next bar.
- Tests: fill-price matrix, bracket OCO and adverse-path, DAY vs GTC semantics, delay enforcement.

## Phase 5 – Constraints & Kill Switches (Commit-ready)
- Enforce buying power, margin hooks, PDT counter using `day_trades_remaining`, position limits (`max_position_pct`), daily loss and drawdown kill-switch with exposure-reduction exception.
- Tests: PDT lockout on 4th day trade, position limit rejection, kill-switch behavior (blocks exposure-increasing only).

## Phase 6 – Provider Models v2 (Oanda & Tradestation) (Commit-ready)
- Fee models: SpreadBased, PerShare (with min per order).
- Slippage: SpreadBased, VolumeWeighted.
- FX conversion for P&L (quote/base/cross) using supplied rates; swap/financing at 5pm NY with Wednesday 3x.
- Shorting with borrow fees and locate flag for Tradestation.
- Tests: spread execution, FX conversion paths (quote/base/cross), swap accrual timing, per-share min fee.

## Phase 7 – Checkpointing & Determinism (Commit-ready)
- Checkpoint save/restore (state, config hash, backtest_id).
- Deterministic seeding for slippage randomness (if any) and reproducible runs.
- Tests: checkpoint round-trip equality, deterministic seed replay.

## Phase 8 – Outputs & Integration Hooks (Commit-ready)
- Ensure fill logs include `realized_pnl`, commission, slippage, provider; equity curve output aligned to `liq-metrics` expectations.
- Comparison/baseline integration: expose data interfaces; keep logic in `liq-runner`.
- Tests: schema conformity for fills/equity outputs; compatibility smoke with `liq-metrics` consumption (fixture).

## Phase 9 – Golden Sets & Coverage (Commit-ready)
- Add golden-set fixtures (BTC minute, AAPL daily, EURUSD swaps placeholders) and regression assertions on key metrics (tolerance per PRD).
- Achieve ≥90% coverage per standards; add Hypothesis where beneficial (e.g., fill rule properties).
- Final docs/examples refresh.

## Phase 10 – CLI (Commit-ready)
- Provide a Typer + Rich CLI for running simulations from config files/env: e.g., `liq-sim run --config config.yaml`, optional provider override, seed control, and checkpoint resume.
- Include commands for validating configs (`liq-sim validate-config`) and emitting schema stubs.
- Tests: CLI smoke (Typer runner), validation command, run command wiring to core entrypoint (mocked simulator).
