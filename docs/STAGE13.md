# ITICAS Stage 13 — Reliability, Nationwide Road Explorer, Historical Ingestion & Decision Reporting

Stage 13 repairs the live map and search-result evaluation path, automates historical Traffic Stats job polling/ingestion, clarifies the configured-network basis of spatial ranking, preserves arbitrary Nigeria-wide road evaluation, and expands research reports with publication cartography and decision metrics.

## Map reliability
The browser requests map tiles only from `/api/map/tile/{z}/{x}/{y}`. The backend caches tiles, uses TomTom Orbis raster tiles as primary source when configured, falls back to OpenStreetMap, and can serve a fresh-enough cache during transient upstream failure. Traffic evaluation does not depend on map rendering.

## Spatial intelligence scope
The intervention-ranking table is based on configured active monitoring locations with coordinates and usable traffic evidence. It is not a census of every Nigerian road. The Nationwide Road Explorer above it evaluates any searchable Nigerian road/corridor on demand. A long-period ranking requires evidence for that segment; absence from the ranking means insufficient configured evidence, not that the road does not exist.

## Historical traffic
Traffic Stats jobs are asynchronous. Stage 13 polls pending jobs in the application background and opportunistically on Historical Data status refresh. DONE jobs are downloaded and ingested as `historical_provider` hourly samples. Live observations take precedence for overlapping hours.

## Reports
Reports now preview live/historical/combined evidence before export. Complete packages include CSV, XLSX, DOCX, PDF, SVG, PNG, JSON plus traffic route/segment, hotspot screening and congestion-weighted kernel maps. DOCX reports include performance, distributions, reliability, congestion episodes, peak/day-type analysis, historical+live evidence, cartography, intervention interpretation, recommendations, validation/limitations, methods and reproducibility metadata.
