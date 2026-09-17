# ITICAS Stage 07 — National Traffic Explorer

Stage 07 makes nationwide search and on-demand traffic evaluation an operational capability.

## Core capability
Users can search a road, junction, town, city, LGA, state, landmark or coordinates anywhere in Nigeria. Search is not limited to preconfigured monitoring points.

## Search and evaluation
- TomTom Search API Fuzzy Search v2, constrained with `countrySet=NG`
- TomTom Traffic Flow Segment Data v4
- TomTom Traffic Incident Details v5
- interactive Leaflet map
- configurable OpenStreetMap raster base map for development
- map-click evaluation
- add a selected result to the ITICAS monitoring catalogue
- clear separation of on-demand live-provider output from nearest stored ITICAS history

## Scientific validation
Stage 07 continues Stage 06 benchmark metadata. The current operational benchmark relationship compares live speed with TomTom free-flow speed and is explicitly marked `provider_reference`, not independent ground truth.

## Security
All search, evaluation and monitoring-location creation endpoints require authenticated/authorized access and generate audit events.

## Deployment
The same FastAPI/search/traffic core is used by web and Windows EXE deployment modes.

## Production map note
The default OpenStreetMap tile server is intended for compliant development/light use. A production deployment should configure an appropriate tile provider or self-hosted tile service while retaining OpenStreetMap attribution where applicable.
