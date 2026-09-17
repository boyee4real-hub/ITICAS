# Stage 02 — Persistent Data Foundation

Adds the persistent SQLite data layer for rapid local development.

Tables:
- monitoring_locations
- traffic_observations
- traffic_incidents
- weather_observations

The architecture keeps provider/source timestamps and provenance fields so real online data can be audited later.

Stage 03 will populate a verified Ibadan monitoring catalogue rather than invent coordinates.
