# Optional GitHub Actions fallback

Supabase Cron is the preferred scheduler.

This workflow can call the same Supabase Edge Function every 15 minutes if you want a second scheduler.
For public repositories, standard GitHub-hosted Actions are free; scheduled public-repo workflows can be disabled after 60 days with no repository activity, so do not treat GitHub as the sole long-term scheduler unless you actively maintain the repository.
