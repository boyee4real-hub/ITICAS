# ITICAS Stage 07 Reliability Fix 1 (v0.7.1)

This overlay strengthens the Nigeria-wide National Traffic Explorer without changing its scope or deleting existing data.

Key changes:
- bounded retry/backoff for transient TomTom traffic and search failures;
- explicit failure categories for DNS, timeout, connectivity, rate limit, provider outage, authentication and invalid requests;
- a live traffic flow failure no longer gets confused with "no coverage";
- incident-service failure no longer discards a valid flow result;
- historical ITICAS data remains clearly historical and is never substituted for unavailable live traffic;
- map-tile connectivity diagnostics and a manual tile reload control;
- a single automatic visible-tile retry after map tile failures;
- Leaflet `invalidateSize()` calls after resize/selection to avoid stale geometry after layout changes;
- stage version updated to 0.7.1;
- exact developer credit retained: Developed by Dr. Oyeyode A.O. MNIS, MGEOSON, MNAG.

The base map still requires internet access to retrieve raster tiles. Missing tile squares during weak connectivity are treated as a map-image delivery issue rather than evidence that live traffic data is unavailable.
