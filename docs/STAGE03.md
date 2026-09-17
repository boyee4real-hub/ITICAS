# ITICAS Stage 03 — Ibadan Monitoring Location Manager

Stage 03 adds:
- a persistent location management UI at `/locations`;
- curated Ibadan traffic-monitoring location names;
- create/update/delete location API endpoints;
- coordinate provenance fields;
- optional one-time OpenStreetMap Nominatim coordinate resolution;
- cached geocoding so already-resolved locations are not requested again;
- monitoring radius per location.

The public Nominatim geocoder is intentionally used conservatively:
- one request at a time;
- >1 second between requests;
- identifying User-Agent;
- local caching;
- no autocomplete;
- OSM attribution shown in the application.

Coordinates are not treated as traffic ground truth. They identify monitoring points; live traffic observations arrive in later stages from traffic-data providers.

Stage 04 will add the provider adapter layer for real traffic flow/incidents.
