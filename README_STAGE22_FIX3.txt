ITICAS Stage 22 Fix 3 - Final Map + Historical Reliability

This overlay fixes two user-visible issues:
1. Live Map no longer depends on Leaflet/CDN JavaScript. It uses a small native ITICAS OSM slippy-map engine with wheel zoom, drag pan, +/- controls, click-to-evaluate, monitoring markers, traffic flow overlays and incident markers. OSM tiles are loaded directly first, with the existing ITICAS backend tile proxy/cache as automatic fallback.
2. Historical Data JavaScript is now defensive against stale/mismatched DOM assets and partial cloud-status failures. Stored observations load independently and the table remains usable even if the cloud status refresh fails. Static assets are cache-busted.

Persistent data is NOT reset. Supabase Cron, Edge Function, .env, local DB, users, observations, locations and credentials are preserved.
