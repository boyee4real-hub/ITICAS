# ITICAS Stage 06 — Security, Validation and Dual Deployment Foundation

Stage 06 establishes these requirements as architecture, not later retrofits:

- Nationwide Nigeria operation in all runtime modules.
- Authentication before dashboard/API use.
- Pending registration + administrator approval.
- Granular module permissions.
- Scrypt password hashing and opaque server-side sessions.
- Login throttling/account lockout and audit records.
- Benchmark source registry and validation records for observations.
- Every live-result API can carry source, reference, deviation, agreement, confidence,
  provenance, standard alignment, independence level, uncertainty and limitations.
- Current TomTom free-flow comparison is explicitly identified as a provider-reference
  validation, not independent ground truth.
- Data/metadata model is aligned conceptually with OGC SensorThings API and OGC
  Observations, Measurements and Samples.
- Shared FastAPI core supports web deployment and a Windows standalone executable.
- Frozen EXE assets are packaged, while persistent standalone data are stored under
  %LOCALAPPDATA%\ITICAS rather than the temporary PyInstaller extraction directory.
- Existing C:\iticas database and TomTom credentials are preserved.

Production web deployment must use HTTPS and set SECURITY_COOKIE_SECURE=true.
