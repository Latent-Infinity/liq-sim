# Development Plan: Close liq-sim Gaps (Calibration/EV Thresholds, Funding/Slippage, Risk Caps)

## Stage 0: Foundation & Standards (≥95% coverage)
- Audit current sim configs/pipelines; document inputs/outputs needed for calibration, EV thresholding, funding, slippage metrics, and risk caps.
- Define interfaces/protocols for:
  - Calibration (per-fold temperature/Platt) and EV-based threshold selector.
  - Funding model (scenario selector: base/elevated/spike) and slippage reporter.
  - Risk-cap policy adapter (net-position cap, pyramiding limit, equity floor kill-switch, frequency caps) leveraging liq-risk.
- Extend config schema (pydantic) for new options: calibration toggle, EV constraints (precision/recall/trade-count), funding scenario, slippage percentile reporting, risk caps toggles/limits.
- Write contract tests for interfaces/config validation (expected to fail until implemented).

## Stage 1: Core Domain (≥95% coverage)
- Implement pure calibration utilities (per-fold temperature scaling/Platt) returning calibrated scores + params.
- Implement EV-based threshold search with precision/recall/trade-count constraints; return threshold, EV, constraint satisfaction.
- Implement slippage stats aggregator (percentiles per window) as pure function.
- Implement funding schedule model for scenarios (base/elevated/spike) to compute funding rates over time windows.
- Implement risk-cap decision functions (pure): net-position cap, pyramiding limit, equity floor kill-switch, frequency cap evaluators given current state.
- Unit tests for all domain functions (happy/edge cases).

## Stage 2: Primary Implementation (≥90% coverage)
- Wire rolling_retrain pipeline to apply per-fold calibration, feed calibrated scores into EV-based threshold selection, and persist thresholds/params in results.
- Integrate funding model into simulation loop: compute funding charges per step and deduct from PnL; expose funding in outputs.
- Integrate slippage percentile reporting: collect per-window slippage samples and include in results.
- Integrate risk-cap checks into sizing/entry path: apply net-position/pyramiding caps, equity floor kill-switch, frequency caps before orders.
- Adapter tests/mocks plus an end-to-end happy path covering new behaviors with fakes.

## Stage 3: Integration (≥90% coverage)
- Wire to liq-risk policies (or shim) so risk caps pull from shared policies.
- Config-driven toggles for funding scenarios and EV constraints; validate error paths for missing/invalid configs.
- Integration test of rolling_retrain on synthetic data verifying calibrated thresholds, funding charged, slippage stats emitted, and risk caps enforced.

## Stage 4: Hardening (≥90% coverage)
- Add structured logging at decisions: calibration params, chosen thresholds/EV, funding charges per window, risk-cap rejections, slippage percentile summaries.
- Tests for logging/metrics hooks (content/shape).

## Stage 5: Polish & Documentation (≥90% coverage)
- Update README/usage docs: new configs, outputs (thresholds, funding, slippage stats), risk-cap behavior.
- Add examples showing calibration+EV thresholding enabled and funding scenarios.
- Maintain coverage target and stage changes for review.
