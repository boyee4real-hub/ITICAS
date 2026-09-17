ITICAS STAGE 22 FIX 4 — REPORT AXES + INTRA-ROAD HOTSPOT EVIDENCE

What this fixes
1. Adds explicit x- and y-axis titles to analytical graphs/heatmaps where they were missing:
   - Road congestion day-hour heatmap: x = Hour of day (WAT), y = Date
   - Delay & travel-time reliability: x = Evidence sequence, y = Delay (seconds)
   - Congestion severity distribution: x = Congestion severity class, y = Observations (count)
   - Clock-hour congestion profile: x = Hour of day (WAT), y = Mean congestion index
   - Data completeness & provenance: x = Hour of day (WAT), y = Date

2. Replaces the old road-wide single-colour congestion evidence map with an evidence-gated
   intra-road hotspot map whenever corridor-probe observations exist.

Hotspot method
- ITICAS uses actual CorridorProbeObservation records for the selected road and requested period.
- Each probe is coloured by its measured mean congestion index.
- Adjacent probe sections are coloured from local probe evidence.
- Descriptive hotspot probes are the upper-quartile mean-CI probes, with an absolute CI floor of 0.20.
- Hotspots are shown with red halo rings.
- This is descriptive probe-level hotspot evidence, NOT Getis-Ord Gi* statistical significance.
- If the selected road has no point-specific probe observations, ITICAS does not fabricate hotspots.

Important
The autonomous Supabase archive, Cron, Edge Function, TomTom keys, local database, .env, users,
monitoring locations and accumulated traffic history are not modified.

After installation
Restart ITICAS and regenerate the Mokola report/complete research ZIP. Previously exported PNGs
will not change automatically; the newly generated figures will contain the corrected labels/hotspots.
