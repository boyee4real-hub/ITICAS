# ITICAS Stage 23 — Predictive Traffic Intelligence

Stage 23 activates the prediction capability that was architecturally reserved in the database from the early stages.

## Scientific behaviour
The engine never manufactures a forecast when the selected road lacks enough historical evidence. Before every prediction request, ITICAS attempts to import available autonomous Supabase archive history for that monitoring location. It then compares four transparent temporal candidate models on held-out observations and selects the lowest-error model for that road.

Candidate models:
- persistence baseline;
- clock-hour seasonal profile;
- weekday/hour seasonal profile;
- adaptive hybrid of seasonal behaviour, recent state and capped short-term trend.

Outputs include forecast speed, congestion index, class, empirical uncertainty bounds, validation MAE/RMSE, speed MAE, model-selection table, evidence grade, limitations and persistent prediction audit records.

## Horizon
The user chooses the future start and end time. Current supported horizon is 5 minutes to 7 days, with 5/10/15/30/60-minute output resolution. This is a configurable safety/cost bound, not a fixed prediction preset.

## Important limitation
Stage 23 is a traffic-history model. Future incidents, road works, special events and weather are not yet causal predictors. Those can be introduced as validated covariates in a later stage without weakening the Stage 23 benchmark baseline.
