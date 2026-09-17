# ITICAS Stage 22 — Supabase autonomous archive baseline

Stage 22 preserves the validated serverless archive established in Stage 21. It does **not** require the PostgreSQL `vault` extension.

Validated architecture:

`Supabase Cron (every 5 minutes) -> Edge Function -> TomTom Flow Segment Data -> archive_observations`

Use the Supabase dashboard Cron integration rather than embedding privileged secrets in SQL. The working job configuration is:

- Name: `iticas-traffic-collector`
- Schedule: `*/5 * * * *`
- Type: **Supabase Edge Function**
- Method: `POST`
- Function: `iticas-traffic-collector`
- Timeout: `5000 ms` (dashboard maximum observed during deployment)
- HTTP header: `apikey = <project publishable key>`
- Body: `{"trigger":"supabase_cron"}`

The TomTom API key remains an Edge Function secret. The local ITICAS Supabase server credential remains in `C:\iticas\.env`; do not paste it into Cron SQL or screenshots.

`01_schema.sql` is the canonical no-Vault schema. The obsolete Stage 21 Vault scripts are intentionally removed from this package.

After deployment, `02_VERIFY_AUTONOMOUS_ARCHIVE.sql` provides read-only health checks.
