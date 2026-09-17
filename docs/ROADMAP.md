# ITICAS Development Roadmap

01. Foundation and attractive application shell
02. Persistent database schema and geospatial-ready data model
03. Ibadan road/location catalogue and location manager
04. Live traffic provider integration with adapter architecture
05. Automatic scheduled traffic monitoring
06. Weather integration and synchronized observations
07. Congestion Intelligence Engine and derived indicators
08. Interactive live dashboard and map
09. Statistical analysis engine
10. Graph, figure, table and export generator
11. Spatial traffic intelligence and hotspot analysis
12. Machine-learning prediction
13. Explainable AI
14. Automated reporting, validation, packaging and release


## Stage 23 — Predictive Traffic Intelligence
- User-specified future start/end period and forecast resolution.
- Automatic cloud-history import before modelling.
- Transparent candidate models: persistence, clock-hour seasonal, weekday-hour seasonal, adaptive hybrid.
- Holdout model selection using CI MAE/RMSE and speed MAE.
- Empirical uncertainty envelope, evidence-readiness grade, limitations and audit trail.
- Nationwide architecture: any monitored road/location with adequate stored evidence.
- Future stages may add weather/event/incident causal covariates without replacing this validated baseline.

## Stage 24 — Map Road Selection + Prediction Decision Deliverables
- Click a road/point on the national OSM map and reverse-identify the nearest road/address.
- Immediately evaluate live traffic and show road name, address/context, speed, free-flow, congestion, delay, confidence, incidents, weather and nearby stored ITICAS history.
- Handoff nearby monitored roads directly from Live Map to Predictions.
- Add forecast decision metrics and operational signals while retaining holdout validation and uncertainty.
- Export individual CSV/JSON/SVG prediction outputs.
- Export a multi-deliverable prediction decision ZIP with tables, graphs, validation chart, road decision map, provenance JSON and executive decision brief.

## Stage 25 — Context-Aware Predictive Intelligence & Explainability
Status: implemented.

The prediction roadmap remains active. Stage 25 adds validation-weighted ensemble forecasting, external weather/incident/corridor/day-type context, explainability and richer prediction decision-package deliverables while preserving the historical-only validated baseline and uncertainty gate.

Next prediction work: road-specific calibrated exogenous effects once sufficient paired history exists; scenario/event planning; model drift monitoring; longer seasonal validation; and optional stronger ML candidates only when they demonstrably outperform the transparent baseline on held-out observations.

## Stage 26 — Calibrated Prediction, Scenario & Drift Intelligence
Status: implemented.

- Adds an interpretable cyclic-ridge machine-learning candidate; it is selected only when held-out error beats simpler baselines.
- Adds road-specific empirical context calibration using paired stored traffic + historical weather and stored incident timing.
- Rain/incident effects may change the forecast mean only after a holdout validation gate shows at least 2% MAE improvement with minimum exposed/unexposed evidence.
- Adds baseline versus validated context-adjusted scenario comparison without inventing coefficients.
- Adds post-forecast verification by matching past predictions to subsequent ITICAS observations and flags material forecast drift.
- Expands the prediction decision package with context-calibration, realized-verification/drift and scenario tables plus a verification figure.
- Preserves nationwide arbitrary-road architecture, user-specified horizons, uncertainty, provenance and non-fabrication rules.

Final release work after Stage 26 is limited to consolidated system QA, deployment/readiness checks, user-facing help and release packaging; the prediction capability itself is feature-complete at this stage subject to evidence availability on each road.
