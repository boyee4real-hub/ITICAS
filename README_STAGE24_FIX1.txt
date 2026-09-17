ITICAS Stage 24 Fix 1 — Click-Road Identification + Line Highlight

Purpose
- A map click remains visible as a small evidence point.
- The identified road/traffic segment is highlighted as a line.
- TomTom reverse geocoding remains primary.
- If TomTom returns only a generic result such as "Nigeria", a low-volume cached OpenStreetMap/Nominatim reverse-geocoding fallback attempts to identify the road.
- TomTom Flow Segment geometry is parsed whether returned as an object or a direct coordinate array.
- If no OSM road geometry is available, genuine TomTom flow geometry is used as the selected segment line when available.

Scientific/UI meaning
- Point = exact coordinate clicked by the user.
- Cyan line = selected/identified road or segment.
- Severity-coloured line = live provider flow segment and current congestion state.
- No road geometry is fabricated when neither provider supplies genuine geometry.
