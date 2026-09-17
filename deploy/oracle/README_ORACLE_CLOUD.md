# ITICAS Stage 20 — Oracle Cloud Always Free deployment

Purpose: keep ITICAS and its historical collector running when the user's personal PC is off.

Architecture:
- `iticas-web.service`: FastAPI web application.
- `iticas-collector.service`: dedicated autonomous archive process.
- `/var/lib/iticas`: persistent SQLite database and rolling backups.
- nginx: port 80 reverse proxy.
- systemd: automatically starts both services after reboot and restarts them after failure.

The collector records:
1. Active monitoring locations at `ARCHIVE_LOCATION_INTERVAL_SECONDS` (default 5 min).
2. Deep corridor-probe observations at `ARCHIVE_PROBE_INTERVAL_SECONDS` (default 60 min).
3. Heartbeat/state every 30 seconds.
4. A safe SQLite backup once per day, retaining 30 days by default.

Important scope:
- ITICAS history begins when the cloud collector begins running.
- ITICAS cannot reconstruct a road's earlier past if that road was never registered for monitoring.
- Do not attempt a nationwide exhaustive live-data mirror unless provider quota/licence permits it.
