# Stage 26 — Calibrated Prediction, Scenario & Drift Intelligence

Stage 26 completes the planned prediction capability without replacing the validated Stage 23–25 baseline.

## Scientific rules
1. Simpler and advanced candidates compete on held-out observations.
2. `cyclic_ridge` is an interpretable regularized ML candidate using cyclical time features.
3. Weather or incident context is never given an arbitrary traffic coefficient.
4. A road-specific rain/incident CI adjustment is applied only when paired historical evidence passes minimum sample rules and improves untouched validation MAE by at least 2%.
5. If the gate fails, the context stays advisory and the baseline forecast remains unchanged.
6. Post-forecast verification uses subsequently observed ITICAS traffic rather than provider forecasts.

## User workflow
- Select a monitored road and arbitrary future period.
- Optionally run **Calibrate context** as the archive grows.
- Run forecast.
- Inspect validation, uncertainty, context calibration, scenario comparison and realized drift.
- Download individual forecast outputs or the full prediction decision package.
