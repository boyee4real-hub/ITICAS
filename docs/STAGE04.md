# ITICAS Stage 04 — Nigeria Live Traffic Provider Integration

Primary provider: TomTom Traffic API.

Why TomTom is primary:
- TomTom's official Traffic API market coverage explicitly lists Nigeria for both Traffic Flow and Traffic Incidents.
- Flow Segment Data service version 4 provides current speed, free-flow speed, current/free-flow travel time, confidence and road-closure status for the road segment nearest a monitoring coordinate.
- Incident Details service version 5 provides present incidents inside a bounding box.

Implementation:
- Flow request: `traffic/services/4/flowSegmentData/absolute/10/json`
- `unit=kmph` is explicitly requested, so stored speeds are already km/h.
- Incident request: `traffic/services/5/incidentDetails`, `timeValidityFilter=present`.
- Each provider response is normalized into the persistent ITICAS traffic tables.
- Raw provider fragments are retained for provenance.
- API credentials are local only and are never returned by provider-status endpoints.
- Missing credentials do not break Stage 04 installation or regression tests.

Run `CONFIGURE_TOMTOM_API_KEY.cmd` after you obtain a TomTom API key.
