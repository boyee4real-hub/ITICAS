ITICAS FINAL RELEASE QUALIFICATION
==================================
This overlay does not reset the database, .env, Supabase archive, users, credentials,
monitoring locations, historical observations, prediction records or research outputs.

It adds a final integrated release gate and removes the one remaining Ibadan-specific
operational default on the Historical Data page. Examples mentioning Nigerian roads are
still allowed; application logic is nationwide.

The qualification verifies:
- Stage 26 / v0.26.0 release identity
- required application modules/assets
- nationwide historical default selection
- map click/reverse-identification/live-traffic contracts
- prediction calibration/verification/export contracts
- source secret hygiene
- SQLite integrity and operational data inventory
- live Supabase autonomous archive recency/health when configured
- one live TomTom flow request using the first active geocoded monitoring location
- complete current pytest regression suite

Live checks do not print credentials.
Reports are written to reports\final_release_qualification\.
