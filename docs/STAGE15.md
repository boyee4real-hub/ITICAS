# ITICAS Stage 15 — Interactive Map, Temporal Evidence & Decision Atlas

Stage 15 is a functional/reporting quality upgrade on the validated Stage 14.1 baseline.

## Map interaction
- mouse-wheel zoom
- drag/pan
- double-click zoom
- zoom buttons
- search-result auto-zoom
- click-to-evaluate remains available
- server-rendered/cache-backed basemap remains the rendering source

## Temporal analytics
The long-period profile no longer renders hundreds of tiny missing-hour bars. It plots only evidence-bearing hourly points against the full requested time axis, with missing periods left as true gaps. A separate 24-hour clock profile shows recurrent time-of-day behavior.

## Spatial/network inference
Duplicate location/road labels are suppressed. Getis-Ord Gi* hotspot significance is withheld when route-level temporal evidence is below 20% coverage or fewer than 24 evidence-bearing hours. Sparse-network values remain screening statistics only.

## Selected-road decision atlas
The report package now contains eight distinct products:
1. selected road / segment context map
2. single-road congestion evidence map
3. day-hour congestion heatmap
4. delay and travel-time reliability profile
5. congestion severity distribution
6. clock-hour congestion profile
7. data completeness and provenance map
8. road decision dashboard

Network-wide hotspot/KDE analysis remains separate from single-road reporting.
