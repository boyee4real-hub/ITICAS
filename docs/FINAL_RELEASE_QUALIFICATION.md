# ITICAS Final Release Qualification

Stage 26 / v0.26.0 is the frozen feature release. This qualification overlay adds no new scientific model. It certifies the integrated application and fixes one residual nationwide-scope issue: Historical Data no longer prefers Mokola; it selects the first active geocoded monitoring location unless the user selects another.

A release PASS requires no failed static/database/cloud/provider checks. WARN is reserved for an unavailable optional configuration in non-production environments. On the operational installation, Supabase and TomTom are expected to be configured, so failures in either are surfaced explicitly.

The qualification report is generated locally and does not include API keys or passwords.
