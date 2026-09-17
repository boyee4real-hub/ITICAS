ITICAS Stage 22 Fix 2 — Fast OpenStreetMap + Stored Historical Archive Integration

Purpose
1. Replace the heavy server-rendered static basemap interaction with a lightweight Leaflet/OpenStreetMap map.
2. Make Historical Data load the autonomous Supabase traffic archive for monitored roads automatically.
3. Show actual stored traffic rows with timestamp, speed, free-flow speed, congestion, delay, confidence, road closure and provenance.
4. Keep optional TomTom Traffic Stats backfill separate from ITICAS autonomous history.
5. Replace obsolete regression assertions that expected the retired static-map interaction engine.

Preserved
- .env and credentials
- .venv
- local SQLite database
- monitoring locations
- Supabase archive tables and observations
- Supabase Cron and Edge Function
- existing research, reports and analytics data

After applying, restart ITICAS and press Ctrl+F5 in the browser.
