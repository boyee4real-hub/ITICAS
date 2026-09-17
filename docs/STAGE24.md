# ITICAS Stage 24 — Map Road Selection + Prediction Decision Deliverables

Stage 24 extends the validated Stage 23 predictive baseline without replacing it.

## Road selection on the live map
A click on the OSM map now performs a Nigeria-scoped TomTom reverse-geocoding lookup, identifies the nearest named road/address, and immediately evaluates live traffic at that coordinate. The inspector shows the road name, address/context, coordinates, current speed, free-flow speed, congestion index, delay, confidence, incidents, weather and nearby ITICAS stored history. If a monitored ITICAS location is nearby, the user can hand it directly to the Prediction page.

OSM remains the basemap only. Traffic measurements remain provider-derived and provenance-labelled.

## Prediction decision intelligence
The prediction engine now derives operational decision signals from the completed forecast while preserving validation, uncertainty and evidence grading. Metrics include mean/peak predicted congestion, minimum predicted speed, moderate/heavy shares, uncertainty width and top peak windows.

## Downloadable deliverables
Users can download forecast CSV, full prediction JSON and the on-screen forecast chart SVG individually. A full Prediction Decision Package ZIP contains forecast/model/decision/peak tables, multiple SVG figures, a forecast road decision map, JSON provenance and an executive HTML decision brief.

The map export uses stored provider segment geometry when available. If segment geometry is not available, ITICAS explicitly states this rather than inventing a road line.
