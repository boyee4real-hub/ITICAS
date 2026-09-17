# ITICAS Stage 12 — Critical Repairs + Spatial Decision Intelligence

## Repairs
- Restores missing `/api/historical/...` routes that caused `Not Found` and blank historical metrics.
- Adds an 8-second vector-basemap watchdog and a user-controlled raster fallback so a stalled OpenFreeMap style does not leave the map blank indefinitely.
- Preserves nationwide search and live traffic evaluation separately from basemap rendering.

## Report upgrade
- Publication-oriented PNG at 300 DPI with labelled axes, scale, legend, validation status, coverage and report identity.
- Larger DOCX/PDF report structure covering executive summary, provenance, reliability, persistence/severity, hourly/day-type dynamics, decision priority, recommendations, validation, methodology and reproducibility.
- Adds TTI, PTI, Buffer Index, congestion persistence shares, provider confidence and experimental ITICAS Decision Priority Score.
- ZIP research package now adds speed-vs-free-flow, daily congestion and data-completeness figures.

## Spatial intelligence
- Congestion-weighted Getis-Ord Gi* screening over monitoring-location congestion values.
- Congestion-weighted Gaussian kernel exposure so point density is not confused with congestion severity.
- Nationwide intervention-priority ranking.
- Statistical caveats are explicit, especially for small sample networks.

## Scientific integrity
The ITICAS Decision Priority Score is experimental and transparent, not an external standard. Provider-reference validation remains explicitly non-independent until an independent traffic benchmark is configured.
