ITICAS STAGE 26 — CALIBRATED PREDICTION, SCENARIO & DRIFT INTELLIGENCE

This is the feature-complete release-candidate stage for the current ITICAS development roadmap.

Prediction additions:
- interpretable cyclic-ridge machine-learning candidate
- transparent baseline + ensemble holdout competition
- road-specific historical traffic-weather calibration
- road-specific incident-effect calibration when evidence permits
- strict holdout gate before exogenous effects can alter forecasts
- baseline versus context-calibrated scenario comparison
- post-forecast realized accuracy and drift monitoring
- expanded decision ZIP with calibration, verification and scenario deliverables

No arbitrary weather/incident coefficients are used. If a road has insufficient paired evidence, external context remains advisory.

INSTALL:
1. Extract this ZIP over C:\iticas
2. cd /d C:\iticas
3. call .venv\Scripts\activate
4. APPLY_STAGE26.cmd
5. RUN_APP.cmd
6. Ctrl+F5 in the browser

The package preserves .venv, .env, database\iticas.db, credentials, users, monitoring locations, traffic/archive history and research data.
