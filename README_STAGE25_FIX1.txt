ITICAS Stage 25 Fix 1
=====================

Purpose
-------
1. Prevent /api/search/reverse HTTP 500 when TomTom returns reverse-geocode position as a string rather than an object.
2. Preserve the OSM/Nominatim road-name fallback after a malformed/generic primary reverse result.
3. Make Stage 25 UI/export tests explicitly read UTF-8 so Windows cp1252 does not raise UnicodeDecodeError on navigation symbols.

No data reset
-------------
This overlay does not modify .env, .venv, database/iticas.db, users, Supabase archive, Cron, Edge Function, TomTom credentials, monitoring locations, observations, research records or prediction history.

Install into C:\iticas and run APPLY_STAGE25_FIX1.cmd.
