# ITICAS Stage 11 — Resilient National Basemap + Historical Traffic Backfill

## Basemap
Primary map rendering is MapLibre GL JS with OpenFreeMap's vector style. If the primary vector style repeatedly fails, ITICAS switches to the existing OpenStreetMap raster layer as fallback. Traffic/search APIs are independent of the basemap.

## Historical traffic
ITICAS includes an optional TomTom Traffic Stats Route Analysis adapter. It does not fabricate historical data.

A requested historical period is split into chunks of at most 24 dates because Route Analysis supports at most 24 date ranges per job. Each date is a separate dateRange and each hour is a separate timeSet. This preserves day-and-hour uniqueness.

Completed provider results are ingested into `historical_traffic_samples` as `data_origin=historical_provider`.

Live observations remain `observed_live` and always take priority for an hour where both live and historical-provider data are available.

## Credentials
Traffic Stats may require separate product entitlement. Run `CONFIGURE_TOMTOM_TRAFFIC_STATS.cmd` if a dedicated Traffic Stats key is issued. If no separate key is configured, ITICAS can attempt the existing TomTom key, but entitlement is determined by TomTom.

## Scientific integrity
Historical provider values, live observations, future imputed values and predictions remain distinct provenance classes.
