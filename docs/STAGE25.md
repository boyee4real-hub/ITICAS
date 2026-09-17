# Stage 25 — Context-Aware Predictive Intelligence & Explainability

Stage 25 preserves the validated Stage 23/24 traffic-history forecasting baseline and adds a stronger, auditable validation-weighted ensemble plus external decision context.

## Added
- Validation-weighted ensemble candidate using inner-validation inverse-error weights and untouched final holdout selection.
- Hourly Open-Meteo future weather context for the requested forecast window.
- Stored TomTom incident context for the selected monitored road.
- Recent corridor-probe spatial context.
- Weekday/weekend context without inventing public-holiday labels.
- Forecast-point context flags for rain, heavy rain, active incidents, corridor congestion and weekends.
- Dynamic explainability showing recent state, clock-hour pattern, weekday-hour pattern, trend and ensemble weights.
- Prediction decision package additions: context table, explainability table, ensemble weights and prediction-context dashboard.

## Scientific boundary
External context remains advisory unless its traffic effect has been empirically calibrated and validated for the selected road. ITICAS does not silently convert rain, incidents or corridor conditions into an unvalidated causal adjustment of the traffic forecast mean.
