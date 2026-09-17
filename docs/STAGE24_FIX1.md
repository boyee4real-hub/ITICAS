# Stage 24 Fix 1

This fix makes map selection road-centric rather than point-only while retaining the click point as provenance.

The road name is resolved primarily with TomTom Search reverse geocoding. When that result is generic or unnamed, ITICAS performs a cached, low-volume OpenStreetMap/Nominatim reverse lookup. Traffic values continue to come from TomTom Traffic; OSM/Nominatim is not treated as a traffic-measurement source.

The map draws the genuine selected-road/segment geometry when supplied by OSM reverse geometry or TomTom Flow Segment Data. It does not invent a road polyline.
