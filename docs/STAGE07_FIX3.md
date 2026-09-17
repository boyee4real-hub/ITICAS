# ITICAS Stage 07 Search Transport Fix 3 (v0.7.3)

The deployed Windows host independently returned HTTP 200 from both TomTom Fuzzy Search and Traffic Flow using the stored API key via Python `urllib`. The ITICAS Search route, however, returned an upstream HTTP 401 while using `httpx`.

This corrective overlay changes only the TomTom Search transport to Python's standard-library `urllib`, executed through `asyncio.to_thread` so the FastAPI event loop remains responsive. Traffic acquisition, monitoring, security, validation, database history, map behavior, credentials and nationwide architecture remain unchanged.

Search remains constrained to Nigeria with `countrySet=NG` and continues to support roads, junctions, towns, cities, LGAs, states, landmarks and coordinate-based evaluation workflows.
