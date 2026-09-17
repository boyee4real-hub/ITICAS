ITICAS Stage 24 — Map Road Selection + Prediction Decision Deliverables

Overlay this ZIP into C:\iticas. It preserves .env, .venv, database\iticas.db, users, Supabase/TomTom credentials, archived observations, monitoring locations and research data.

Then run:
  cd /d C:\iticas
  call .venv\Scripts\activate
  APPLY_STAGE24.cmd
  RUN_APP.cmd

Key pages:
  http://127.0.0.1:8765/map
  http://127.0.0.1:8765/predictions

Stage 24 adds:
- click a road/point on OSM -> identify road/address -> immediately show traffic information
- hand a nearby monitored road from Live Map directly to Predictions
- operational prediction decision signals
- individual Forecast CSV, JSON and chart SVG downloads
- full multi-deliverable prediction decision ZIP with tables, maps, graphs, charts and executive analysis
