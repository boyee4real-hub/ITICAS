from __future__ import annotations
from pathlib import Path
import os

def status():
    gateway=(os.getenv("ITICAS_GATEWAY_URL") or "").strip()
    smtp_host=(os.getenv("ITICAS_SMTP_HOST") or "").strip()
    smtp_user=(os.getenv("ITICAS_SMTP_USER") or "").strip()
    smtp_password=bool((os.getenv("ITICAS_SMTP_PASSWORD") or "").strip())
    central_db=(os.getenv("ITICAS_CENTRAL_DATABASE_URL") or "").strip()
    provider_secret_server_side=bool((os.getenv("TOMTOM_API_KEY") or os.getenv("TOMTOM_API_KEYS") or "").strip())
    https=gateway.lower().startswith("https://")
    checks={
      "central_access_module":Path("backend/app/central_access.py").exists(),
      "gateway_configured":bool(gateway),
      "gateway_https":https,
      "persistent_central_database_configured":bool(central_db),
      "smtp_configured":bool(smtp_host and smtp_user and smtp_password),
      "server_side_provider_secret_present":provider_secret_server_side,
    }
    return {
      "checks":checks,
      "passed":sum(bool(v) for v in checks.values()),
      "total":len(checks),
      "secrets_exposed":False,
      "gateway_scheme":"https" if https else ("configured_non_https" if gateway else "missing"),
      "production_central_access_ready":all(checks.values()),
      "note":"No secret values are returned by this endpoint."
    }
