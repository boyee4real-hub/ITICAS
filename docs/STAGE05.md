# ITICAS Stage 05 — Nationwide Automatic Monitoring

Stage 05 treats Nigeria-wide coverage as a foundational runtime rule, not an expansion.

- Scheduler selects every active monitoring location in the database, irrespective of city/state.
- Only coordinate-verified records are queried; unresolved records are skipped and audited.
- Monitoring run + per-location run-item tables preserve acquisition history and failures.
- Default cadence is 5 minutes and can be changed with `CONFIGURE_MONITORING.cmd`.
- Provider credentials remain local in `.env`.
- Historical locations with traffic observations cannot be physically deleted; deactivate them instead.
- Prediction request/storage tables are introduced now with arbitrary forecast start/end/horizon fields so later model work does not require an Ibadan-only or fixed-horizon redesign.
- Core runtime tests fail if `Ibadan` is hard-coded into backend runtime, main dashboard, or launcher.
