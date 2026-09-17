ITICAS Stage 22 Fix 1 - Cloud Archive Monitoring Location Dropdown

Cause fixed:
The Stage 22 JavaScript used the identifier `location`, which collides with the browser's built-in `window.location` object. As a result, the Monitoring location <select> was not populated even though /api/locations was valid.

Fix:
- Uses explicit document.getElementById('location') references.
- Adds a visible "Select a monitoring location..." prompt.
- Adds clear empty/error states.
- Uses explicit DOM references in readiness, export, and cloud-import actions.
- Does not alter the database, .env, Supabase archive, Cron, Edge Function, or accumulated observations.
