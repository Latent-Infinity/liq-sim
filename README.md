# liq-sim

Execution simulation layer for the LIQ Stack. Scope: simulate broker-specific execution (fees, slippage, settlement, PDT, brackets) over pre-sized orders from `liq-risk`. Out of scope: signal generation, feature computation, reporting, and experiment orchestration (handled by `liq-signals`, `liq-features`, `liq-metrics`, `liq-runner`).

Status: Phase 0/1 scaffolding and validation. See `docs/IMPLEMENTATION_PLAN.md` for the phased TDD roadmap aligned to the PRD.
